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

        Fails closed: if the deployment is not fully configured (both the user
        pool id and the app client id must be set) the token is rejected rather
        than accepted on signature alone. Returns the decoded claims (including
        ``sub``) on success.
        """
        try:
            headers = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise AuthError("Malformed token header") from exc

        kid = headers.get("kid")
        if not kid:
            raise AuthError("Token missing key id")

        settings = self._settings

        # Fail closed on a half-configured deployment. Without BOTH the issuer
        # (derived from the user pool id) and the app client id we cannot bind a
        # token to this issuer and this application, so verifying only the
        # signature would accept any token signed by *some* Cognito pool. Refuse
        # rather than silently skip the audience / issuer checks.
        if not settings.cognito_fully_configured:
            raise AuthError(
                "Cognito is not fully configured; refusing to verify tokens. "
                "COGNITO_USER_POOL_ID and COGNITO_APP_CLIENT_ID must both be set."
            )

        key = self._find_key(kid)
        token_use_expected = settings.COGNITO_TOKEN_USE

        # Access tokens carry client_id (not aud); id tokens carry aud. The
        # issuer is always verified (guaranteed non-empty by the guard above).
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "issuer": settings.COGNITO_ISSUER,
        }
        if token_use_expected == "id":
            # id tokens bind the app client id in the standard ``aud`` claim.
            decode_kwargs["audience"] = settings.COGNITO_APP_CLIENT_ID
        else:
            # Access tokens carry the app client in ``client_id`` (not ``aud``),
            # which python-jose cannot check; skip aud here and enforce the
            # client_id claim explicitly below.
            decode_kwargs["options"] = {"verify_aud": False}

        try:
            claims = jwt.decode(token, key, **decode_kwargs)
        except JWTError as exc:
            raise AuthError("Token verification failed") from exc

        token_use = claims.get("token_use")
        if token_use_expected and token_use != token_use_expected:
            raise AuthError(f"Unexpected token_use '{token_use}'")

        if token_use_expected == "access":
            if claims.get("client_id") != settings.COGNITO_APP_CLIENT_ID:
                raise AuthError("Token client_id does not match app client")

        if not claims.get("sub"):
            raise AuthError("Token missing subject")

        return claims
