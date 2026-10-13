# AI Query Analyser & Validator (AIQAV)

AIQAV is a web platform that helps developers and analysts **validate, analyse,
and improve SQL** across dialects, with AI-assisted suggestions - **without ever
executing their queries**. You connect a database (read-only introspection
only), paste or write SQL, and get deterministic validation plus optimization
and rewrite suggestions grounded in your real schema.

> ### Safety guarantee (read this first)
> **No SQL is ever executed.** Neither the SQL you enter nor any SQL the AI
> generates is run against your database. Connections are used only for
> connection checks, catalog/schema introspection, statistics, and strictly
> opt-in, limited data sampling.
>
> **Credentials never leave the server.** Database credentials are never sent
> to any AI provider and are never returned to the browser. AI provider keys
> live in AWS Secrets Manager (or the EC2 IAM role for Bedrock) and are never
> embedded in the frontend bundle or exposed to the client.

## What it does

- **Deterministic validation** of all supported statement types (not just
  `SELECT`) using SQLGlot parsing against the connected dialect.
- **Schema-aware analysis** using a cached, normalized view of your database
  schema so validation and suggestions reflect your real tables and columns.
- **AI-assisted optimization and rewrites** through a provider abstraction with
  a configurable fallback chain (**Gemini -> Amazon Bedrock -> OpenAI ->
  Anthropic**). Every AI-generated suggestion is **re-validated** by the
  deterministic parser before it is shown as valid.
- **Authentication via Amazon Cognito** (public app client, no secret). The
  backend validates JWTs and isolates each user's connections and analyses by
  their Cognito `sub`.

## Known limitations (MVP scope)

- **Live-database features are PostgreSQL-only.** Syntax validation works across
  all listed dialects (PostgreSQL, MySQL, SQL Server, SQLite, Oracle) via
  SQLGlot, but anything that needs a live connection - connection testing,
  schema introspection, and opt-in data sampling - is implemented only for
  PostgreSQL. Selecting another dialect for a *live connection* raises
  `NotImplementedError`; its schema-aware validation and AI suggestions are not
  available until that adapter is added (`backend/app/db/factory.py`). You can
  still run dialect-aware **syntax** validation for any supported dialect
  without a connection. The dialect dropdown in the SPA reflects parse-time
  support; schema-aware features assume a PostgreSQL connection.
- **Performance findings are estimates.** Optimizations come from static AST
  analysis, not query plans; `EXPLAIN`-based planning is gated off by default.

## Architecture

A React (Vite + TypeScript) SPA and a FastAPI (Python 3.11) backend run on **one
raw Amazon EC2 `t3.micro`** behind an Application Load Balancer. No Docker, no
ECS/Fargate, no S3/CloudFront.

```
Route 53 -> ALB (HTTPS via ACM) --HTTP--> EC2 t3.micro
                                            |
                                 Nginx :80  --> /var/www/aiqav  (React SPA, SPA fallback)
                                            |-> /api/   -> 127.0.0.1:8000  (FastAPI)
                                            |-> /health -> 127.0.0.1:8000/health (ALB check)
                                                         |
                                   Gunicorn + Uvicorn workers under systemd
                                              app.main:app
```

- **Frontend**: built with `npm run build` (emits `frontend/dist`), served as
  static files by Nginx with SPA fallback to `index.html`.
- **Backend**: FastAPI `app.main:app` on port **8000**, run by Gunicorn with
  Uvicorn workers under systemd (`Restart=always`).
- **Auth**: Amazon Cognito User Pool + public app client.
- **Secrets**: AWS Secrets Manager; Bedrock via the EC2 IAM role (no static key).
- **Observability**: CloudWatch logs, with credentials always redacted.

Repository layout:

```
backend/      FastAPI app (app/main.py, app/config.py, app/api/, app/services/, ...)
frontend/     React + Vite SPA (src/, vite.config.ts)
deployment/   nginx/aiqav.conf, systemd/aiqav-backend.service, bootstrap.sh, README.md
.env.example  All backend + frontend config vars (placeholders only)
```

## Local development

Requires **Python 3.11** (via `uv`/`pyenv`) and **Node 20+**.

### Backend

```bash
cd backend
uv venv --python 3.11
uv pip install -e '.[dev]'
cp ../.env.example .env   # then fill in Cognito/AI values as needed
uv run uvicorn app.main:app --reload
```

The backend listens on `http://localhost:8000`. `GET /health` is public; all
`/api/*` routes require a valid Cognito JWT.

### Frontend

```bash
cd frontend
npm install
cp ../.env.example .env    # keep only the VITE_* vars; set your Cognito ids
npm run dev
```

The Vite dev server runs on `http://localhost:5173` and proxies `/api` to the
backend on `:8000` (see `frontend/vite.config.ts`), so the SPA and API share an
origin during development.

## Testing

```bash
# Backend: lint, format check, and unit tests (external DB/AI calls are mocked)
cd backend
uv run ruff check .
uv run black --check .
uv run pytest -q

# Frontend: type-check + production build (primary gate)
cd ../frontend
npm run build
# optional unit tests
npx vitest run
```

Tests never require a live database or real AI provider credentials; all
external calls are mockable.

## Deployment (raw EC2)

See [`deployment/README.md`](deployment/README.md) for the full step-by-step
guide. In short:

1. Launch an EC2 `t3.micro` with the IAM instance profile described in the
   deployment guide, and a security group allowing `:80` from the ALB only.
2. Run the idempotent provisioner:
   ```bash
   sudo REPO_URL=https://github.com/REPLACE_ME_ORG/AI-Query-Analyser-Validator.git \
        REPO_BRANCH=main bash deployment/bootstrap.sh
   ```
   It installs Python 3.11, Node 20+, and Nginx; builds the frontend into
   `/var/www/aiqav`; creates the backend venv; installs
   [`deployment/nginx/aiqav.conf`](deployment/nginx/aiqav.conf) and
   [`deployment/systemd/aiqav-backend.service`](deployment/systemd/aiqav-backend.service);
   and enables the services.
3. Put an ALB in front terminating HTTPS with ACM, health-checking `/health`;
   add a Route 53 alias record; configure the Cognito User Pool, Secrets
   Manager secret, and CloudWatch logging as described in the guide.

## Configuration

Every backend and frontend configuration variable is documented with
placeholder values in [`.env.example`](.env.example). Backend values are read by
`backend/app/config.py`; `VITE_*` values are public build-time config for the
frontend. Real secrets belong in AWS Secrets Manager, never in the repository.
