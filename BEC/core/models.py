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
# Handed to the Batch API and waiting for the answer. A real state, not a
# flavour of pending: without it the next nightly run would resubmit the same
# items and we would pay twice for the same analysis.
BATCHED = "batched"
STATUS_CHOICES = [
    (PENDING, "pending"),
    (DONE, "done"),
    (FAILED, "failed"),
    (SKIPPED, "skipped"),
    (BATCHED, "batched"),
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
    # What the analysis could actually be based on. Guards the UI against
    # presenting a caption-derived guess as if it described the video.
    EVIDENCE_CHOICES = [
        ("transcript", "transcript"),
        ("caption_only", "caption_only"),
        ("insufficient", "insufficient"),
    ]
    evidence = models.CharField(max_length=16, choices=EVIDENCE_CHOICES,
                                default="transcript")
    # The one specific subject of this reel, never an umbrella term. Every
    # video mentions "menopausa" and "ormoni bioidentici", so those labels
    # separate nothing: what distinguishes a reel is vampate vs tiroide vs
    # osteoporosi.
    primary_topic = models.CharField(max_length=80, blank=True, default="")
    is_on_topic = models.BooleanField(default=True)
    off_topic_reason = models.CharField(max_length=300, blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "enrichments"

    def __str__(self):
        return f"enrichment:{self.reel.shortcode}"


class ReelEmbedding(models.Model):
    reel = models.OneToOneField(Reel, on_delete=models.CASCADE, related_name="embedding")
    vector = models.JSONField(default=list)  # list[float]
    # One vector per passage of the text, in the order core.knowledge._chunks
    # produces them. The chat picks the passage that answers the question
    # rather than the head of the document, and re-encoding those passages on
    # every question cost 15-18s per query — the whole of its latency. The
    # text is not stored again: chunking is deterministic from the source.
    chunk_vectors = models.JSONField(default=list, blank=True)  # list[list[float]]
    model_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # Bumps on every re-embed, unlike created_at. The chat's index cache keys
    # on this: a re-embed that reuses rows (update_or_create) leaves the count
    # and created_at unchanged, so without it the chat served a stale index
    # until the process restarted.
    updated_at = models.DateTimeField(auto_now=True)

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
    # Verbatim span from the transcript that supports this claim. Empty means
    # the claim was not grounded and should not have been stored.
    quote = models.TextField(blank=True, default="")
    embedding = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reel_arguments"

    def __str__(self):
        return self.text_it[:60]


class DocumentArgument(models.Model):
    """A standalone claim extracted from a blog article.

    The parallel table to ReelArgument — the polymorphism pattern this
    codebase already chose (see DocClusterAssignment) — with the same
    grounding rule: `quote` is a verbatim span of the article's text, and a
    claim that cannot be quoted is not stored.
    """

    document = models.ForeignKey("KnowledgeDocument", on_delete=models.CASCADE,
                                 related_name="arguments")
    text_it = models.TextField()
    quote = models.TextField(blank=True, default="")
    embedding = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "document_arguments"

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

    Lets a cluster span reels AND blog articles together, in both scopes:
    Medyca's own second brain, and the competitors' map since blogs became
    a tracked competitor surface too.
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
    llm_model = models.CharField(max_length=64, blank=True, default="")
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
    # True when generated from the LLM primary_topic rather than typed by
    # hand. Lets the auto-tagger refresh its own tags without touching the
    # client's manual ones, and the UI show where a tag came from.
    auto = models.BooleanField(default=False)

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


class BlogSource(models.Model):
    """A blog we crawl for articles — what TrackedAccount is for Instagram.

    Deliberately NOT a generalisation of TrackedAccount: that model is
    Instagram-native (unique username, ig_user_id, followers). The shared
    thing is only the role — a tracked origin with an owner_type.

    `discovery` holds what the crawler LEARNED about this site: which sitemap
    or feed to use, and which URL shapes are articles. The LLM classification
    that fills it is paid once per site; every later crawl reads the cache
    and costs nothing.
    """

    OWNER_CHOICES = [("competitor", "competitor"), ("owned", "owned")]
    STRATEGY_CHOICES = [("unknown", "unknown"), ("sitemap", "sitemap"),
                        ("feed", "feed"), ("index", "index"), ("mixed", "mixed")]

    name = models.CharField(max_length=120)
    site_url = models.URLField(max_length=300, blank=True, default="")
    index_url = models.URLField(max_length=500, unique=True)
    owner_type = models.CharField(max_length=16, choices=OWNER_CHOICES,
                                  default="competitor")
    language = models.CharField(max_length=8, blank=True, default="")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    # Cadence lives on the row, not in the crontab: our own blog matters
    # daily, a third-party site should not see us more than weekly.
    crawl_interval_h = models.IntegerField(default=168)

    strategy = models.CharField(max_length=16, choices=STRATEGY_CHOICES,
                                default="unknown")
    discovery = models.JSONField(default=dict, blank=True)
    crawl_state = models.JSONField(default=dict, blank=True)

    # Real columns, not JSON: auto-deactivation queries them and the UI
    # shows them next to the source.
    consecutive_failures = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "blog_sources"
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "owner_type"])]

    def __str__(self):
        return f"{self.name} ({self.owner_type})"


