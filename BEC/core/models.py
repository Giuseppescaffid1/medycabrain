"""
core/models.py
==============
All tables for the medycabrain POC live in this single app (single owner,
Django-managed migrations — no scraper/Django schema split like SPI).

Status columns (media/transcribe/enrich/argument) drive the idempotent
pipeline: each agent selects rows in its `pending` state, processes them,
and marks them `done` / `failed` / `skipped`.
"""

from django.db import models

# Status choices shared by the pipeline stage columns
PENDING = "pending"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"
STATUS_CHOICES = [
    (PENDING, "pending"),
    (DONE, "done"),
    (FAILED, "failed"),
    (SKIPPED, "skipped"),
]

CONTENT_FORMATS = [
    ("talking_head", "Talking head"),
    ("voiceover", "Voiceover"),
    ("tutorial", "Tutorial"),
    ("testimonianza", "Testimonianza"),
    ("text_overlay", "Text overlay"),
    ("intervista", "Intervista"),
    ("altro", "Altro"),
]


class TrackedAccount(models.Model):
    """A public Instagram account we scrape reels from."""

    username = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=255, blank=True, default="")
    ig_user_id = models.CharField(max_length=32, blank=True, default="")
    profile_pic_url = models.TextField(blank=True, default="")
    bio = models.TextField(blank=True, default="")
    followers_count = models.IntegerField(null=True, blank=True)
    # 'competitor' feeds the inspiration library; 'owned' (e.g. @medyca.menopausa)
    # feeds the Medyca knowledge bank / second brain.
    owner_type = models.CharField(
        max_length=16,
        choices=[("competitor", "competitor"), ("owned", "owned")],
        default="competitor",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    # scrape_state: {"end_cursor": str, "consecutive_failures": int,
    #                "last_error": str, "provider": str}
    scrape_state = models.JSONField(default=dict, blank=True)
    last_scraped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tracked_accounts"
        ordering = ["username"]

    def __str__(self):
        return f"@{self.username}"


class Reel(models.Model):
    """A single reel scraped from a tracked account."""

    account = models.ForeignKey(
        TrackedAccount, on_delete=models.CASCADE, related_name="reels"
    )
    shortcode = models.CharField(max_length=32, unique=True)
    ig_media_id = models.CharField(max_length=64, blank=True, default="")
    caption = models.TextField(blank=True, default="")
    posted_at = models.DateTimeField(null=True, blank=True)
    duration_s = models.FloatField(null=True, blank=True)
    view_count = models.IntegerField(null=True, blank=True)
    like_count = models.IntegerField(null=True, blank=True)
    comment_count = models.IntegerField(null=True, blank=True)

    # Media: video_url is an ephemeral CDN link (expires in hours/days);
    # audio_file / thumbnail_file are media-root-relative paths we keep.
    video_url = models.TextField(blank=True, default="")
    thumbnail_url = models.TextField(blank=True, default="")
    thumbnail_file = models.CharField(max_length=255, blank=True, default="")
    audio_file = models.CharField(max_length=255, blank=True, default="")
    audio_info = models.JSONField(default=dict, blank=True)  # {title, artist}
    raw_json_path = models.CharField(max_length=255, blank=True, default="")

    # Idempotent pipeline stage tracking
    media_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    transcribe_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    enrich_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    argument_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    media_attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    is_active = models.BooleanField(default=True)
    scraped_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reels"
        ordering = ["-posted_at"]
        indexes = [
            models.Index(fields=["media_status"]),
            models.Index(fields=["transcribe_status"]),
            models.Index(fields=["enrich_status"]),
            models.Index(fields=["argument_status"]),
            models.Index(fields=["-posted_at"]),
        ]

    def __str__(self):
        return f"{self.account.username}/{self.shortcode}"


class Transcript(models.Model):
    reel = models.OneToOneField(Reel, on_delete=models.CASCADE, related_name="transcript")
    text = models.TextField(blank=True, default="")
    language = models.CharField(max_length=8, blank=True, default="it")
    segments = models.JSONField(default=list, blank=True)  # [{start, end, text}]
    model_name = models.CharField(max_length=64, blank=True, default="")
    audio_duration_s = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "transcripts"

    def __str__(self):
        return f"transcript:{self.reel.shortcode}"


class Enrichment(models.Model):
    reel = models.OneToOneField(Reel, on_delete=models.CASCADE, related_name="enrichment")
    summary_it = models.TextField(blank=True, default="")
    topics = models.JSONField(default=list, blank=True)  # list[str]
    hook_text = models.TextField(blank=True, default="")
    hook_analysis_it = models.TextField(blank=True, default="")
    target_audience_it = models.TextField(blank=True, default="")
    content_format = models.CharField(
        max_length=32, choices=CONTENT_FORMATS, blank=True, default=""
    )
    llm_model = models.CharField(max_length=64, blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "enrichments"

    def __str__(self):
        return f"enrichment:{self.reel.shortcode}"


class ReelEmbedding(models.Model):
    reel = models.OneToOneField(Reel, on_delete=models.CASCADE, related_name="embedding")
    vector = models.JSONField(default=list)  # list[float]
    model_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reel_embeddings"


class ClusterRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    # Clustering is scoped: 'competitor' reels and 'owned' (Medyca) reels are
    # clustered separately, each with its own current run.
    scope = models.CharField(
        max_length=16,
        choices=[("competitor", "competitor"), ("owned", "owned")],
        default="competitor",
    )
    algorithm = models.CharField(max_length=32, blank=True, default="")
    params = models.JSONField(default=dict, blank=True)
    n_reels = models.IntegerField(default=0)
    n_clusters = models.IntegerField(default=0)
    n_noise = models.IntegerField(default=0)
    status = models.CharField(max_length=16, default="running")  # running|done|failed
    is_current = models.BooleanField(default=False)  # one current per scope

    class Meta:
        db_table = "cluster_runs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["scope", "is_current"])]

    def __str__(self):
        return f"run#{self.pk} [{self.scope}] ({self.status})"


class TopicCluster(models.Model):
    run = models.ForeignKey(ClusterRun, on_delete=models.CASCADE, related_name="clusters")
    label_it = models.CharField(max_length=120, blank=True, default="")
    description_it = models.TextField(blank=True, default="")
    size = models.IntegerField(default=0)
    keywords = models.JSONField(default=list, blank=True)
    centroid = models.JSONField(default=list, blank=True)  # for cross-run label matching
    position = models.IntegerField(default=0)

    class Meta:
        db_table = "topic_clusters"
        ordering = ["-size"]

    def __str__(self):
        return self.label_it or f"cluster#{self.pk}"


class ReelClusterAssignment(models.Model):
    run = models.ForeignKey(ClusterRun, on_delete=models.CASCADE, related_name="reel_assignments")
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name="cluster_assignments")
    cluster = models.ForeignKey(
        TopicCluster, on_delete=models.CASCADE, null=True, blank=True, related_name="reel_assignments"
    )
    probability = models.FloatField(default=0.0)

    class Meta:
        db_table = "reel_cluster_assignments"
        unique_together = [("run", "reel")]


class ReelArgument(models.Model):
    """A standalone claim extracted from a reel (layer-2, stable across runs)."""

    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name="arguments")
    text_it = models.TextField()
    embedding = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reel_arguments"

    def __str__(self):
        return self.text_it[:60]


