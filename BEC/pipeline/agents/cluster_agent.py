"""
pipeline/agents/cluster_agent.py
================================
ClusterAgent — the two-layer DAG clustering step.

Layer 1 (topics):
  - embed each enriched reel (local sentence-transformers, cached)
  - cluster with HDBSCAN; fall back to Agglomerative for tiny/degenerate
    corpora
  - name each cluster in Italian via one HF LLM call from centroid-nearest
    reels, reusing prior labels for stable clusters (centroid cosine >= 0.8)

Layer 2 (arguments):
  - embed each ReelArgument, assign to the nearest topic-cluster centroid
    (cosine < 0.35 -> noise)

Each run writes a fresh ClusterRun; is_current is flipped atomically at
the end. The API only ever serves is_current=True.
"""

from __future__ import annotations

import logging

import numpy as np
from django.conf import settings
from django.db import transaction

from core.models import (
    DONE, ArgumentAssignment, ClusterRun, Enrichment, Reel, ReelArgument,
    ReelClusterAssignment, ReelEmbedding, TopicCluster,
)
from llm import client, prompts

logger = logging.getLogger(__name__)

_embedder = None
MIN_DOCS = 8
LABEL_MATCH_THRESHOLD = 0.80
ARG_ASSIGN_THRESHOLD = 0.35


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        logger.info("[cluster] loading embedder %s", settings.EMBEDDINGS_MODEL)
        _embedder = SentenceTransformer(settings.EMBEDDINGS_MODEL)
    return _embedder


def _embed(texts: list[str]) -> np.ndarray:
    model = _get_embedder()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def _reel_text(reel: Reel, enr: Enrichment | None) -> str:
    parts = []
    if enr and enr.summary_it:
        parts.append(enr.summary_it)
    if enr and enr.topics:
        parts.append(" ".join(enr.topics))
    tr = getattr(reel, "transcript", None)
    if tr and tr.text:
        parts.append(tr.text[:600])
    if not parts:
        parts.append(reel.caption[:600])
    return "\n".join(parts)


def _ensure_reel_embeddings(reels: list[Reel]) -> dict[int, np.ndarray]:
    """Return {reel_id: vector}, embedding+caching any missing ones."""
    out: dict[int, np.ndarray] = {}
    to_embed: list[tuple[int, str]] = []
    for reel in reels:
        emb = getattr(reel, "embedding", None)
        if emb and emb.model_name == settings.EMBEDDINGS_MODEL and emb.vector:
            out[reel.id] = np.asarray(emb.vector, dtype=np.float32)
        else:
            enr = getattr(reel, "enrichment", None)
            to_embed.append((reel.id, _reel_text(reel, enr)))
    if to_embed:
        vecs = _embed([t for _, t in to_embed])
        for (rid, _), vec in zip(to_embed, vecs):
            ReelEmbedding.objects.update_or_create(
                reel_id=rid,
                defaults={"vector": vec.tolist(), "model_name": settings.EMBEDDINGS_MODEL},
            )
            out[rid] = vec
    return out


def _cluster(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, str, dict]:
    """Return (labels, probabilities, algorithm, params). -1 = noise."""
    n = len(matrix)
    # HDBSCAN for reasonable corpora
    if n >= 60:
        try:
            import hdbscan

            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=4, min_samples=2, metric="euclidean",
                cluster_selection_method="leaf",
            )
            labels = clusterer.fit_predict(matrix)
            probs = clusterer.probabilities_
            n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
            noise_frac = float(np.mean(labels == -1))
            if n_clusters >= 3 and noise_frac <= 0.6:
                return labels, probs, "hdbscan", {
                    "min_cluster_size": 4, "min_samples": 2, "noise_frac": round(noise_frac, 2)}
            logger.info("[cluster] HDBSCAN degenerate (clusters=%s noise=%.2f), "
                        "falling back", n_clusters, noise_frac)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cluster] HDBSCAN failed: %r — falling back", exc)

    # Agglomerative fallback (cosine distance on normalized vecs)
    from sklearn.cluster import AgglomerativeClustering

    k_threshold = 0.45
    labels = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average",
        distance_threshold=k_threshold,
    ).fit_predict(matrix)
    probs = np.ones(n, dtype=np.float32)
    return labels, probs, "agglomerative", {"distance_threshold": k_threshold}


def _name_cluster(sample_texts: list[str]) -> dict:
    if not client.available():
        return {}
    samples = "\n\n".join(f"- {t[:300]}" for t in sample_texts[:5])
    user = prompts.CLUSTER_NAME_USER_TEMPLATE.format(samples=samples)
    try:
        data = client.chat_json(prompts.CLUSTER_NAME_SYSTEM, user, max_tokens=300)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cluster] naming failed: %r", exc)
        return {}


def _prior_clusters() -> list[tuple[np.ndarray, dict]]:
    prev = ClusterRun.objects.filter(is_current=True).first()
    if not prev:
        return []
    out = []
    for c in prev.clusters.all():
        if c.centroid:
            out.append((np.asarray(c.centroid, dtype=np.float32),
                        {"label_it": c.label_it, "description_it": c.description_it,
                         "keywords": c.keywords}))
    return out


