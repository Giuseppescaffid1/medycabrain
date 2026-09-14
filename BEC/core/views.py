import logging
import os
from pathlib import Path

from django.contrib.auth import authenticate
from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import models, serializers
from .filters import ReelFilter

logger = logging.getLogger(__name__)


# ── Auth ───────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get("username", "")
    password = request.data.get("password", "")
    user = authenticate(username=username, password=password)
    if not user:
        return Response({"detail": "Credenziali non valide."}, status=status.HTTP_401_UNAUTHORIZED)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": serializers.UserSerializer(user).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    return Response(serializers.UserSerializer(request.user).data)


# ── Accounts ───────────────────────────────────────────────────────────────────

class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.AccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return models.TrackedAccount.objects.annotate(
            reel_count=Count("reels", filter=Q(reels__is_active=True))
        ).order_by("username")

    def perform_destroy(self, instance):
        # Soft delete: deactivate, keep reels.
        instance.is_active = False
        instance.save(update_fields=["is_active"])


class BlogSourceViewSet(viewsets.ModelViewSet):
    """The blogs we crawl — the TrackedAccount of the article world.

    Creating one queues a discovery job immediately: the whole promise of
    this screen is "paste a URL, the agent does the rest", and a source that
    sits empty until the nightly run breaks that promise on first use.
    """

    serializer_class = serializers.BlogSourceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return models.BlogSource.objects.annotate(
            document_count=Count("documents", filter=Q(documents__is_active=True))
        ).order_by("name")

    def _queue_crawl(self, source, force=False):
        job = _existing_job("blogsource_discover", {"source_id": source.id})
        if job:
            return job
        job = models.Job.objects.create(
            kind="blogsource_discover",
            params={"source_id": source.id, "force": force},
            message=f"In coda: scansione di {source.name}",
        )
        _spawn_job(job.id)
        return job

    def perform_create(self, serializer):
        source = serializer.save()
        self._queue_crawl(source)

    def perform_destroy(self, instance):
        # Soft delete, AND the documents go with it. Unlike an Instagram
        # account — whose reels are the client's own library — a removed
        # competitor blog must leave the analysis, or the client deletes a
        # source and the gap engine keeps quoting it.
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        instance.documents.update(is_active=False)

    @action(detail=True, methods=["post"], url_path="crawl")
    def crawl(self, request, pk=None):
        source = self.get_object()
        job = self._queue_crawl(source, force=True)
        return Response({"job_id": job.id, "status": job.status})

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request, pk=None):
        """Deactivation is automatic after repeated failures; coming back is
        a human decision, and it gets one fresh chance immediately."""
        source = self.get_object()
        source.is_active = True
        source.consecutive_failures = 0
        source.last_error = ""
        source.save(update_fields=["is_active", "consecutive_failures", "last_error"])
        source.documents.update(is_active=True)
        job = self._queue_crawl(source, force=True)
        return Response({"job_id": job.id, "status": job.status})


class UploadedMediaViewSet(viewsets.ModelViewSet):
    """The client's own audio/video interviews entering the knowledge bank.

    Two ways in, one list out:

    * POST a file (multipart) → stored, transcription job queued, 202 with the
      job id.
    * POST /from-links/ with a blob of text → every video link in it becomes a
      row, titles fetched from the provider, one job each.

    Either way the transcript becomes a KnowledgeDocument and a blog draft, off
    the request; the UI polls. GET lists everything with its status.
    """

    serializer_class = serializers.UploadedMediaSerializer
    permission_classes = [IsAuthenticated]
    from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "delete", "head", "options"]

    _AUDIO_EXT = {"mp3", "m4a", "wav", "aac", "ogg", "flac", "opus"}
    _VIDEO_EXT = {"mp4", "mov", "m4v", "webm", "mkv", "avi"}

    def get_queryset(self):
        return models.UploadedMedia.objects.all()

    def create(self, request, *args, **kwargs):
        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "Nessun file caricato."}, status=400)
        name = f.name or "upload"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in self._VIDEO_EXT:
            kind = "video"
        elif ext in self._AUDIO_EXT:
            kind = "audio"
        else:
            return Response(
                {"detail": f"Formato non supportato ({ext or '?'}). "
                           "Ammessi audio (mp3, m4a, wav…) e video (mp4, mov…)."},
                status=400)

        up = models.UploadedMedia.objects.create(
            file=f, kind=kind, original_name=name[:300],
            title=(request.data.get("title") or "")[:300],
            size_bytes=getattr(f, "size", 0) or 0,
        )
        job = models.Job.objects.create(
            kind="upload_transcribe", params={"upload_id": up.id},
            message=f"In coda: trascrizione di {up.original_name}",
        )
        _spawn_job(job.id)
        data = self.get_serializer(up).data
        data["job_id"] = job.id
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="from-links",
            parser_classes=[JSONParser])
    def from_links(self, request):
        """Paste a blob of text; every video link in it becomes a row.

        The client sends his notes, not a clean list — "Parte I: <url>", dates,
        names in brackets. `extract_ids` pulls the videos out and collapses the
        spellings of the same video (youtu.be, &t=365s) onto one id, so pasting
        the same list twice adds nothing.

        JSONParser is declared explicitly: this ViewSet is set to multipart for
        the file upload, and without it a JSON body would be rejected here.
        """
        from core.link_ingest import LinkRefused, canonical_url, extract_ids, probe

        text = request.data.get("text") or ""
        owner = request.data.get("owner_type")
        owner = owner if owner in ("owned", "competitor") else "owned"
        inspiration = bool(request.data.get("is_inspiration", True))

        ids = extract_ids(text)
        if not ids:
            return Response(
                {"detail": "Non ho trovato nessun link a un video in quel testo."},
                status=400)

        created, skipped, refused = [], [], []
        for vid in ids:
            url = canonical_url(vid)
            # Already in, as a row or as a document: adding it twice would
            # pay for the same transcription twice.
            if (models.UploadedMedia.objects.filter(source_url=url).exists()
                    or models.KnowledgeDocument.objects.filter(source_url=url).exists()):
                skipped.append(url)
                continue
            try:
                meta = probe(url)
            except LinkRefused as exc:
                refused.append({"url": url, "motivo": str(exc)})
                continue
            up = models.UploadedMedia.objects.create(
                kind="video", source_url=url, channel=meta["channel"],
                title=meta["title"], original_name=meta["title"][:300],
                owner_type=owner, is_inspiration=inspiration,
            )
            job = models.Job.objects.create(
                kind="link_transcribe", params={"upload_id": up.id},
                message=f"In coda: {up.title[:80]}",
            )
            _spawn_job(job.id)
            created.append(self.get_serializer(up).data)

        return Response(
            {"creati": created, "gia_presenti": skipped, "rifiutati": refused},
            status=status.HTTP_202_ACCEPTED)

    def perform_destroy(self, instance):
        # Remove the derived doc too: an interview the client deleted must
        # leave chat/clusters, not linger as a citable source.
        if instance.document_id:
            models.KnowledgeDocument.objects.filter(
                id=instance.document_id).update(is_active=False)
        instance.delete()