class KnowledgeDocument(models.Model):
    """A text document in the Medyca knowledge bank — e.g. a blog article
    from medyca.it, fetched and stored as Markdown, then enriched + embedded.

    Together with the OWNED reels (owner_type='owned'), these documents form
    the knowledge bank the "second brain" and downstream agents draw on.
    """

    SOURCE_CHOICES = [("blog", "Blog"), ("manual", "Manual"),
                      ("video", "Video"), ("other", "Other")]

    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="blog")
    # Provenance. SET_NULL: deleting a source must never destroy the bank.
    source = models.ForeignKey(BlogSource, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="documents")
    # THE rule: whoever needs to know whose a document is reads THIS field,
    # never source.owner_type. Denormalised on purpose — the hot paths iterate
    # every doc, and "source is null => owned" is a silent invariant that
    # breaks the first time a competitor source is deleted with SET_NULL. The
    # way it breaks is competitor text entering Medyca's own-material prompts,
    # the worst failure this product can make. Only blog_agent.ingest() and
    # the seed migration write it.
    owner_type = models.CharField(max_length=16, db_index=True,
                                  choices=[("competitor", "competitor"),
                                           ("owned", "owned")],
                                  default="owned")
    language = models.CharField(max_length=8, blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    source_url = models.URLField(max_length=500, unique=True)
    title = models.CharField(max_length=300, blank=True, default="")
    content_md = models.TextField(blank=True, default="")       # readable article as Markdown
    content_text = models.TextField(blank=True, default="")     # plain text for search/embeddings
    author = models.CharField(max_length=200, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)

    # Enrichment (LLM) + embedding, mirroring the reel pipeline
    summary_it = models.TextField(blank=True, default="")
    topics = models.JSONField(default=list, blank=True)
    # Same rule as Enrichment.primary_topic: the one specific subject, never
    # an umbrella term — "menopausa" separates nothing in this corpus.
    primary_topic = models.CharField(max_length=80, blank=True, default="")
    is_on_topic = models.BooleanField(default=True)
    off_topic_reason = models.CharField(max_length=300, blank=True, default="")
    # Reference material the client added on purpose — a TV episode, a talk.
    # Deliberately NOT a third owner_type: 26 call sites read that field as a
    # binary and ten of them would silently file a third value under Medyca,
    # including the enrichment prompt that says "il blog di Medyca stessa".
    # It also exempts the row from the on-topic filter: a model's verdict must
    # not delete from the client's library something a human put there.
    is_inspiration = models.BooleanField(default=False, db_index=True)
    embedding = models.JSONField(default=list, blank=True)
    # See ReelEmbedding.chunk_vectors — same purpose, for blog articles.
    chunk_vectors = models.JSONField(default=list, blank=True)
    embedding_model = models.CharField(max_length=128, blank=True, default="")

    enrich_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    embed_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    argument_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    last_error = models.TextField(blank=True, default="")

    # Tags apply to articles and uploaded interviews too, not just reels —
    # a direct M2M rather than an annotation twin, since a document has no
    # favourite/note the way a reel does.
    tags = models.ManyToManyField(Tag, blank=True, related_name="documents")

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
    hook_it = models.CharField(max_length=400, blank=True, default="")  # opening line
    # The shot list: what to say, in order, from the hook to the closing line.
    # Without it an "idea" still leaves the whole video to invent.
    outline = models.JSONField(default=list, blank=True)   # [{"step": "...", "note": "..."}]
    cta_it = models.CharField(max_length=300, blank=True, default="")
    content_format = models.CharField(max_length=32, blank=True, default="")
    scope = models.CharField(max_length=16, default="owned")  # owned | competitor
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
        ("editorial", "editorial"),
        ("blogsource_discover", "Blog source discovery"),
        ("upload_transcribe", "Upload transcribe"),
        ("link_transcribe", "Link transcribe"),
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
    # Which model wrote this, so the reader can weigh the output accordingly.
    brief_model = models.CharField(max_length=64, blank=True, default="")
    draft_model = models.CharField(max_length=64, blank=True, default="")
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


class CustomTopic(models.Model):
    """A client-supplied theme to map content against (e.g. "tiroide",
    "osteoporosi", "andropausa", "Bijuva"). Unlike auto-discovered
    TopicClusters these persist across cluster runs; matches are recomputed
    on creation and refreshed at every nightly cluster step."""

    label = models.CharField(max_length=120, unique=True)
    keywords = models.JSONField(default=list, blank=True)
    embedding = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "custom_topics"
        ordering = ["label"]

    def __str__(self):
        return self.label


class CustomTopicMatch(models.Model):
    """An asset (reel or blog doc) semantically matched to a CustomTopic."""

    topic = models.ForeignKey(CustomTopic, on_delete=models.CASCADE, related_name="matches")
    reel = models.ForeignKey(
        Reel, on_delete=models.CASCADE, null=True, blank=True,
        related_name="custom_topic_matches")
    document = models.ForeignKey(
        "KnowledgeDocument", on_delete=models.CASCADE, null=True, blank=True,
        related_name="custom_topic_matches")
    scope = models.CharField(max_length=16, default="competitor")  # owned|competitor
    similarity = models.FloatField(default=0.0)
    # How the asset matched: semantic (embedding), keyword (verbatim mention),
    # or both. Verbatim mentions matter for drug/brand names (e.g. "Bijuva").
    via = models.CharField(max_length=16, default="semantic")

    class Meta:
        db_table = "custom_topic_matches"
        indexes = [models.Index(fields=["topic", "scope"])]


def _upload_path(instance, filename):
    """Where an uploaded interview file lands under MEDIA_ROOT."""
    import uuid as _uuid
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"uploads/{_uuid.uuid4().hex}.{ext}"


class UploadedMedia(models.Model):
    """Media the client brought in himself — by FILE or by LINK.

    The fourth way content enters the knowledge bank, after Instagram reels
    and crawled blogs: the client sends an audio or video file (or pastes a
    video link), it is transcribed, and the transcript becomes a
    KnowledgeDocument (source_type='manual'/'video') that flows through the
    SAME enrichment/embedding/clustering pipeline, plus a blog draft.

    Two independent things are recorded about each item, because they answer
    different questions and conflating them would be wrong:

    * `owner_type` — WHOSE content it is. Decides whether it counts as
      Medyca's own coverage in the gap engine. Same two values as everywhere
      else; there is deliberately no third value (see KnowledgeDocument).
    * `is_inspiration` — WHY it is here: reference material the client added
      on purpose, to draw from. A competitor's episode can be inspiration; so
      can one of his own TV appearances. Neither implies the other.

    Status is tracked on the row the way Reel tracks media/transcribe: the
    item processes asynchronously (a Job), and the UI polls this.
    """

    KIND_CHOICES = [("audio", "Audio"), ("video", "Video")]

    # Empty for a link-sourced item: there is no uploaded file to store.
    file = models.FileField(upload_to=_upload_path, blank=True)
    # The public page the video came from (YouTube, …). Empty for a file
    # upload. This is what makes the reference clickable downstream.
    source_url = models.URLField(max_length=500, blank=True, default="")
    # Who published it — "YouTVRS" — straight from the provider's oEmbed.
    channel = models.CharField(max_length=200, blank=True, default="")
    owner_type = models.CharField(max_length=16,
                                  choices=[("owned", "owned"),
                                           ("competitor", "competitor")],
                                  default="owned")
    is_inspiration = models.BooleanField(default=False)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default="audio")
    original_name = models.CharField(max_length=300, blank=True, default="")
    title = models.CharField(max_length=300, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    duration_s = models.FloatField(null=True, blank=True)
    # mp3 (16kHz mono) derived from the upload, MEDIA_ROOT-relative — the
    # video itself is discarded once the audio is extracted.
    audio_file = models.CharField(max_length=500, blank=True, default="")

    transcribe_status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                                         default=PENDING)
    # The results, once ready.
    document = models.ForeignKey("KnowledgeDocument", null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="uploads")
    blog_draft = models.ForeignKey("BlogDraft", null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="uploads")
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "uploaded_media"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.original_name or f"upload {self.pk}"


