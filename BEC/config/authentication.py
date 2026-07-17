"""
config/authentication.py
========================
Token authentication that doesn't reject invalid tokens on public endpoints.
Mirrors the SafeTokenAuthentication pattern from spi-backend.
"""

from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class SafeTokenAuthentication(TokenAuthentication):
    """TokenAuthentication that silently ignores invalid tokens."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            return None