# ── Reels ──────────────────────────────────────────────────────────────────────

class ReelViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filterset_class = ReelFilter
    ordering_fields = ["posted_at", "view_count", "like_count", "comment_count"]
    ordering = ["-posted_at"]

    def get_queryset(self):
        qs = models.Reel.objects.select_related("account", "enrichment", "annotation")
        # ?excluded=1 shows what the client removed, so it can be restored.
        if self.request.query_params.get("excluded") in ("1", "true"):
            qs = qs.filter(is_active=False)
        else:
            qs = qs.filter(is_active=True)
        search = self.request.query_params.get("search", "").strip()
        if search:
            vector = SearchVector("caption", config="italian") + SearchVector(
                "transcript__text", config="italian"
            )
            qs = qs.annotate(sv=vector).filter(sv=SearchQuery(search, config="italian"))
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return serializers.ReelDetailSerializer
        return serializers.ReelListSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.action == "list":
            ctx["current_assignments"] = _current_cluster_labels()
        return ctx

    @action(detail=True, methods=["post"], url_path="exclude")
    def exclude(self, request, pk=None):
        """Take a reel out of the dataset (greetings, off-topic guests…).

        is_active is already honoured by every read path — library, analytics,
        clustering, custom topics — so flipping it removes the reel from the
        whole product without deleting anything.
        """
        reel = models.Reel.objects.filter(pk=pk).first()
        if not reel:
            return Response(status=status.HTTP_404_NOT_FOUND)
        reel.is_active = False
        reel.save(update_fields=["is_active"])
        return Response({"id": reel.id, "is_active": False})

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        reel = models.Reel.objects.filter(pk=pk).first()
        if not reel:
            return Response(status=status.HTTP_404_NOT_FOUND)
        reel.is_active = True
        reel.save(update_fields=["is_active"])
        return Response({"id": reel.id, "is_active": True})

    @action(detail=True, methods=["patch"], url_path="annotation")
    def annotation(self, request, pk=None):
        reel = self.get_object()
        ann, _ = models.ReelAnnotation.objects.get_or_create(reel=reel)
        for field in ("is_favorite", "is_inspiration", "note"):
            if field in request.data:
                setattr(ann, field, request.data[field])
        ann.save()
        return Response(serializers.AnnotationSerializer(ann).data)

    @action(detail=True, methods=["post", "delete"], url_path=r"tags(?:/(?P<tag_id>\d+))?")
    def tags(self, request, pk=None, tag_id=None):
        reel = self.get_object()
        ann, _ = models.ReelAnnotation.objects.get_or_create(reel=reel)
        if request.method == "POST":
            tag_id_in = request.data.get("tag_id")
            name = request.data.get("name")
            if tag_id_in:
                tag = models.Tag.objects.get(id=tag_id_in)
            elif name:
                tag, _ = models.Tag.objects.get_or_create(name=name.strip())
            else:
                return Response({"detail": "tag_id o name richiesto."}, status=400)
            ann.tags.add(tag)
            return Response(serializers.AnnotationSerializer(ann).data)
        # DELETE
        if tag_id:
            ann.tags.remove(tag_id)
        return Response(serializers.AnnotationSerializer(ann).data)


def _current_cluster_labels():
    """Map reel_id -> cluster label across both scopes' current runs."""
    current_ids = list(
        models.ClusterRun.objects.filter(is_current=True).values_list("id", flat=True)
    )
    if not current_ids:
        return {}
    rows = (
        models.ReelClusterAssignment.objects
        .filter(run_id__in=current_ids, cluster__isnull=False)
        .values_list("reel_id", "cluster__label_it")
    )
    return dict(rows)


