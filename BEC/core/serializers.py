from django.contrib.auth.models import User
from rest_framework import serializers

from . import models


class TagSerializer(serializers.ModelSerializer):
    usage = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = models.Tag
        fields = ["id", "name", "color", "auto", "usage"]


class AnnotationSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = models.ReelAnnotation
        fields = ["is_favorite", "is_inspiration", "note", "tags", "updated_at"]


class BlogSourceSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = models.BlogSource
        fields = [
            "id", "name", "index_url", "site_url", "owner_type", "language",
            "is_active", "notes", "crawl_interval_h", "strategy",
            "last_crawled_at", "consecutive_failures", "last_error",
            "document_count", "created_at",
        ]
        read_only_fields = [
            "site_url", "strategy", "language", "last_crawled_at",
            "consecutive_failures", "last_error", "created_at",
        ]

    def validate_index_url(self, value):
        """The URL a crawler will visit on a schedule: only public http(s).

        Reuses the chat's SSRF chain — its refusal messages are already
        user-facing Italian.
        """
        from urllib.parse import urlparse

        from core.external_ref import RefusedURL, _check_public

        value = (value or "").strip().rstrip("/")
        if urlparse(value).scheme not in ("http", "https"):
            raise serializers.ValidationError("Sono ammessi solo indirizzi http e https.")
        try:
            _check_public(value)
        except RefusedURL as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def create(self, validated_data):
        from urllib.parse import urlparse

        u = urlparse(validated_data["index_url"])
        validated_data.setdefault("site_url", f"{u.scheme}://{u.netloc}")
        return super().create(validated_data)


class AccountSerializer(serializers.ModelSerializer):
    reel_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = models.TrackedAccount
        fields = [
            "id", "username", "display_name", "ig_user_id", "profile_pic_url",
            "bio", "followers_count", "owner_type", "is_active", "notes",
            "last_scraped_at", "reel_count", "created_at",
        ]
        read_only_fields = [
            "ig_user_id", "profile_pic_url", "bio", "followers_count",
            "last_scraped_at", "created_at", "display_name",
        ]


class TranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Transcript
        fields = ["text", "language", "segments", "audio_duration_s", "model_name"]


class EnrichmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Enrichment
        fields = [
            "summary_it", "topics", "hook_text", "hook_analysis_it",
            "target_audience_it", "content_format", "llm_model",
            "evidence", "is_on_topic", "off_topic_reason",
        
            "primary_topic",
        ]


class ReelListSerializer(serializers.ModelSerializer):
    account_username = serializers.CharField(source="account.username", read_only=True)
    summary_it = serializers.CharField(source="enrichment.summary_it", read_only=True, default="")
    content_format = serializers.CharField(source="enrichment.content_format", read_only=True, default="")
    evidence = serializers.CharField(source="enrichment.evidence", read_only=True, default="")
    primary_topic = serializers.CharField(source="enrichment.primary_topic", read_only=True, default="")
    is_on_topic = serializers.BooleanField(source="enrichment.is_on_topic", read_only=True, default=True)
    is_favorite = serializers.BooleanField(source="annotation.is_favorite", read_only=True, default=False)
    is_inspiration = serializers.BooleanField(source="annotation.is_inspiration", read_only=True, default=False)
    cluster_label = serializers.SerializerMethodField()

    class Meta:
        model = models.Reel
        fields = [
            "id", "shortcode", "account_username", "caption", "posted_at",
            "duration_s", "view_count", "like_count", "comment_count",
            "thumbnail_file", "thumbnail_url", "summary_it", "content_format",
            "is_favorite", "is_inspiration", "cluster_label",
            "transcribe_status", "enrich_status",
            "evidence", "is_on_topic", "is_active",
        
            "primary_topic",
        ]

    def get_cluster_label(self, obj):
        current = self.context.get("current_assignments")
        if current is not None:
            return current.get(obj.id)
        return None


class ReelDetailSerializer(serializers.ModelSerializer):
    account = AccountSerializer(read_only=True)
    transcript = TranscriptSerializer(read_only=True)
    enrichment = EnrichmentSerializer(read_only=True)
    annotation = AnnotationSerializer(read_only=True)
    arguments = serializers.SerializerMethodField()
    instagram_url = serializers.SerializerMethodField()

    class Meta:
        model = models.Reel
        fields = [
            "id", "shortcode", "account", "caption", "posted_at", "duration_s",
            "view_count", "like_count", "comment_count", "thumbnail_file",
            "thumbnail_url", "audio_file", "audio_info", "instagram_url",
            "transcript", "enrichment", "annotation", "arguments",
            "media_status", "transcribe_status", "enrich_status", "argument_status",
        ]

    def get_arguments(self, obj):
        # Each claim ships with the verbatim span that supports it, so the
        # client can check it instead of trusting it.
        return [{"text": a.text_it, "quote": a.quote} for a in obj.arguments.all()]

    def get_instagram_url(self, obj):
        return f"https://www.instagram.com/reel/{obj.shortcode}/"


