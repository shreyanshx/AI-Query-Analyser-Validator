# AI Query Analyser & Validator - Backend

FastAPI backend for the AI Query Analyser & Validator platform.

## Development

Requires Python 3.11.

```bash
cd backend
uv venv --python 3.11
uv pip install -e '.[dev]'
uv run ruff check .
uv run black --check .
uv run pytest -q
```

## Overview

- `app/main.py` - FastAPI app factory (`create_app`) and `app` instance.
- `app/config.py` - pydantic-settings configuration + Secrets Manager loader.
- `app/auth/` - Cognito JWT verification with injectable JWKS.
- `app/db/` - DB adapter interface + PostgreSQL adapter + factory.
- `app/services/` - schema introspection service with TTL cache.
- `app/models/` - normalized schema models + API request/response models.
- `app/api/` - routers (`/health`, `/connections`).

No user-entered or AI-generated SQL is ever executed. Database connections are
used only for connection checks, schema introspection, and opt-in sampling.
