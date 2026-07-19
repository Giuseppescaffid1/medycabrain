from django.contrib import admin

from . import models


@admin.register(models.TrackedAccount)
class TrackedAccountAdmin(admin.ModelAdmin):
    list_display = ("username", "display_name", "is_active", "followers_count", "last_scraped_at")
    list_filter = ("is_active",)
    search_fields = ("username", "display_name")


@admin.register(models.Reel)
class ReelAdmin(admin.ModelAdmin):
    list_display = (
        "shortcode", "account", "posted_at", "view_count",
        "media_status", "transcribe_status", "enrich_status", "argument_status",
    )
    list_filter = ("media_status", "transcribe_status", "enrich_status", "argument_status", "account")
    search_fields = ("shortcode", "caption")
    raw_id_fields = ("account",)


@admin.register(models.ScraperConfig)
class ScraperConfigAdmin(admin.ModelAdmin):
    """Edit doc_ids, delays, page caps here — doc_id rotation fixed without deploy."""

    list_display = ("key", "value", "updated_at")


@admin.register(models.ClusterRun)
class ClusterRunAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "algorithm", "n_reels", "n_clusters", "n_noise", "status", "is_current")
    list_filter = ("status", "is_current")


@admin.register(models.KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "source_type", "enrich_status", "embed_status", "published_at")
    list_filter = ("source_type", "enrich_status", "embed_status")
    search_fields = ("title", "source_url", "content_text")


@admin.register(models.ContentIdea)
class ContentIdeaAdmin(admin.ModelAdmin):
    list_display = ("argument_it", "is_gap", "status", "batch", "created_at")
    list_filter = ("status", "is_gap")
    search_fields = ("argument_it", "rationale_it")


admin.site.register(models.Transcript)
admin.site.register(models.Enrichment)
admin.site.register(models.TopicCluster)
admin.site.register(models.ReelArgument)
admin.site.register(models.Tag)
admin.site.register(models.ReelAnnotation)
admin.site.site_header = "medycabrain admin"
admin.site.site_title = "medycabrain"
