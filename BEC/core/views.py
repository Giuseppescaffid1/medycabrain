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


# ── Reels ──────────────────────────────────────────────────────────────────────

class ReelViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filterset_class = ReelFilter
    ordering_fields = ["posted_at", "view_count", "like_count", "comment_count"]
    ordering = ["-posted_at"]

    def get_queryset(self):
        qs = (
            models.Reel.objects.filter(is_active=True)
            .select_related("account", "enrichment", "annotation")
        )
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
    queryset = models.Tag.objects.all()
    serializer_class = serializers.TagSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


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
        """Deduped arguments assigned to this cluster with source-reel counts."""
        cluster = models.TopicCluster.objects.filter(id=pk).select_related("run").first()
        if not cluster:
            return Response([])
        assignments = (
            models.ArgumentAssignment.objects
            .filter(run=cluster.run, cluster_id=pk)
            .select_related("argument", "argument__reel")
        )
        # Simple dedup by normalized text (semantic dedup happens in the agent;
        # here we merge exact/near-exact repeats and count source reels).
        buckets = {}
        for a in assignments:
            key = a.argument.text_it.strip().lower()[:120]
            b = buckets.setdefault(key, {"text": a.argument.text_it, "reels": set()})
            b["reels"].add(a.argument.reel.shortcode)
        out = [
            {"text": v["text"], "reel_count": len(v["reels"]), "reels": sorted(v["reels"])}
            for v in buckets.values()
        ]
        out.sort(key=lambda x: x["reel_count"], reverse=True)
        return Response(out)


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


# ── Knowledge bank / second brain (MEDYC-10, MEDYC-13) ─────────────────────────

class KnowledgeDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse the blog documents in the Medyca knowledge bank."""

    permission_classes = [IsAuthenticated]
    ordering_fields = ["published_at", "created_at", "title"]
    ordering = ["-published_at"]
    search_fields = ["title", "content_text", "summary_it"]

    def get_queryset(self):
        return models.KnowledgeDocument.objects.filter(is_active=True)

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
        top_k = int(request.data.get("top_k", 6))
        from core.knowledge import semantic_search
        return Response({"query": query, "results": semantic_search(query, top_k=top_k)})

    def get(self, request):
        request._full_data = {"query": request.query_params.get("q", ""),
                              "top_k": request.query_params.get("top_k", 6)}
        return self.post(request)


class KnowledgeAskView(APIView):
    """RAG over the knowledge bank: retrieve + grounded Italian answer with
    citations. The "second brain" Q&A / agent task interface."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        query = (request.data.get("query") or request.data.get("q") or "").strip()
        if not query:
            return Response({"detail": "query richiesta."}, status=400)
        top_k = int(request.data.get("top_k", 6))
        from core.knowledge import answer
        return Response(answer(query, top_k=top_k))


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

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        n = int(request.data.get("n", 8))
        from core.ideation import generate_ideas
        try:
            created = generate_ideas(n=n)
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=400)
        return Response(serializers.ContentIdeaSerializer(created, many=True).data)
