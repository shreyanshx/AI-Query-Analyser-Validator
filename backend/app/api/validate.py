"""Validate router: deterministic SQL validation.

``POST /api/validate`` runs syntax validation always, and schema-aware
validation when the request names a known ``connection_id`` for the current
user. No SQL is ever executed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.connections import get_connection_config
from app.auth.deps import CurrentUser, get_current_user
from app.logging_utils import get_logger
from app.models.api_models import ValidateRequest, ValidationResult
from app.models.schema_models import NormalizedSchema
from app.services.schema import SchemaService
from app.services.validator import SqlValidator

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["validate"])

_validator = SqlValidator()


def _get_schema_service(request: Request) -> SchemaService:
    service = getattr(request.app.state, "schema_service", None)
    if service is None:
        service = SchemaService()
        request.app.state.schema_service = service
    return service


@router.post("/validate", response_model=ValidationResult)
def validate_sql(
    payload: ValidateRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> ValidationResult:
    """Validate SQL syntax and, if a connection is given, schema references."""
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

    return _validator.validate(payload.sql, dialect=payload.dialect, schema=schema)
