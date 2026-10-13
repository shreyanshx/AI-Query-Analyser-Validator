"""FastAPI application factory.

``create_app`` wires CORS, routers, and logging. ``GET /health`` is
unauthenticated (for the ALB); all other routers require a valid Cognito JWT via
the ``get_current_user`` dependency applied on the individual routes.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import connections, health
from app.config import Settings, get_settings
from app.logging_utils import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    settings = settings or get_settings()

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

    return app


app = create_app()
