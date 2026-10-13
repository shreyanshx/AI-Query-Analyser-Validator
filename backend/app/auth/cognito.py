"""Cognito JWT verification.

The JWKS source is injectable so tests can supply a locally generated RSA key
set and sign fake Cognito tokens without any live Cognito dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from cachetools import TTLCache
from jose import jwt
from jose.exceptions import JWTError

from app.config import Settings, get_settings

# Type for an injectable JWKS provider: returns the full JWKS dict.
JWKSProvider = Callable[[], dict[str, Any]]


class AuthError(Exception):
    """Raised when a token fails verification."""


class CognitoVerifier:
    """Verifies Cognito-issued JWTs against a (cached) JWKS."""

    def __init__(
        self,
        settings: Settings | None = None,
        jwks_provider: JWKSProvider | None = None,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._settings = settings or get_settings()
        self._jwks_provider = jwks_provider or self._default_jwks_provider
        self._cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=1, ttl=cache_ttl_seconds)

    @property
    def settings(self) -> Settings:
        return self._settings

    def _default_jwks_provider(self) -> dict[str, Any]:
        """Fetch the JWKS from the derived Cognito issuer URL."""
        issuer = self._settings.COGNITO_ISSUER
        if not issuer:
            raise AuthError("Cognito issuer is not configured")
        url = f"{issuer}/.well-known/jwks.json"
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()

    def _get_jwks(self) -> dict[str, Any]:
        cached = self._cache.get("jwks")
        if cached is not None:
            return cached
        jwks = self._jwks_provider()
        self._cache["jwks"] = jwks
        return jwks

    def _find_key(self, kid: str) -> dict[str, Any]:
        jwks = self._get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        # Refresh once in case of key rotation, then retry.
        self._cache.clear()
        jwks = self._get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        raise AuthError("Signing key not found for token")

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify signature, issuer, audience/client id, exp, and token_use.

        Returns the decoded claims (including ``sub``) on success.
        """
        try:
            headers = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise AuthError("Malformed token header") from exc

        kid = headers.get("kid")
        if not kid:
            raise AuthError("Token missing key id")

        key = self._find_key(kid)
        settings = self._settings
        token_use_expected = settings.COGNITO_TOKEN_USE

        # Access tokens carry client_id (not aud); id tokens carry aud.
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "issuer": settings.COGNITO_ISSUER or None,
        }
        if token_use_expected == "id" and settings.COGNITO_APP_CLIENT_ID:
            decode_kwargs["audience"] = settings.COGNITO_APP_CLIENT_ID
        else:
            # For access tokens python-jose cannot check client_id, so skip aud
            # verification here and validate client_id from claims below.
            decode_kwargs["options"] = {"verify_aud": False}

        try:
            claims = jwt.decode(token, key, **decode_kwargs)
        except JWTError as exc:
            raise AuthError("Token verification failed") from exc

        token_use = claims.get("token_use")
        if token_use_expected and token_use != token_use_expected:
            raise AuthError(f"Unexpected token_use '{token_use}'")

        if token_use_expected == "access" and settings.COGNITO_APP_CLIENT_ID:
            if claims.get("client_id") != settings.COGNITO_APP_CLIENT_ID:
                raise AuthError("Token client_id does not match app client")

        if not claims.get("sub"):
            raise AuthError("Token missing subject")

        return claims