# ── Tags ───────────────────────────────────────────────────────────────────────

class TagViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.TagSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        # Order by how much a tag is actually used (reels + articles), so the
        # picker surfaces the useful ones first instead of alphabetical noise.
        return models.Tag.objects.annotate(
            usage=Count("annotations", distinct=True) + Count("documents", distinct=True)
        ).order_by("-usage", "name")


# ── Clusters ───────────────────────────────────────────────────────────────────

from core.filters import SCOPE_MAP


class ClusterViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = serializers.ClusterSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        # Detail fetch is by id — don't scope-restrict it.
        if self.action == "retrieve":
            return models.TopicCluster.objects.all()
        scope = SCOPE_MAP.get(self.request.query_params.get("scope", "competitor").lower(),
                              "competitor")
        current = models.ClusterRun.objects.filter(scope=scope, is_current=True).first()
        if not current:
            return models.TopicCluster.objects.none()
        return current.clusters.all().order_by("-size")

    @action(detail=True, methods=["get"], url_path="arguments")
    def arguments(self, request, pk=None):
        """Deduped claims assigned to this cluster, reels and articles merged.

        Article claims join through DocClusterAssignment rather than the
        argument-level clustering (which is layer-2 and reel-only for now):
        an article in the cluster contributes its claims to the cluster.
        """
        cluster = models.TopicCluster.objects.filter(id=pk).select_related("run").first()
        if not cluster:
            return Response([])
        assignments = (
            models.ArgumentAssignment.objects
            .filter(run=cluster.run, cluster_id=pk)
            .select_related("argument", "argument__reel")
        )
        # Simple dedup by normalized text (semantic dedup happens in the agent;
        # here we merge exact/near-exact repeats and count sources).
        buckets = {}
        for a in assignments:
            key = a.argument.text_it.strip().lower()[:120]
            b = buckets.setdefault(key, {"text": a.argument.text_it,
                                         "reels": set(), "articles": set()})
            b["reels"].add(a.argument.reel.shortcode)
        doc_args = (models.DocumentArgument.objects
                    .filter(document__cluster_assignments__cluster_id=pk,
                            document__cluster_assignments__run=cluster.run)
                    .select_related("document"))
        for da in doc_args:
            key = da.text_it.strip().lower()[:120]
            b = buckets.setdefault(key, {"text": da.text_it,
                                         "reels": set(), "articles": set()})
            b["articles"].add(da.document.title[:60] or da.document.source_url)
        out = [
            {"text": v["text"], "reel_count": len(v["reels"]),
             "reels": sorted(v["reels"]),
             "article_count": len(v["articles"]), "articles": sorted(v["articles"])}
            for v in buckets.values()
        ]
        out.sort(key=lambda x: x["reel_count"] + x["article_count"], reverse=True)
        return Response(out)

    @action(detail=True, methods=["post"], url_path="blog")
    def blog(self, request, pk=None):
        """Cluster-driven blog: expand the cluster's existing article, or draft
        a new one grounded in its reels. Runs as a detached background job."""
        cluster = models.TopicCluster.objects.filter(id=pk).first()
        if not cluster:
            return Response({"detail": "Cluster non trovato."}, status=404)
        job = models.Job.objects.create(
            kind="blog", status="queued", params={"cluster_id": int(pk)},
            message=f"In coda: blog per «{cluster.label_it}»")
        _spawn_job(job.id)
        return Response(serializers.JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class BlogDraftViewSet(viewsets.ModelViewSet):
    """Browse / save / dismiss the cluster-driven blog drafts + expansions."""

    serializer_class = serializers.BlogDraftSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        qs = models.BlogDraft.objects.all()
        status_f = self.request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        else:
            qs = qs.exclude(status="dismissed")
        return qs


# ── Stats ──────────────────────────────────────────────────────────────────────

class StatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        def scope_block(owner):
            reels = models.Reel.objects.filter(is_active=True, account__owner_type=owner)
            run = models.ClusterRun.objects.filter(scope=owner, is_current=True).first()
            return {
                "accounts": models.TrackedAccount.objects.filter(
                    is_active=True, owner_type=owner).count(),
                "reels": reels.count(),
                "transcribed": reels.filter(transcribe_status=models.DONE).count(),
                "enriched": reels.filter(enrich_status=models.DONE).count(),
                "clusters": run.n_clusters if run else 0,
                "last_cluster_run": run.created_at if run else None,
            }
        return Response({
            "competitor": scope_block("competitor"),
            "medyca": scope_block("owned"),
            "knowledge_docs": models.KnowledgeDocument.objects.filter(is_active=True).count(),
            "favorites": models.ReelAnnotation.objects.filter(is_favorite=True).count(),
            "inspiration": models.ReelAnnotation.objects.filter(is_inspiration=True).count(),
            "content_ideas": models.ContentIdea.objects.exclude(status="dismissed").count(),
        })


# ── Analytics — the visible "numbers" layer (per scope) ────────────────────────

class AnalyticsView(APIView):
    """One endpoint, several metrics (?metric=&scope=). Mirrors SPI's
    per-metric analytics but ORM-based. Everything data-driven + weighted."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from core import analytics
        scope = request.query_params.get("scope", "medyca")
        metric = request.query_params.get("metric", "overview")
        fn = {
            "overview": lambda: analytics.overview(scope),
            "engagement-over-time": lambda: analytics.engagement_over_time(scope),
            "top-content": lambda: analytics.top_content(scope),
            "cluster-performance": lambda: analytics.cluster_performance(scope),
            "benchmark": lambda: analytics.benchmark(),
        }.get(metric)
        if not fn:
            return Response({"detail": f"unknown metric '{metric}'"}, status=400)
        return Response(fn())


# ── Knowledge bank / second brain (MEDYC-10, MEDYC-13) ─────────────────────────

class KnowledgeDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse blog articles — Medyca's own and, on request, the competitors'."""

    permission_classes = [IsAuthenticated]
    ordering_fields = ["published_at", "created_at", "title"]
    ordering = ["-published_at"]
    search_fields = ["title", "content_text", "summary_it"]

    def get_queryset(self):
        qs = (models.KnowledgeDocument.objects
              .filter(is_active=True).select_related("source"))
        # Detail by id stays unrestricted, like ClusterViewSet does.
        if self.action == "retrieve":
            return qs
        # The browse list hides what the model itself judged non-editorial
        # (cookie walls, install pages, recipes): a card that summarises a
        # cookie banner is noise dressed as an article. The rows stay in the
        # DB and reachable by id — the verdict is reviewable, not a delete.
        qs = qs.filter(is_on_topic=True)
        # A cluster filter implies its own scope — the cluster was built from
        # one side's material, so the owner filter would only fight it.
        cluster = self.request.query_params.get("cluster")
        if cluster and str(cluster).isdigit():
            qs = qs.filter(cluster_assignments__cluster_id=int(cluster),
                           cluster_assignments__run__is_current=True)
        else:
            # Explicit scope. The default is Medyca's own material: this
            # endpoint existed before competitor blogs did, and its callers
            # assume it.
            owner = SCOPE_MAP.get(
                (self.request.query_params.get("scope") or "medyca").lower(), "owned")
            qs = qs.filter(owner_type=owner)
        source = self.request.query_params.get("source")
        if source and str(source).isdigit():
            qs = qs.filter(source_id=int(source))
        tag = self.request.query_params.get("tag")
        if tag and str(tag).isdigit():
            qs = qs.filter(tags__id=int(tag))
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(title__icontains=search)
                           | Q(summary_it__icontains=search)
                           | Q(content_text__icontains=search))
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return serializers.KnowledgeDocDetailSerializer
        return serializers.KnowledgeDocListSerializer