class BatchRun(models.Model):
    """One delivery to the Batch API — the receipt we come back with.

    The Batch API answers within 24h, not within seconds, so the work splits
    into "submit" and "collect" across two nightly runs. This row is what
    connects them: which provider batch is open, what went into it, and what
    came back. Without it a restarted process would lose the batch id and the
    money spent on it.

    Results come back in ANY order and are matched by custom_id
    ("reel-1251", "doc-42", "docarg-42"), never by position — matching by
    position would file one item's analysis under a different item.
    """

    # One entry per kind of batchable work — mirrors batch_agent.KINDS.
    KIND_CHOICES = [
        ("reel_enrich", "analisi di un reel"),
        ("doc_enrich", "analisi di un articolo"),
        ("doc_arguments", "affermazioni di un articolo"),
    ]
    STATUS_CHOICES = [
        ("submitted", "submitted"),   # handed over, still working
        ("ended", "ended"),           # provider finished, results ready
        ("collected", "collected"),   # we have written the results down
        ("failed", "failed"),
        ("canceled", "canceled"),
    ]

    kind = models.CharField(max_length=20, choices=KIND_CHOICES,
                            default="reel_enrich")
    batch_id = models.CharField(max_length=120, unique=True)
    model = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="submitted")
    # The custom_ids we sent, so a collect knows what it is owed even if the
    # rows changed in the meantime.
    items = models.JSONField(default=list, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(auto_now_add=True)
    collected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "batch_runs"
        ordering = ["-submitted_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.kind} {self.batch_id} ({self.status})"

