---
inclusion: always
---

# Project Architecture Decisions

## Hosting

- Host both the React frontend and FastAPI backend directly on one Amazon EC2 `t3.micro` instance; do not use S3 or CloudFront for frontend hosting.
- Do not use Docker, ECS, or Fargate.
- Build the React application during deployment and serve its static production files with Nginx on EC2.
- Configure Nginx to serve the React application and reverse-proxy `/api` requests to FastAPI on localhost.
- Install the Python runtime and backend dependencies in a virtual environment on EC2.
- Run FastAPI with Gunicorn/Uvicorn under `systemd` so it starts on boot and restarts after failures.
- Put an AWS Application Load Balancer in front of EC2. Terminate HTTPS with an ACM certificate.
- Manage DNS with Amazon Route 53.
- Send application and system logs to Amazon CloudWatch. Never log credentials or unredacted sensitive database values.
- Store application-level secrets, including the AI provider API key, in AWS Secrets Manager.
- Use an in-memory TTL cache for normalized database schema metadata in the MVP. Add ElastiCache only when horizontal scaling requires shared cache state.
- Add PostgreSQL/RDS only if persistent application records such as accounts, saved connections, teams, or analysis history require it.

## Authentication

- Use an Amazon Cognito User Pool for portal authentication.
- Support sign-up, email verification, login, logout, token refresh, and forgot/reset password.
- Use a Cognito public app client without a client secret for the browser application.
- The frontend must never handle AWS credentials.
- The backend must validate Cognito JWT signatures, issuer, audience/client ID, expiry, and token use before serving protected API routes.
- Keep database connection sessions and analyses isolated by the authenticated Cognito user identifier (`sub`).

## SQL and Database Behavior

- Validate all supported SQL statement types, not only `SELECT`.
- Never execute user-entered or AI-generated SQL.
- Database connections are used for connection checks, catalog/schema introspection, statistics retrieval, and optional controlled data sampling only.
- Data-aware sampling must be opt-in, limited, and configurable. Never send database credentials to the AI provider.
- Use cached normalized schema context for live validation and AI suggestions.
- Treat performance improvements as estimates unless the user explicitly enables a query-planning feature.

## AI

- Use an AI provider abstraction so providers can be changed without rewriting validation logic.
- Use an eligible Gemini Developer API free-tier model as the default MVP provider, configured through backend secrets rather than frontend code.
- Support an administrator-configurable provider fallback chain, initially Gemini, Amazon Bedrock, OpenAI, and Anthropic.
- Store provider API keys in AWS Secrets Manager; access Bedrock through the EC2 IAM role rather than a static AWS key.
- Trigger fallback only for provider timeouts, service unavailability, throttling, or exhausted quota. Do not use fallback to bypass provider safety refusals or account limits.
- Apply the same schema/data-sharing policy to every fallback provider and never expose provider credentials to the browser.
- Normalize every provider response to the same internal result format.
- Revalidate every AI-generated SQL suggestion with the deterministic parser and schema validator before showing it as valid.
