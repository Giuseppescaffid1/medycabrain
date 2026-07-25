"""
config/settings/base.py
=======================
Shared settings for the medycabrain BEC (Instagram Content Intelligence POC).
Environment-specific overrides live in production.py.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Security ───────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ── Installed apps ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    # Local
    "core",
]

# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # must be first
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ── Database ───────────────────────────────────────────────────────────────────
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    _ssl = os.environ.get("DB_SSL_REQUIRE", "false").lower() == "true"
    DATABASES = {"default": dj_database_url.config(conn_max_age=600, ssl_require=_ssl)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "medycabrain"),
            "USER": os.environ.get("DB_USER", "medycabrain_user"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }

# ── Django REST Framework ──────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "config.authentication.SafeTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
    },
}

# ── CORS ───────────────────────────────────────────────────────────────────────
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()]

# ── Internationalisation ───────────────────────────────────────────────────────
LANGUAGE_CODE = "it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

# ── Static / Media ─────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Project-specific paths ─────────────────────────────────────────────────────
DATA_DIR = BASE_DIR / "data"
IG_SESSION_FILE = os.environ.get("IG_SESSION_FILE", str(DATA_DIR / "ig_session.json"))
RAW_DUMP_DIR = DATA_DIR / "raw"
TMP_DIR = DATA_DIR / "tmp"

# ── LLM / Whisper / embeddings ─────────────────────────────────────────────────
HF_API_TOKEN = os.environ.get("HF_API_TOKEN", "")
HF_LLM_MODEL = os.environ.get("HF_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
# Local-first: Ollama runs a quantized Qwen2.5-7B (zero cost, good Italian).
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
# Provider order: try each until one answers. Default local-only; HF is
# dormant (add ",hf" to call it — e.g. after refilling credits).
# Fast remote provider (OpenAI-compatible): Groq / Cerebras / OpenRouter /
# DeepSeek / Together. ~100-300 tok/s vs ~1-3 tok/s for a 7B on this CPU, so
# it is tried FIRST whenever a key is present. Ollama stays as the offline
# backstop. Set FAST_LLM_API_KEY in .env to activate.
FAST_LLM_API_KEY = os.environ.get("FAST_LLM_API_KEY", "")
FAST_LLM_BASE_URL = os.environ.get("FAST_LLM_BASE_URL", "https://api.groq.com/openai/v1")
FAST_LLM_MODEL = os.environ.get("FAST_LLM_MODEL", "llama-3.3-70b-versatile")

# Serialize local Ollama calls: the CPU fits exactly one 3B/7B generation.
# Concurrent calls (nightly pipeline + a client clicking "Analizza") make
# BOTH time out, which is how the box melted down.
OLLAMA_LOCK_PATH = os.environ.get("OLLAMA_LOCK_PATH", "/tmp/medycabrain-ollama.lock")
OLLAMA_LOCK_WAIT = int(os.environ.get("OLLAMA_LOCK_WAIT", "900"))

LLM_PROVIDER_ORDER = os.environ.get("LLM_PROVIDER_ORDER", "fast,ollama").split(",")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "4"))
EMBEDDINGS_MODEL = os.environ.get(
    "EMBEDDINGS_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

# ── Logging ────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
