"""FastAPI authentication dependencies.

``get_current_user`` extracts the Bearer token, verifies it with the
``CognitoVerifier``, and returns the authenticated principal. The verifier is
resolved through ``app.state`` so tests can inject one with a local JWKS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.cognito import AuthError, CognitoVerifier

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated principal derived from a verified Cognito token."""

    sub: str
    claims: dict[str, Any]


def get_verifier(request: Request) -> CognitoVerifier:
    """Return the CognitoVerifier stored on the app, creating a default one."""
    verifier = getattr(request.app.state, "cognito_verifier", None)
    if verifier is None:
        verifier = CognitoVerifier()
        request.app.state.cognito_verifier = verifier
    return verifier


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """Validate the Bearer token and return the current user, else 401."""
    from fastapi import HTTPException, status

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    verifier = get_verifier(request)
    try:
        claims = verifier.verify_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return CurrentUser(sub=str(claims["sub"]), claims=claims)