def run(ctx) -> dict:
    reels = list(
        Reel.objects.filter(enrich_status=DONE, is_active=True)
        .select_related("enrichment", "transcript", "embedding")
    )
    if len(reels) < MIN_DOCS:
        return {"skipped": True, "note": f"need >= {MIN_DOCS} enriched reels, have {len(reels)}"}

    emb_map = _ensure_reel_embeddings(reels)
    reels = [r for r in reels if r.id in emb_map]
    matrix = np.vstack([emb_map[r.id] for r in reels])

    labels, probs, algo, params = _cluster(matrix)
    unique = sorted(set(int(l) for l in labels if l != -1))
    n_noise = int(np.sum(labels == -1))

    prior = _prior_clusters()

    run_obj = ClusterRun.objects.create(
        algorithm=algo, params=params, n_reels=len(reels),
        n_clusters=len(unique), n_noise=n_noise, status="running",
    )

    label_to_cluster: dict[int, TopicCluster] = {}
    for pos, lab in enumerate(unique):
        idxs = [i for i, l in enumerate(labels) if l == lab]
        centroid = matrix[idxs].mean(axis=0)
        centroid /= (np.linalg.norm(centroid) or 1.0)

        # Label stability: reuse a prior label if centroids are close.
        reused = None
        for pcent, pinfo in prior:
            if float(np.dot(centroid, pcent)) >= LABEL_MATCH_THRESHOLD:
                reused = pinfo
                break
        if reused:
            naming = reused
        else:
            sample_texts = [
                _reel_text(reels[i], getattr(reels[i], "enrichment", None)) for i in idxs[:5]
            ]
            naming = _name_cluster(sample_texts)

        cluster = TopicCluster.objects.create(
            run=run_obj,
            label_it=(naming.get("label_it") or f"Tema {pos + 1}")[:120],
            description_it=naming.get("description_it", ""),
            keywords=naming.get("keywords", [])[:6] if isinstance(naming.get("keywords"), list) else [],
            centroid=centroid.tolist(),
            size=len(idxs),
            position=pos,
        )
        label_to_cluster[lab] = cluster

    # Reel assignments
    assignments = []
    for i, reel in enumerate(reels):
        lab = int(labels[i])
        cluster = label_to_cluster.get(lab)
        assignments.append(ReelClusterAssignment(
            run=run_obj, reel=reel, cluster=cluster, probability=float(probs[i]),
        ))
    ReelClusterAssignment.objects.bulk_create(assignments)

    # ── Layer 2: arguments ──────────────────────────────────────────────────
    arg_assigned = _assign_arguments(run_obj, unique, labels, matrix, reels, label_to_cluster)

    # Flip current atomically
    with transaction.atomic():
        ClusterRun.objects.filter(is_current=True).update(is_current=False)
        run_obj.status = "done"
        run_obj.is_current = True
        run_obj.save(update_fields=["status", "is_current"])

    _prune_old_runs()

    return {"algorithm": algo, "reels": len(reels), "clusters": len(unique),
            "noise": n_noise, "arguments_assigned": arg_assigned}


def _assign_arguments(run_obj, unique, labels, matrix, reels, label_to_cluster) -> int:
    args = list(ReelArgument.objects.filter(reel__in=reels))
    if not args:
        return 0
    # Ensure argument embeddings
    to_embed = [(a.id, a.text_it) for a in args if not a.embedding]
    if to_embed:
        vecs = _embed([t for _, t in to_embed])
        by_id = {}
        for (aid, _), vec in zip(to_embed, vecs):
            by_id[aid] = vec.tolist()
        for a in args:
            if a.id in by_id:
                a.embedding = by_id[a.id]
        ReelArgument.objects.bulk_update([a for a in args if a.id in by_id], ["embedding"])

    # Cluster centroids (normalized)
    centroids = {}
    for lab in unique:
        idxs = [i for i, l in enumerate(labels) if l == lab]
        c = matrix[idxs].mean(axis=0)
        c /= (np.linalg.norm(c) or 1.0)
        centroids[lab] = c

    rows = []
    for a in args:
        if not a.embedding:
            continue
        v = np.asarray(a.embedding, dtype=np.float32)
        v /= (np.linalg.norm(v) or 1.0)
        best_lab, best_sim = None, -1.0
        for lab, c in centroids.items():
            sim = float(np.dot(v, c))
            if sim > best_sim:
                best_sim, best_lab = sim, lab
        cluster = label_to_cluster.get(best_lab) if best_sim >= ARG_ASSIGN_THRESHOLD else None
        rows.append(ArgumentAssignment(
            run=run_obj, argument=a, cluster=cluster, similarity=best_sim,
        ))
    ArgumentAssignment.objects.bulk_create(rows)
    return len(rows)


def _prune_old_runs(keep: int = 10):
    ids = list(ClusterRun.objects.order_by("-created_at").values_list("id", flat=True)[:keep])
    ClusterRun.objects.exclude(id__in=ids).delete()
