"""
config/settings/production.py
=============================
Production overrides. Note: TLS is terminated at nginx, so we do NOT set
SECURE_SSL_REDIRECT here (that would double-redirect behind the proxy).
"""

from .base import *  # noqa: F401,F403

DEBUG = False

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
