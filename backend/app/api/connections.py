"""Connections router: test a connection, introspect its schema.

Connection metadata is stored in-memory keyed by the authenticated Cognito
``sub`` so that connections are isolated per user. Passwords are held only as
``SecretStr`` and are never returned to clients.
"""

from __future__ import annotations

import uuid
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.deps import CurrentUser, get_current_user
from app.logging_utils import get_logger
from app.models.api_models import (
    ConnectionConfig,
    ConnectionInfo,
    TestConnectionResponse,
)
from app.models.schema_models import NormalizedSchema
from app.services.schema import SchemaService

logger = get_logger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])

# In-memory per-user connection store: {sub: {connection_id: ConnectionConfig}}.
_connections: dict[str, dict[str, ConnectionConfig]] = {}
_store_lock = Lock()


def _get_schema_service(request: Request) -> SchemaService:
    service = getattr(request.app.state, "schema_service", None)
    if service is None:
        service = SchemaService()
        request.app.state.schema_service = service
    return service


def _to_info(connection_id: str, config: ConnectionConfig) -> ConnectionInfo:
    return ConnectionInfo(
        connection_id=connection_id,
        dialect=config.dialect,
        host=config.host,
        port=config.port,
        database=config.database,
        username=config.username,
    )


@router.post("/test", response_model=TestConnectionResponse)
def test_connection(
    config: ConnectionConfig,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> TestConnectionResponse:
    """Test the connection, introspect schema, and store metadata for the user."""
    service = _get_schema_service(request)
    try:
        schema: NormalizedSchema = service.get_schema(user.sub, config, force_refresh=True)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface as a clean 502
        logger.warning("Connection test failed for user %s", user.sub)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to the database",
        ) from exc

    connection_id = uuid.uuid4().hex
    with _store_lock:
        _connections.setdefault(user.sub, {})[connection_id] = config

    return TestConnectionResponse(
        connection=_to_info(connection_id, config),
        ok=True,
        table_count=len(schema.tables),
    )


@router.get("", response_model=list[ConnectionInfo])
def list_connections(
    user: CurrentUser = Depends(get_current_user),
) -> list[ConnectionInfo]:
    """List the current user's connections (without secrets)."""
    with _store_lock:
        user_conns = dict(_connections.get(user.sub, {}))
    return [_to_info(cid, cfg) for cid, cfg in user_conns.items()]
