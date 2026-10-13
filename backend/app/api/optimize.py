"""Optimize router: rule-based SQL optimization.

``POST /api/optimize`` returns deterministic, rule-based optimizations and a
best-effort rewritten query. All performance implications are estimates derived
from static AST analysis; no SQL is ever executed.

AI integration point
---------------------
The AI optimization layer is isolated in :func:`_ai_optimize`. It is
best-effort and never blocks the deterministic rule-based result:

* it produces an ``AISuggestion`` through the provider abstraction / fallback
  chain (:class:`AIOrchestrator`),
* re-validates the suggested SQL with :class:`SqlValidator` against the same
  cached schema and sets ``is_suggestion_valid`` accordingly, and
* populates ``suggested_sql`` / ``explanation`` / ``provider`` on the response.

When no provider is configured or all are unavailable, the response keeps the
rule-based output and signals ``ai_available=false`` with a message. Provider
credentials are read from settings / IAM only and are never returned or logged.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai.base import AllProvidersUnavailable, ProviderRefusal
from app.ai.orchestrator import AIOrchestrator
from app.ai.prompt import PromptContext
from app.api.connections import get_connection_config
from app.auth.deps import CurrentUser, get_current_user
from app.logging_utils import get_logger
from app.models.api_models import Optimization, OptimizeRequest, OptimizeResponse
from app.models.schema_models import NormalizedSchema
from app.services.optimizer import RuleBasedOptimizer
from app.services.schema import SchemaService
from app.services.validator import SqlValidator

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["optimize"])

_optimizer = RuleBasedOptimizer()
_validator = SqlValidator()


def _get_orchestrator(request: Request) -> AIOrchestrator:
    orchestrator = getattr(request.app.state, "ai_orchestrator", None)
    if orchestrator is None:
        orchestrator = AIOrchestrator()
        request.app.state.ai_orchestrator = orchestrator
    return orchestrator


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
) -> OptimizeResponse:
    """Enrich ``response`` with a best-effort, re-validated AI suggestion.

    This never raises for AI-side problems and never blocks the deterministic
    result. When a provider produces a suggestion, the suggested SQL is
    re-validated with :class:`SqlValidator` against the same cached schema and
    ``is_suggestion_valid`` is set from that deterministic check. When AI is
    unavailable (nothing configured / all unavailable) or refuses / errors,
    the rule-based ``response`` is returned with ``ai_available=False`` and a
    short message.
    """
    orchestrator = _get_orchestrator(request)
    context = PromptContext.from_schema(payload.sql, dialect=payload.dialect, schema=schema)

    try:
        suggestion = asyncio.run(orchestrator.suggest(context))
    except AllProvidersUnavailable:
        response.ai_available = False
        response.ai_message = (
            "AI suggestions are temporarily unavailable; showing rule-based results."
        )
        return response
    except ProviderRefusal:
        response.ai_available = False
        response.ai_message = "The AI provider declined to answer this request."
        return response
    except Exception:  # noqa: BLE001 - AI is best-effort, never block results
        logger.warning("AI optimization failed for user %s", user.sub)
        response.ai_available = False
        response.ai_message = "AI suggestions could not be produced; showing rule-based results."
        return response

    # Re-validate the AI suggestion deterministically before trusting it.
    validation = _validator.validate(
        suggestion.suggested_sql, dialect=payload.dialect, schema=schema
    )

    response.ai_available = True
    response.provider = suggestion.provider
    response.suggested_sql = suggestion.suggested_sql
    response.explanation = suggestion.explanation
    response.is_suggestion_valid = validation.is_valid
    if suggestion.optimizations:
        # Surface AI-named optimizations as info-level findings alongside the
        # rule-based ones, clearly attributed to the provider.
        for item in suggestion.optimizations:
            response.optimizations.append(
                Optimization(
                    rule="ai-suggestion",
                    severity="info",
                    message=item,
                )
            )
    if not validation.is_valid:
        response.ai_message = (
            "The AI suggestion did not pass deterministic validation and is "
            "flagged as not validated."
        )
    return response


@router.post("/optimize", response_model=OptimizeResponse)
def optimize_sql(
    payload: OptimizeRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> OptimizeResponse:
    """Return rule-based optimizations and, when ``use_ai`` is set, a re-validated AI suggestion."""
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
        return _ai_optimize(request, user, payload, schema, response)

    return response
