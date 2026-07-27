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
MIN_AGG_SIZE = 2  # agglomerative clusters smaller than this become noise
LABEL_MATCH_THRESHOLD = 0.80
ARG_ASSIGN_THRESHOLD = 0.35


def _is_fallback_label(label: str) -> bool:
    """True for generic auto-labels like 'Tema 3' that must not be reused."""
    import re
    return bool(re.fullmatch(r"\s*Tema\s+\d+\s*", label or ""))


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

    # Agglomerative fallback (cosine distance on normalized vecs).
    # Single-niche corpora (e.g. all-menopause) sit at high mutual cosine
    # similarity, so a loose threshold collapses everything into one blob.
    # A tighter default splits real sub-themes; tune via scraper_config.
    from collections import Counter

    from core.models import ScraperConfig
    from sklearn.cluster import AgglomerativeClustering

    cfg_th = ScraperConfig.get("cluster_distance_threshold", {"value": 0.30})
    k_threshold = cfg_th.get("value", 0.30) if isinstance(cfg_th, dict) else cfg_th
    labels = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average",
        distance_threshold=k_threshold,
    ).fit_predict(matrix)

    # Fold singleton clusters into noise (-1) so every named theme is
    # backed by at least MIN_AGG_SIZE reels.
    sizes = Counter(labels)
    labels = np.array([l if sizes[l] >= MIN_AGG_SIZE else -1 for l in labels])
    probs = np.ones(n, dtype=np.float32)
    n_noise = int(np.sum(labels == -1))
    return labels, probs, "agglomerative", {
        "distance_threshold": k_threshold, "min_size": MIN_AGG_SIZE, "noise": n_noise}


def _name_cluster(sample_texts: list[str]) -> dict:
    if not client.available():
        return {}
    samples = "\n\n".join(f"- {t[:300]}" for t in sample_texts[:5])
    user = prompts.CLUSTER_NAME_USER_TEMPLATE.format(samples=samples)
    try:
        # Extra retries: naming runs right after the argument-extraction burst,
        # so HF can be rate-limited here.
        # Naming a theme is judgement, not extraction: it decides how the
        # whole Second Brain is organised.
        data = client.chat_json(prompts.CLUSTER_NAME_SYSTEM, user, max_tokens=300,
                                retries=4, model=client.model_for("analysis"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cluster] naming failed: %r", exc)
        return {}


def _prior_clusters(scope: str) -> list[tuple[np.ndarray, dict]]:
    prev = ClusterRun.objects.filter(scope=scope, is_current=True).first()
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
    """Cluster each scope (competitor + owned) into its own current run."""
    results = {}
    for scope in ("competitor", "owned"):
        results[scope] = _run_scope(scope)
    # Refresh client-supplied custom-topic matches over the (possibly new)
    # reel/doc embeddings produced above.
    try:
        from core import custom_topics
        results["custom_topics"] = custom_topics.recompute_matches()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cluster] custom-topic refresh failed: %r", exc)
    return results