class ClusterSerializer(serializers.ModelSerializer):
    preview_thumbs = serializers.SerializerMethodField()
    has_blog = serializers.SerializerMethodField()
    reel_count = serializers.SerializerMethodField()
    doc_count = serializers.SerializerMethodField()

    class Meta:
        model = models.TopicCluster
        fields = ["id", "label_it", "description_it", "size", "keywords", "position",
                  "preview_thumbs", "has_blog", "reel_count", "doc_count"]

    def get_preview_thumbs(self, obj):
        thumbs = (
            models.Reel.objects.filter(cluster_assignments__cluster=obj)
            .exclude(thumbnail_file="")
            .values_list("thumbnail_file", flat=True)[:3]
        )
        return list(thumbs)

    def get_has_blog(self, obj):
        return obj.doc_assignments.filter(document__isnull=False).exists()

    def get_reel_count(self, obj):
        return obj.reel_assignments.count()

    def get_doc_count(self, obj):
        return obj.doc_assignments.count()


class BlogDraftSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.BlogDraft
        fields = ["id", "mode", "cluster_label", "title", "content_md",
                  "source_refs", "status", "created_at"
            "llm_model",
        ]
        read_only_fields = ["mode", "cluster_label", "title", "content_md",
                            "source_refs", "created_at"]


class StrategyBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.StrategyBrief
        fields = ["id", "input_text", "source_kind", "coverage", "brief_md",
                  "draft_md", "medyca_sources", "competitor_sources", "metrics",
                  "status", "created_at", "brief_model", "draft_model"]
        read_only_fields = ["input_text", "source_kind", "coverage", "brief_md",
                            "draft_md", "medyca_sources", "competitor_sources",
                            "metrics", "created_at"]


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username"]


class _DocSourceField(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    owner_type = serializers.CharField()


class KnowledgeDocListSerializer(serializers.ModelSerializer):
    source = _DocSourceField(read_only=True, allow_null=True)

    class Meta:
        model = models.KnowledgeDocument
        fields = [
            "id", "source_type", "source_url", "title", "author",
            "published_at", "summary_it", "topics", "primary_topic",
            "owner_type", "language", "source", "enrich_status", "created_at",
        ]


class DocumentArgumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DocumentArgument
        fields = ["id", "text_it", "quote"]


class KnowledgeDocDetailSerializer(serializers.ModelSerializer):
    source = _DocSourceField(read_only=True, allow_null=True)
    arguments = DocumentArgumentSerializer(many=True, read_only=True)

    class Meta:
        model = models.KnowledgeDocument
        fields = [
            "id", "source_type", "source_url", "title", "author", "published_at",
            "summary_it", "topics", "primary_topic", "owner_type", "language",
            "source", "content_md", "arguments", "enrich_status", "embed_status",
            "created_at", "updated_at",
        ]


class UploadedMediaSerializer(serializers.ModelSerializer):
    document = serializers.PrimaryKeyRelatedField(read_only=True)
    blog_draft = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = models.UploadedMedia
        fields = ["id", "kind", "original_name", "title", "size_bytes",
                  "duration_s", "transcribe_status", "document",
                  "blog_draft", "last_error", "created_at",
                  # Link-sourced items: the reference itself.
                  "source_url", "channel", "owner_type", "is_inspiration"]
        read_only_fields = ["kind", "size_bytes", "duration_s",
                            "transcribe_status", "document", "blog_draft",
                            "last_error", "created_at", "source_url", "channel"]


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Job
        fields = [
            "id", "kind", "status", "progress", "message", "result",
            "error", "created_at", "updated_at", "finished_at",
        ]


class ContentIdeaSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ContentIdea
        fields = [
            "id", "argument_it", "rationale_it", "angle_it", "is_gap",
            "source_refs", "status", "batch", "created_at",
            "hook_it", "content_format", "scope", "outline", "cta_it",
        ]
        read_only_fields = [
            "argument_it", "rationale_it", "angle_it", "is_gap",
            "source_refs", "batch", "created_at",
        ]


class CustomTopicSerializer(serializers.ModelSerializer):
    medyca_matches = serializers.IntegerField(read_only=True, required=False)
    competitor_matches = serializers.IntegerField(read_only=True, required=False)
    doc_matches = serializers.IntegerField(read_only=True, required=False)
    competitor_doc_matches = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = models.CustomTopic
        fields = ["id", "label", "keywords", "is_active", "created_at",
                  "medyca_matches", "competitor_matches", "doc_matches",
                  "competitor_doc_matches"]
        read_only_fields = ["created_at"]