class KnowledgeSearchView(APIView):
    """Semantic retrieval over the knowledge bank (blog + owned reels).

    The endpoint agents call to ground copy/articles in Medyca's own material.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        query = (request.data.get("query") or request.data.get("q") or "").strip()
        if not query:
            return Response({"detail": "query richiesta."}, status=400)
        # Clamped: an unbounded top_k here would load and score the whole
        # corpus into one response on request.
        try:
            top_k = max(1, min(int(request.data.get("top_k", 6)), 24))
        except (TypeError, ValueError):
            top_k = 6
        # scope was accepted nowhere and silently defaulted to "all", so a
        # caller asking for Medyca's own material got the competitors too.
        scope = (request.data.get("scope") or "all").lower()
        if scope not in ("all", "medyca", "competitor"):
            scope = "all"
        from core.knowledge import semantic_search
        return Response({"query": query, "scope": scope,
                         "results": semantic_search(query, top_k=top_k, scope=scope)})

    def get(self, request):
        request._full_data = {"query": request.query_params.get("q", ""),
                              "top_k": request.query_params.get("top_k", 6),
                              "scope": request.query_params.get("scope", "all")}
        return self.post(request)


class KnowledgeAskView(APIView):
    """RAG over the knowledge bank: retrieve + grounded Italian answer with
    citations. The "second brain" Q&A / agent task interface."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        query = (request.data.get("query") or request.data.get("q") or "").strip()
        if not query:
            return Response({"detail": "query richiesta."}, status=400)
        top_k = max(3, min(int(request.data.get("top_k", 8)), 12))
        scope = (request.data.get("scope") or "all").lower()
        if scope not in ("all", "medyca", "competitor"):
            scope = "all"
        history = request.data.get("history") or []
        if not isinstance(history, list):
            history = []
        # Pages the user pasted into this conversation. Read once, used for
        # this answer only, never added to the knowledge bank.
        from core.knowledge import MAX_REFERENCES
        refs = request.data.get("references") or []
        if isinstance(refs, str):
            refs = [refs]
        refs = [str(u).strip() for u in refs if str(u).strip()][:MAX_REFERENCES]
        ctype = (request.data.get("content_type") or "all").lower()
        if ctype not in ("all", "reel", "article"):
            ctype = "all"
        from core.knowledge import answer
        return Response(answer(query, top_k=top_k, scope=scope, history=history,
                               references=refs, content_type=ctype))