class ArgumentAssignment(models.Model):
    run = models.ForeignKey(ClusterRun, on_delete=models.CASCADE, related_name="argument_assignments")
    argument = models.ForeignKey(ReelArgument, on_delete=models.CASCADE, related_name="assignments")
    cluster = models.ForeignKey(
        TopicCluster, on_delete=models.CASCADE, null=True, blank=True, related_name="argument_assignments"
    )
    similarity = models.FloatField(default=0.0)

    class Meta:
        db_table = "argument_assignments"
        unique_together = [("run", "argument")]


class DocClusterAssignment(models.Model):
    """A blog KnowledgeDocument's membership in a topic cluster.

    Lets the Second Brain cluster span ALL Medyca assets — reels AND blog
    articles together (Alberto's model: the second brain is the thematic
    layer over every asset). Only meaningful for the 'owned' scope.
    """

    run = models.ForeignKey(ClusterRun, on_delete=models.CASCADE, related_name="doc_assignments")
    document = models.ForeignKey("KnowledgeDocument", on_delete=models.CASCADE, related_name="cluster_assignments")
    cluster = models.ForeignKey(
        TopicCluster, on_delete=models.CASCADE, null=True, blank=True, related_name="doc_assignments"
    )
    probability = models.FloatField(default=0.0)

    class Meta:
        db_table = "doc_cluster_assignments"
        unique_together = [("run", "document")]


class BlogDraft(models.Model):
    """Output of the cluster-driven blog workflow (Alberto's headline).

    For a theme cluster: 'expand' lists what the reels cover that the
    existing blog article doesn't yet; 'draft' is a full new article
    grounded ONLY in the cluster's reel transcripts (not invented).
    """

    MODE_CHOICES = [("expand", "Expand existing"), ("draft", "New draft")]
    STATUS_CHOICES = [("proposed", "Proposed"), ("saved", "Saved"), ("dismissed", "Dismissed")]

    mode = models.CharField(max_length=12, choices=MODE_CHOICES)
    cluster_label = models.CharField(max_length=160, blank=True, default="")
    title = models.CharField(max_length=300, blank=True, default="")
    content_md = models.TextField(blank=True, default="")
    source_refs = models.JSONField(default=list, blank=True)  # [{kind,title,url}]
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="proposed")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blog_drafts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.mode}: {self.title or self.cluster_label}"


# ── Workspace (single shared client user → no per-user FK) ─────────────────────

