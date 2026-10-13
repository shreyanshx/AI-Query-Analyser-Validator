"""FastAPI application factory.

``create_app`` wires CORS, routers, and logging. ``GET /health`` is
unauthenticated (for the ALB); all other routers require a valid Cognito JWT via
the ``get_current_user`` dependency applied on the individual routes.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import connections, health, optimize, validate
from app.config import Settings, get_settings
from app.logging_utils import configure_logging, get_logger

logger = get_logger(__name__)


def _warn_on_insecure_config(settings: Settings) -> None:
    """Emit startup warnings for config that is unsafe for production.

    These are warnings (not hard failures) so local development stays
    frictionless, but they make a misconfigured production deploy obvious in
    CloudWatch. Protected routes additionally fail closed at request time when
    Cognito is not fully configured (see ``app.auth.deps.get_current_user``).
    """
    if not settings.cognito_fully_configured:
        logger.warning(
            "Cognito is not fully configured (COGNITO_USER_POOL_ID and "
            "COGNITO_APP_CLIENT_ID must both be set); protected routes will "
            "refuse requests until this is fixed."
        )
    if settings.cors_is_localhost_default:
        logger.warning(
            "CORS_ORIGINS is still the localhost development default "
            "(http://localhost:5173). Set it to the real HTTPS SPA origin in "
            "production or browser requests from the SPA will be rejected."
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    settings = settings or get_settings()
    _warn_on_insecure_config(settings)

    app = FastAPI(
        title="AI Query Analyser & Validator",
        version="0.1.0",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Unauthenticated health check for the ALB.
    app.include_router(health.router)
    # Authenticated routers (auth enforced per-route via get_current_user).
    app.include_router(connections.router)
    app.include_router(validate.router)
    app.include_router(optimize.router)

    return app


app = create_app()
