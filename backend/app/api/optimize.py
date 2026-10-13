"""Optimize router: rule-based SQL optimization.

``POST /api/optimize`` returns deterministic, rule-based optimizations and a
best-effort rewritten query. All performance implications are estimates derived
from static AST analysis; no SQL is ever executed.

AI integration point
---------------------
FEAT-003 will add an AI optimization layer. The call site is isolated in
:func:`_ai_optimize`, which currently returns ``None`` (rule-based only). When
the AI layer lands it will:

* produce an ``AISuggestion`` through the provider abstraction / fallback chain,
* re-validate the suggested SQL with :class:`SqlValidator` against the same
  cached schema before marking it valid, and
* populate ``suggested_sql`` / ``explanation`` / ``provider`` /
  ``is_suggestion_valid`` on the response.

Until then the endpoint defaults to rule-based output only, even when
``use_ai`` is requested.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.connections import get_connection_config
from app.auth.deps import CurrentUser, get_current_user
from app.logging_utils import get_logger
from app.models.api_models import OptimizeRequest, OptimizeResponse
from app.models.schema_models import NormalizedSchema
from app.services.optimizer import RuleBasedOptimizer
from app.services.schema import SchemaService

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["optimize"])

_optimizer = RuleBasedOptimizer()


def _get_schema_service(request: Request) -> SchemaService:
    service = getattr(request.app.state, "schema_service", None)
    if service is None:
        service = SchemaService()
        request.app.state.schema_service = service
    return service


def _ai_optimize(
    request: Request,
    user: CurrentUser,
    payload: OptimizeRequest,
    schema: NormalizedSchema | None,
    response: OptimizeResponse,
) -> OptimizeResponse | None:
    """AI optimization integration point (filled in by FEAT-003).

    Returns ``None`` today so the endpoint defaults to rule-based output. The
    FEAT-003 implementation will enrich ``response`` with an AI suggestion that
    has been re-validated by the deterministic validator.
    """
    return None


@router.post("/optimize", response_model=OptimizeResponse)
def optimize_sql(
    payload: OptimizeRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> OptimizeResponse:
    """Return rule-based optimizations (and AI suggestions once FEAT-003 lands)."""
    schema: NormalizedSchema | None = None
    if payload.connection_id:
        config = get_connection_config(user.sub, payload.connection_id)
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Unknown connection_id",
            )
        service = _get_schema_service(request)
        try:
            schema = service.get_schema(user.sub, config)
        except Exception as exc:  # noqa: BLE001 - surface schema load failure
            logger.warning("Schema load failed for user %s", user.sub)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not load schema for the connection",
            ) from exc

    optimizations = _optimizer.optimize(payload.sql, dialect=payload.dialect, schema=schema)
    response = OptimizeResponse(
        original_sql=payload.sql,
        rewritten_sql=_optimizer.rewritten_sql(optimizations),
        optimizations=optimizations,
    )

    if payload.use_ai:
        ai_response = _ai_optimize(request, user, payload, schema, response)
        if ai_response is not None:
            return ai_response

    return response