class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=7, blank=True, default="#6366f1")

    class Meta:
        db_table = "tags"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ReelAnnotation(models.Model):
    reel = models.OneToOneField(Reel, on_delete=models.CASCADE, related_name="annotation")
    is_favorite = models.BooleanField(default=False)
    is_inspiration = models.BooleanField(default=False)
    note = models.TextField(blank=True, default="")
    tags = models.ManyToManyField(Tag, blank=True, related_name="annotations")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reel_annotations"

    def __str__(self):
        return f"annotation:{self.reel.shortcode}"


class KnowledgeDocument(models.Model):
    """A text document in the Medyca knowledge bank — e.g. a blog article
    from medyca.it, fetched and stored as Markdown, then enriched + embedded.

    Together with the OWNED reels (owner_type='owned'), these documents form
    the knowledge bank the "second brain" and downstream agents draw on.
    """

    SOURCE_CHOICES = [("blog", "Blog"), ("manual", "Manual"), ("other", "Other")]

    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="blog")
    source_url = models.URLField(max_length=500, unique=True)
    title = models.CharField(max_length=300, blank=True, default="")
    content_md = models.TextField(blank=True, default="")       # readable article as Markdown
    content_text = models.TextField(blank=True, default="")     # plain text for search/embeddings
    author = models.CharField(max_length=200, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)

    # Enrichment (LLM) + embedding, mirroring the reel pipeline
    summary_it = models.TextField(blank=True, default="")
    topics = models.JSONField(default=list, blank=True)
    embedding = models.JSONField(default=list, blank=True)
    embedding_model = models.CharField(max_length=128, blank=True, default="")

    enrich_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    embed_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    last_error = models.TextField(blank=True, default="")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_documents"
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["enrich_status"]),
            models.Index(fields=["embed_status"]),
        ]

    def __str__(self):
        return self.title or self.source_url


class ContentIdea(models.Model):
    """A content angle the second brain proposes for Medyca to produce.

    Derived from what competitors cover (competitor clusters + arguments)
    vs what Medyca already covers (owned reels + blog). `is_gap` marks
    arguments competitors push that Medyca hasn't addressed.
    """

    STATUS_CHOICES = [
        ("proposed", "Proposed"),
        ("saved", "Saved"),
        ("dismissed", "Dismissed"),
    ]

    argument_it = models.CharField(max_length=300)   # the content argument/topic
    rationale_it = models.TextField(blank=True, default="")  # why it's worth doing
    angle_it = models.TextField(blank=True, default="")      # concrete content angle
    is_gap = models.BooleanField(default=False)              # competitors cover, Medyca doesn't
    source_refs = models.JSONField(default=list, blank=True)  # [{kind,title,url}]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="proposed")
    batch = models.CharField(max_length=40, blank=True, default="")  # generation batch id
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "content_ideas"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return self.argument_it[:60]


class Job(models.Model):
    """A background job run by a detached management command (`run_job`).

    Lets slow work (LLM idea generation) run outside the HTTP request/timeout
    while the UI polls status and a global status bar shows progress.
    """

    KIND_CHOICES = [
        ("ideation", "Ideation"), ("pipeline", "Pipeline"), ("blog", "Blog"),
        ("strategy", "Strategy"), ("strategy_draft", "Strategy draft"),
    ]
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="queued")
    progress = models.IntegerField(default=0)  # 0–100
    message = models.CharField(max_length=300, blank=True, default="")
    params = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "jobs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.kind} #{self.pk} ({self.status})"

    def set_progress(self, progress: int, message: str = ""):
        self.progress = max(0, min(100, int(progress)))
        if message:
            self.message = message[:300]
        self.save(update_fields=["progress", "message", "updated_at"])


class StrategyBrief(models.Model):
    """Output of the input-driven strategy engine.

    Given an input (a free-text topic/brief, or a clicked theme), the engine
    analyzes the knowledge bank + competitor signal, weighted by engagement,
    and produces a strategic brief: what Medyca already covers, the gap vs
    competitors, and a grounded proposal. A full draft can be generated
    on-demand from the same sources.
    """

    COVERAGE_CHOICES = [("covered", "Covered"), ("partial", "Partial"), ("gap", "Gap")]
    STATUS_CHOICES = [("proposed", "Proposed"), ("saved", "Saved"), ("dismissed", "Dismissed")]

    input_text = models.CharField(max_length=400)
    source_kind = models.CharField(max_length=16, default="input")  # input | theme
    coverage = models.CharField(max_length=12, choices=COVERAGE_CHOICES, default="gap")
    brief_md = models.TextField(blank=True, default="")
    draft_md = models.TextField(blank=True, default="")   # filled on-demand
    medyca_sources = models.JSONField(default=list, blank=True)      # [{title,url,weight}]
    competitor_sources = models.JSONField(default=list, blank=True)  # [{title,url}]
    metrics = models.JSONField(default=dict, blank=True)   # engagement numbers used
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="proposed")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "strategy_briefs"
        ordering = ["-created_at"]

    def __str__(self):
        return self.input_text[:60]


class ScraperConfig(models.Model):
    """Key/value runtime config editable in Django admin (doc_ids, delays…)."""

    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "scraper_config"

    def __str__(self):
        return self.key

    @classmethod
    def get(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default