class ContentIdeaViewSet(viewsets.ModelViewSet):
    """The content-ideation Second Brain: browse / save / dismiss ideas, and
    generate a fresh batch from competitor coverage vs Medyca's own."""

    serializer_class = serializers.ContentIdeaSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        qs = models.ContentIdea.objects.all()
        status_f = self.request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        else:
            qs = qs.exclude(status="dismissed")
        return qs

    @action(detail=False, methods=["post"], url_path="plan")
    def plan(self, request):
        """Build an editorial plan: n contents ready to film, each grounded."""
        n = max(3, min(int(request.data.get("n", 6)), 12))
        theme = (request.data.get("theme") or "").strip()[:200]
        running = _existing_job("editorial", {"theme": theme})
        if running:
            return Response(serializers.JobSerializer(running).data,
                            status=status.HTTP_202_ACCEPTED)
        job = models.Job.objects.create(
            kind="editorial", status="queued", params={"n": n, "theme": theme},
            message=f"In coda: piano editoriale{' su ' + theme if theme else ''}")
        _spawn_job(job.id)
        return Response(serializers.JobSerializer(job).data,
                        status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """Kick off idea generation as a detached background job (returns 202)."""
        n = int(request.data.get("n", 8))
        running = _existing_job("ideation", {})
        if running:
            return Response(serializers.JobSerializer(running).data,
                            status=status.HTTP_202_ACCEPTED)
        job = models.Job.objects.create(kind="ideation", status="queued",
                                        params={"n": n}, message="In coda…")
        _spawn_job(job.id)
        return Response(serializers.JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


ACTIVE = ("queued", "running")
STALE_AFTER = 25 * 60  # a job with no progress for 25 min is dead, not slow


def _reap_stale_jobs():
    """Fail jobs whose worker died, so the UI never shows a bar that can no
    longer move. A worker killed by a signal (a backend restart kills the whole
    cgroup) never gets to write its own failure, so someone has to."""
    from django.utils import timezone
    cutoff = timezone.now() - timezone.timedelta(seconds=STALE_AFTER)
    models.Job.objects.filter(status__in=ACTIVE, updated_at__lt=cutoff).update(
        status="failed",
        message="Interrotto: nessun avanzamento",
        error="il processo è morto senza segnalare l'errore (riavvio o kill)",
        finished_at=timezone.now(),
    )


def _existing_job(kind: str, params: dict):
    """Return an already-running identical job, if any.

    Local inference fits one generation at a time, so launching the same
    analysis twice makes both slower and neither finishes sooner.
    """
    _reap_stale_jobs()
    for job in models.Job.objects.filter(kind=kind, status__in=ACTIVE):
        if all(job.params.get(k) == v for k, v in params.items()):
            return job
    return None


def _spawn_job(job_id: int):
    """Spawn `manage.py run_job --job <id>` as a detached process (survives the
    request and gunicorn worker recycling). Mirrors the scraper's run_spider."""
    import subprocess
    import sys

    from django.conf import settings

    # Never DEVNULL: a job that dies leaves no trace, and every incident
    # becomes unfalsifiable. One file per job, kept next to the other logs.
    log_dir = Path(settings.BASE_DIR) / "logs" / "jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / f"job-{job_id}.log", "ab", buffering=0)
    subprocess.Popen(
        [sys.executable, "manage.py", "run_job", "--job", str(job_id)],
        cwd=str(settings.BASE_DIR),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


class StrategyBriefViewSet(viewsets.ModelViewSet):
    """The input-driven strategy engine: analyze an input into a brief, list/
    save/dismiss briefs, and generate a full draft on-demand."""

    serializer_class = serializers.StrategyBriefSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        qs = models.StrategyBrief.objects.all()
        status_f = self.request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        else:
            qs = qs.exclude(status="dismissed")
        return qs

    @action(detail=False, methods=["post"], url_path="analyze")
    def analyze(self, request):
        """Kick a strategy analysis (free-text input or a theme) as a job."""
        text = (request.data.get("input_text") or request.data.get("text") or "").strip()
        if len(text) < 3:
            return Response({"detail": "Inserisci un tema o una richiesta."}, status=400)
        params = {"input_text": text[:400],
                  "source_kind": request.data.get("source_kind", "input")}
        # Embed here, where the model stays warm across requests (~0.2s),
        # instead of in the job process where it would be a cold 14s load.
        try:
            from core.knowledge import _embed_query
            params["qv"] = _embed_query(text[:400]).tolist()
        except Exception:  # noqa: BLE001 — job falls back to embedding itself
            logger.warning("[strategy] query embedding failed; job will embed")
        running = _existing_job("strategy", {"input_text": params["input_text"]})
        if running:
            return Response(serializers.JobSerializer(running).data,
                            status=status.HTTP_202_ACCEPTED)
        job = models.Job.objects.create(
            kind="strategy", status="queued", params=params,
            message=f"In coda: analisi «{text[:40]}»")
        _spawn_job(job.id)
        return Response(serializers.JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="draft")
    def draft(self, request, pk=None):
        """Generate the full draft for this brief (on-demand) as a job."""
        running = _existing_job("strategy_draft", {"brief_id": int(pk)})
        if running:
            return Response(serializers.JobSerializer(running).data,
                            status=status.HTTP_202_ACCEPTED)
        job = models.Job.objects.create(
            kind="strategy_draft", status="queued", params={"brief_id": int(pk)},
            message="In coda: bozza completa")
        _spawn_job(job.id)
        return Response(serializers.JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class PipelineStatusView(APIView):
    """Operational view of the pipeline: how far each stage has got.

    Built for watching a long backlog drain — the counts are the same ones
    the agents work from, so the page cannot disagree with reality.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Max

        reels = models.Reel.objects.all()
        total = reels.count()

        SCOPES = (("owned", "Medyca"), ("competitor", "Competitor"))

        def stage(field):
            # Grouped once by owner as well as by state: a single percentage
            # hides the one thing the client asks about first. "30% scaricati"
            # reads as broken, when in fact every Medyca reel is done and the
            # remainder is competitor backlog draining against Instagram's
            # quota. One query, not one per scope: this endpoint is polled
            # every five seconds.
            rows = reels.values("account__owner_type", field).annotate(n=Count("id"))
            counts: dict[str, int] = {}
            per_scope: dict[str, dict[str, int]] = {}
            for r in rows:
                state, n = r[field], r["n"]
                counts[state] = counts.get(state, 0) + n
                bucket = per_scope.setdefault(r["account__owner_type"], {})
                bucket[state] = bucket.get(state, 0) + n

            def _done(c: dict[str, int]) -> int:
                return c.get("done", 0) + c.get("skipped", 0)

            done = _done(counts)
            scopes = []
            for owner, label in SCOPES:
                c = per_scope.get(owner)
                if not c:
                    continue
                n = sum(c.values())
                d = _done(c)
                scopes.append({"scope": owner, "label": label, "done": d,
                               "total": n, "pct": round(100 * d / n) if n else 0})
            return {
                "done": done,
                "pending": counts.get("pending", 0),
                "failed": counts.get("failed", 0),
                "total": total,
                "pct": round(100 * done / total) if total else 0,
                "scopes": scopes,
            }

        stages = [
            {"key": "download", "label": "Download video", **stage("media_status")},
            {"key": "transcribe", "label": "Trascrizione", **stage("transcribe_status")},
            {"key": "enrich", "label": "Analisi LLM", **stage("enrich_status")},
            {"key": "arguments", "label": "Affermazioni", **stage("argument_status")},
        ]
        # How much of the queue can skip the throttled API call: the single
        # number that says whether the download bottleneck is dissolving.
        pending = reels.filter(media_status="pending")
        stages.append({
            "key": "cached_urls", "label": "URL video in cache",
            "done": pending.exclude(video_url="").count(),
            "pending": pending.filter(video_url="").count(),
            "failed": 0, "total": pending.count(),
            "pct": round(100 * pending.exclude(video_url="").count() / pending.count())
                   if pending.count() else 100,
        })

        embedded = models.ReelEmbedding.objects.count()
        stages.append({"key": "embed", "label": "Embedding", "done": embedded,
                       "pending": max(0, total - embedded), "failed": 0,
                       "total": total, "pct": round(100 * embedded / total) if total else 0})

        jobs = [
            {"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress,
             "message": j.message[:120]}
            for j in models.Job.objects.filter(status__in=("queued", "running")).order_by("-id")[:10]
        ]

        accounts = [
            {"username": a.username, "owner_type": a.owner_type, "reels": a.n,
             "last_scraped_at": a.last_scraped_at}
            for a in models.TrackedAccount.objects.annotate(n=Count("reels")).order_by("-n")
        ]

        last = {
            "reel_scraped": reels.aggregate(m=Max("scraped_at"))["m"],
            "enrichment": models.Enrichment.objects.aggregate(m=Max("created_at"))["m"],
            "cluster_run": models.ClusterRun.objects.aggregate(m=Max("created_at"))["m"],
        }

        from core import ops, queue_eta
        from scraper import apify_budget

        return Response({
            "operations": ops.snapshot(),
            # What collection has cost this cycle. On a $5 plan this is not a
            # detail: the page that starts a run must show what a run spends.
            # Cached 5 minutes inside apify_budget — this endpoint is polled
            # every 5 seconds per open tab.
            "budget": apify_budget.spend(),
            # How much is left and how long it should take — the question a
            # percentage cannot answer. See core/queue_eta.py.
            "queue": queue_eta.snapshot(),
            "totals": {
                "reels": total,
                "active": reels.filter(is_active=True).count(),
                "excluded": reels.filter(is_active=False).count(),
                "arguments": models.ReelArgument.objects.count(),
                "documents": models.KnowledgeDocument.objects.count(),
                "clusters": models.TopicCluster.objects.filter(run__is_current=True).count(),
            },
            "stages": stages,
            "jobs": jobs,
            "accounts": accounts,
            "last": last,
        })


class PipelineRunView(APIView):
    """Start the pipeline by hand, from the interface.

    Until now the pipeline only ever ran from cron, which meant that adding an
    account or a blog source and then wanting to see the result involved
    waiting for the night. This queues a `Job` of kind "pipeline"; `run_job`
    executes it detached and the status page follows it.

    **Only one run at a time, and the check is deliberately wider than this
    table.** A second concurrent run is not just wasted work: the downloader
    paces itself against Instagram's quota, and two runs double the request
    rate against the limit that is already the bottleneck. So the guard looks
    both at the job rows *and* at the process table — the nightly cron run
    leaves no row in the database, and it is exactly the run most likely to be
    in progress when someone presses the button.

    POST body (both optional):
      only:  ["download", "transcribe", …] — a subset of the stages
      limit: cap rows processed per agent

    Returns 202 with the job, or 409 when something is already running.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from pipeline.dag import STAGE_NAMES

        raw_only = request.data.get("only") or []
        if isinstance(raw_only, str):
            raw_only = [s.strip() for s in raw_only.split(",") if s.strip()]
        only = [s for s in raw_only if s in STAGE_NAMES]
        if raw_only and not only:
            return Response(
                {"detail": f"Passaggi non riconosciuti. Ammessi: {', '.join(STAGE_NAMES)}."},
                status=400)

        limit = request.data.get("limit")
        try:
            limit = int(limit) if limit not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "Il limite deve essere un numero."}, status=400)
        if limit is not None and limit < 1:
            return Response({"detail": "Il limite deve essere almeno 1."}, status=400)

        running = _existing_job("pipeline", {})
        if running:
            return Response(
                {"detail": "L'aggiornamento è già in corso.",
                 "job_id": running.id, "already_running": True},
                status=status.HTTP_409_CONFLICT)

        from core import ops
        if any(a["job"] == "run_pipeline" for a in ops.activity()):
            return Response(
                {"detail": "L'aggiornamento automatico è già in corso in questo "
                           "momento. Riprova quando è finito.",
                 "already_running": True},
                status=status.HTTP_409_CONFLICT)

        job = models.Job.objects.create(
            kind="pipeline",
            params={"only": only, "limit": limit},
            message="In coda: aggiornamento dei contenuti",
        )
        _spawn_job(job.id)
        return Response(
            {"job_id": job.id, "status": job.status, "only": only, "limit": limit},
            status=status.HTTP_202_ACCEPTED)


class CoverageMapView(APIView):
    """Coverage map: Medyca themes (covered) vs competitor themes Medyca hasn't
    addressed (opportunities). Match Medyca vs competitor cluster centroids by
    cosine; unmatched competitor clusters = gaps."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        import numpy as np
        med_run = models.ClusterRun.objects.filter(scope="owned", is_current=True).first()
        comp_run = models.ClusterRun.objects.filter(scope="competitor", is_current=True).first()
        med = list(med_run.clusters.all()) if med_run else []
        comp = list(comp_run.clusters.all()) if comp_run else []

        def vec(c):
            return np.asarray(c.centroid, dtype=np.float32) if c.centroid else None

        med_vecs = [(c, vec(c)) for c in med if c.centroid]
        covered = [{"id": c.id, "label": c.label_it, "reels": c.reel_assignments.count(),
                    "docs": c.doc_assignments.count()} for c in med]
        opportunities = []
        for c in comp:
            cv = vec(c)
            if cv is None:
                continue
            best = max((float(np.dot(cv, mv)) for _, mv in med_vecs if mv is not None), default=0.0)
            if best < 0.8:  # competitors talk about it, Medyca doesn't (much)
                opportunities.append({"id": c.id, "label": c.label_it,
                                      "reels": c.reel_assignments.count(),
                                      "similarity": round(best, 2)})
        # Client-supplied custom topics: owned content -> covered, competitor
        # signal only (or nothing yet) -> opportunity. Marked custom for the UI.
        for topic in models.CustomTopic.objects.filter(is_active=True):
            own_reels = topic.matches.filter(scope="owned", reel__isnull=False).count()
            own_docs = topic.matches.filter(document__isnull=False).count()
            comp = topic.matches.filter(scope="competitor").count()
            if own_reels + own_docs > 0:
                covered.append({"id": f"ct{topic.id}", "label": topic.label,
                                "reels": own_reels, "docs": own_docs, "custom": True})
            else:
                opportunities.append({"id": f"ct{topic.id}", "label": topic.label,
                                      "reels": comp, "similarity": 0.0, "custom": True})

        opportunities.sort(key=lambda x: x["reels"], reverse=True)
        return Response({"covered": covered, "opportunities": opportunities})


class SecondBrainGraphView(APIView):
    """The second brain as three worlds, not one tangle.

    Medyca on one side, the competitors on the other, and between them the
    opportunities — themes the competition covers and Medyca does not. Edges
    run competitor -> opportunity -> Medyca, which is the direction the client
    reads the map in: what is out there, and what it means for me.

    Every node carries its owner and a link to the source, so any dot can be
    followed back to the reel or article it came from.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        import numpy as np

        nodes, edges = [], []
        seen = set()

        def add(nid, group, label, sub="", parent="", owner="", detail="", url=""):
            if nid in seen:
                return
            seen.add(nid)
            nodes.append({"id": nid, "group": group, "label": label[:60], "sub": sub,
                          "parent": parent, "owner": owner, "detail": detail, "url": url})

        def link(a, b, rel="", kind="structure"):
            edges.append({"source": a, "target": b, "rel": rel, "kind": kind})

        # ── the three anchors ────────────────────────────────────────────
        add("root:medyca", "hub", "Medyca", "i tuoi contenuti", owner="owned")
        add("root:competitor", "hub", "Competitor", "il mercato", owner="competitor")
        add("root:opportunity", "hub", "Opportunità", "da coprire", owner="opportunity")

        def add_world(scope, root_id):
            run = models.ClusterRun.objects.filter(scope=scope, is_current=True).first()
            if not run:
                return []
            clusters = list(run.clusters.all().order_by("-size"))
            for c in clusters:
                cid = f"{scope}:cluster:{c.id}"
                add(cid, "theme", c.label_it, f"{c.reel_assignments.count()} reel",
                    parent=root_id, owner=scope, detail=c.description_it or "")
                link(root_id, cid, "", "structure")
                for r in (models.Reel.objects
                          .filter(cluster_assignments__cluster=c, is_active=True)
                          .select_related("account", "enrichment")
                          .order_by("-view_count")[:5]):
                    enr = getattr(r, "enrichment", None)
                    rid = f"reel:{r.shortcode}"
                    add(rid, "reel",
                        (enr.primary_topic if enr else "") or (r.caption or r.shortcode)[:38],
                        f"{r.view_count or 0} view · @{r.account.username}",
                        parent=cid, owner=r.account.owner_type,
                        detail=(enr.summary_it if enr else "") or "",
                        url=f"https://www.instagram.com/reel/{r.shortcode}/")
                    link(cid, rid, "", "structure")
                for a in (models.DocClusterAssignment.objects.filter(cluster=c)
                          .select_related("document", "document__source")[:3]):
                    d = a.document
                    site = d.source.name if d.source else ""
                    add(f"doc:{d.id}", "blog", d.title.replace(" — Medyca", ""),
                        f"articolo blog{' · ' + site if site else ''}",
                        parent=cid, owner=d.owner_type,
                        detail=d.summary_it or "", url=d.source_url)
                    link(cid, f"doc:{d.id}", "", "structure")
            return clusters

        med_clusters = add_world("owned", "root:medyca")
        comp_clusters = add_world("competitor", "root:competitor")

        # ── opportunities: what the competition covers and Medyca does not ──
        med_vecs = [np.asarray(c.centroid, dtype=np.float32)
                    for c in med_clusters if c.centroid]
        for c in comp_clusters:
            if not c.centroid:
                continue
            cv = np.asarray(c.centroid, dtype=np.float32)
            best = max((float(np.dot(cv, mv)) for mv in med_vecs), default=0.0)
            if best >= 0.8:
                continue
            oid = f"opp:{c.id}"
            add(oid, "opportunity", c.label_it,
                f"{c.reel_assignments.count()} reel competitor",
                parent="root:opportunity", owner="opportunity")
            link("root:opportunity", oid, "", "structure")
            # the flow the client reads: seen out there -> a gap -> something
            # Medyca could make
            link(f"competitor:cluster:{c.id}", oid, "scoperto", "flow")
            link(oid, "root:medyca", "da coprire", "flow")

        # client-supplied themes hang off Medyca: they are the client's own lens
        for topic in models.CustomTopic.objects.filter(is_active=True):
            tid = f"custom:{topic.id}"
            own = topic.matches.filter(scope="owned").count()
            comp = topic.matches.filter(scope="competitor").count()
            add(tid, "custom", topic.label,
                f"{own} Medyca · {comp} competitor · tema del cliente",
                parent="root:medyca", owner="owned")
            link("root:medyca", tid, "tema tuo", "flow")

        return Response({"nodes": nodes, "edges": edges})


class CustomTopicViewSet(viewsets.ModelViewSet):
    """Client-supplied themes to map ("tiroide", "osteoporosi", "Bijuva"…).

    Creation embeds the label+keywords and computes matches synchronously so
    the client sees immediately how much content exists on the theme. The
    nightly cluster step refreshes matches for new content.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.CustomTopicSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return models.CustomTopic.objects.filter(is_active=True).annotate(
            medyca_matches=Count("matches", filter=Q(matches__scope="owned", matches__reel__isnull=False)),
            competitor_matches=Count("matches", filter=Q(matches__scope="competitor")),
            # Scoped: now that competitor blogs exist, an unscoped doc count
            # would silently mix them into what reads as Medyca's blog column.
            doc_matches=Count("matches", filter=Q(matches__document__isnull=False,
                                                  matches__scope="owned")),
            competitor_doc_matches=Count("matches", filter=Q(
                matches__document__isnull=False, matches__scope="competitor")),
        )

    def perform_create(self, serializer):
        from core import custom_topics
        topic = serializer.save()
        custom_topics.embed_topic(topic)
        custom_topics.recompute_matches([topic])

    @action(detail=True, methods=["get"])
    def matches(self, request, pk=None):
        """Matched assets for one topic, filtered by ?scope=."""
        topic = self.get_object()
        scope = SCOPE_MAP.get(request.query_params.get("scope", "medyca").lower(), "owned")
        qs = (topic.matches.filter(scope=scope)
              .select_related("reel__account", "reel__enrichment", "document"))
        # Verbatim mentions first (strongest evidence), then by similarity.
        ordered = sorted(qs, key=lambda m: (m.via == "semantic", -m.similarity))
        reels, docs = [], []
        for m in ordered:
            if m.reel:
                data = serializers.ReelListSerializer(m.reel).data
                data["similarity"] = m.similarity
                data["via"] = m.via
                reels.append(data)
            elif m.document:
                d = m.document
                docs.append({"id": d.id, "title": d.title, "url": d.source_url,
                             "summary_it": d.summary_it, "similarity": m.similarity,
                             "via": m.via})
        return Response({"reels": reels, "docs": docs})


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    """Poll background job status (for the global status bar)."""

    serializer_class = serializers.JobSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = models.Job.objects.all()
        if self.request.query_params.get("active"):
            # The UI polls this every few seconds; it is the only place that
            # reliably runs, so it is where ghosts get cleaned up.
            _reap_stale_jobs()
            qs = qs.filter(status__in=["queued", "running"])
        elif self.action == "list":
            # recent jobs only (avoid unbounded list); retrieve stays unfiltered
            recent_ids = list(qs.values_list("id", flat=True)[:20])
            qs = qs.filter(id__in=recent_ids)
        return qs