def _run_scope(scope: str) -> dict:
    reels = list(
        Reel.objects.filter(enrich_status=DONE, is_active=True,
                            account__owner_type=scope)
        .select_related("enrichment", "transcript", "embedding")
    )
    emb_map = _ensure_reel_embeddings(reels)
    reels = [r for r in reels if r.id in emb_map]

    # Assets = reels (both scopes) + blog documents (owned scope only), so the
    # Second Brain clusters span every Medyca asset, not just reels.
    assets = [{"kind": "reel", "obj": r, "vec": emb_map[r.id],
               "text": _reel_text(r, getattr(r, "enrichment", None))} for r in reels]
    docs = []
    if scope == "owned":
        from core.models import KnowledgeDocument
        docs = [d for d in KnowledgeDocument.objects.filter(is_active=True).exclude(embedding=[])]
        for d in docs:
            assets.append({
                "kind": "doc", "obj": d,
                "vec": np.asarray(d.embedding, dtype=np.float32),
                "text": f"{d.title}\n{d.summary_it}\n{' '.join(d.topics)}",
            })

    if len(assets) < MIN_DOCS:
        return {"skipped": True, "scope": scope,
                "note": f"need >= {MIN_DOCS} enriched {scope} assets, have {len(assets)}"}

    matrix = np.vstack([a["vec"] for a in assets])

    labels, probs, algo, params = _cluster(matrix)
    unique = sorted(set(int(l) for l in labels if l != -1))
    n_noise = int(np.sum(labels == -1))

    prior = _prior_clusters(scope)

    run_obj = ClusterRun.objects.create(
        scope=scope, algorithm=algo, params=params, n_reels=len(reels),
        n_clusters=len(unique), n_noise=n_noise, status="running",
    )

    label_to_cluster: dict[int, TopicCluster] = {}
    # A prior label may only be inherited by ONE new cluster. Without this,
    # several clusters that all sit close to the same old centroid inherit the
    # same name, and the UI shows "Terapie Ormonali Menopausa" three times.
    used_labels: set[str] = set()
    for pos, lab in enumerate(unique):
        idxs = [i for i, l in enumerate(labels) if l == lab]
        centroid = matrix[idxs].mean(axis=0)
        centroid /= (np.linalg.norm(centroid) or 1.0)

        # Label stability: reuse a prior label if centroids are close — but
        # never propagate a generic "Tema N" fallback from an earlier run.
        reused = None
        best_sim = LABEL_MATCH_THRESHOLD
        for pcent, pinfo in prior:
            label = pinfo.get("label_it", "")
            if _is_fallback_label(label) or label in used_labels:
                continue
            sim = float(np.dot(centroid, pcent))
            if sim >= best_sim:  # keep the closest match, not merely the first
                best_sim, reused = sim, pinfo
        if reused:
            naming = reused
        else:
            import time as _t
            _t.sleep(1.0)  # space out naming calls to avoid rate limits
            sample_texts = [assets[i]["text"] for i in idxs[:5]]
            naming = _name_cluster(sample_texts)

        label = (naming.get("label_it") or "").strip()
        if not label or label in used_labels:
            # Still colliding (the namer produced a duplicate): disambiguate
            # with the cluster's own top keyword rather than shipping twins.
            kws = naming.get("keywords") if isinstance(naming.get("keywords"), list) else []
            extra = next((k for k in kws if k and k.lower() not in label.lower()), "")
            label = f"{label} · {extra}".strip(" ·") if extra else f"Tema {pos + 1}"
        if label in used_labels:
            label = f"{label} ({pos + 1})"
        used_labels.add(label)

        cluster = TopicCluster.objects.create(
            run=run_obj,
            label_it=label[:120],
            description_it=naming.get("description_it", ""),
            keywords=naming.get("keywords", [])[:6] if isinstance(naming.get("keywords"), list) else [],
            centroid=centroid.tolist(),
            size=len(idxs),
            position=pos,
        )
        label_to_cluster[lab] = cluster

    # Assign each asset (reel or blog doc) to its cluster.
    from core.models import DocClusterAssignment
    reel_rows, doc_rows = [], []
    for i, a in enumerate(assets):
        cluster = label_to_cluster.get(int(labels[i]))
        if a["kind"] == "reel":
            reel_rows.append(ReelClusterAssignment(
                run=run_obj, reel=a["obj"], cluster=cluster, probability=float(probs[i])))
        else:
            doc_rows.append(DocClusterAssignment(
                run=run_obj, document=a["obj"], cluster=cluster, probability=float(probs[i])))
    ReelClusterAssignment.objects.bulk_create(reel_rows)
    DocClusterAssignment.objects.bulk_create(doc_rows)
    params["n_docs"] = len(doc_rows)

    # ── Layer 2: arguments (reels only) ─────────────────────────────────────
    reel_idx = [i for i, a in enumerate(assets) if a["kind"] == "reel"]
    reel_list = [assets[i]["obj"] for i in reel_idx]
    reel_labels = np.array([labels[i] for i in reel_idx])
    reel_matrix = matrix[reel_idx] if reel_idx else matrix
    arg_assigned = _assign_arguments(run_obj, unique, reel_labels, reel_matrix, reel_list, label_to_cluster)

    # Flip current atomically, within this scope only.
    with transaction.atomic():
        ClusterRun.objects.filter(scope=scope, is_current=True).update(is_current=False)
        run_obj.status = "done"
        run_obj.is_current = True
        run_obj.save(update_fields=["status", "is_current"])

    _prune_old_runs(scope)

    return {"scope": scope, "algorithm": algo, "reels": len(reels),
            "clusters": len(unique), "noise": n_noise, "arguments_assigned": arg_assigned}


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


def _prune_old_runs(scope: str, keep: int = 10):
    ids = list(
        ClusterRun.objects.filter(scope=scope)
        .order_by("-created_at").values_list("id", flat=True)[:keep]
    )
    ClusterRun.objects.filter(scope=scope).exclude(id__in=ids).delete()
