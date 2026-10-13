# AIQAV Deployment & Infrastructure Guide

This directory contains everything needed to run **AI Query Analyser & Validator**
(AIQAV) on a single raw Amazon EC2 `t3.micro` behind an Application Load
Balancer. There is **no Docker, no ECS/Fargate, and no S3/CloudFront** for the
frontend. The React build is served as static files by Nginx on the instance;
Nginx reverse-proxies `/api` to the FastAPI backend running locally under
systemd.

```
Internet
   |
   v
Route 53 (DNS)  ->  AWS ALB (HTTPS, ACM cert)  --HTTP:80-->  EC2 t3.micro
                                                               |
                                                   Nginx (:80)  --> /var/www/aiqav (React SPA)
                                                               |--> /api/   -> 127.0.0.1:8000
                                                               |--> /health -> 127.0.0.1:8000/health
                                                                            |
                                                             Gunicorn + Uvicorn workers (systemd)
                                                                   app.main:app  (FastAPI)
```

## Files in this directory

| File | Purpose |
| ---- | ------- |
| `nginx/aiqav.conf` | Nginx site: serve the React build with SPA fallback, proxy `/api/` and `/health` to FastAPI on `127.0.0.1:8000`. HTTP only (TLS terminates at the ALB). |
| `systemd/aiqav-backend.service` | Runs FastAPI (`app.main:app`) via Gunicorn with Uvicorn workers from the backend venv as the non-root `aiqav` user. `EnvironmentFile=/etc/aiqav/backend.env`, `Restart=always`. |
| `bootstrap.sh` | Idempotent provisioner for a fresh instance (Amazon Linux 2023 or Ubuntu): installs Python 3.11, Node 20+, Nginx; builds the frontend; creates the backend venv; installs the Nginx conf + systemd unit; enables and starts the services. |

## 1. Launch the EC2 instance

1. Launch an EC2 `t3.micro` (Amazon Linux 2023 recommended) in a private or
   public subnet of your choice.
2. Attach the **IAM instance profile** described in [section 6](#6-ec2-iam-instance-profile).
3. Security group: allow inbound **TCP 80 from the ALB security group only**
   (not from the internet). Allow outbound HTTPS so the instance can reach
   AWS APIs, PyPI, and npm during bootstrap.

## 2. Run the bootstrap script

SSH in (or use SSM Session Manager) and run:

```bash
sudo REPO_URL=https://github.com/REPLACE_ME_ORG/AI-Query-Analyser-Validator.git \
     REPO_BRANCH=main \
     bash deployment/bootstrap.sh
```

The script is safe to re-run for deploys (it fetches the latest code, rebuilds
the frontend, reinstalls backend deps, and restarts the services).

Before building the frontend for production, create
`frontend/.env.production` with your real `VITE_*` values (see the root
[`.env.example`](../.env.example)). These are **public** configuration values
(Cognito User Pool id, public app client id, region, API base URL) and are
safe to embed in the client bundle. **No AWS credentials or AI provider keys
are ever placed in frontend code.**

Edit the backend runtime config the script seeds at `/etc/aiqav/backend.env`
(mode `600`) and restart: `sudo systemctl restart aiqav-backend`.

## 3. Application Load Balancer + ACM (HTTPS termination)

1. **Request an ACM certificate** for your domain (e.g. `app.example.com`) in
   the same region as the ALB. Validate it via DNS (Route 53 can auto-create
   the validation records).
2. **Create an Application Load Balancer** (internet-facing) across at least two
   public subnets.
3. **Listeners:**
   - `HTTPS :443` -> forward to the target group below. Attach the ACM
     certificate. Use a modern TLS security policy.
   - `HTTP :80` -> redirect to `HTTPS :443` (301).
4. **Target group:**
   - Protocol/port: **HTTP : 80** (the ALB speaks plain HTTP to Nginx; TLS is
     already terminated at the ALB).
   - Target type: instance; register the EC2 instance.
   - **Health check path: `/health`** (HTTP, port traffic-port). This maps to
     the unauthenticated FastAPI `/health` route via Nginx. Expected codes:
     `200`.
5. The EC2 security group must allow inbound `:80` **from the ALB security
   group only**.

## 4. Route 53 (DNS)

Create an **A / AAAA alias record** for your application hostname
(e.g. `app.example.com`) pointing at the ALB's DNS name. Alias records are free
and resolve directly to the load balancer.

## 5. Cognito User Pool + public app client

AIQAV authenticates users with a Cognito **User Pool** and a **public app
client with no client secret** (the browser must never hold a secret).

1. **Create a User Pool.** Enable email as a sign-in attribute and require email
   verification. Configure the password policy and (optionally) MFA. These
   support sign-up, email verification, login, logout, token refresh, and
   forgot/reset password.
2. **Create an app client:**
   - **Do not generate a client secret** (public client).
   - Enable the auth flows your frontend uses (e.g. `ALLOW_USER_SRP_AUTH`,
     `ALLOW_REFRESH_TOKEN_AUTH`).
   - If you use the Cognito Hosted UI (optional), set:
     - Allowed callback URLs: `https://app.example.com/` (and
       `http://localhost:5173/` for local dev).
     - Allowed sign-out URLs: `https://app.example.com/` (and the localhost
       equivalent).
3. Record the **User Pool ID** and **App client ID**. These go into:
   - Frontend build: `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`,
     `VITE_AWS_REGION`.
   - Backend runtime: `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`,
     `AWS_REGION`.

The backend validates every protected request's Cognito JWT (signature via
JWKS, issuer, audience/client id, expiry, and token use) and isolates data by
the authenticated user's `sub`.

## 6. EC2 IAM instance profile

Attach an IAM role to the instance (via an instance profile) granting **least
privilege**:

- `secretsmanager:GetSecretValue` on the specific secret ARN only.
- `bedrock:InvokeModel` (and `bedrock:InvokeModelWithResponseStream` if used)
  on the model ARNs you call. Bedrock is accessed **through this IAM role, never
  a static AWS access key**.
- CloudWatch Logs: `logs:CreateLogGroup`, `logs:CreateLogStream`,
  `logs:PutLogEvents` for the application/system log groups.

Example policy (replace ARNs/region/account):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAppSecret",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:aiqav/backend-*"
    },
    {
      "Sid": "InvokeBedrock",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/aiqav/*"
    }
  ]
}
```

## 7. Secrets Manager (AI provider keys)

Store AI provider API keys in a single Secrets Manager secret and reference it
from the backend via `SECRETS_MANAGER_SECRET_ID`. At startup the backend reads
the secret and merges its JSON keys into the environment **without overwriting
values already set in the environment**. These keys **never reach the browser**
and are never logged.

Secret JSON shape (store as a `SecretString`):

```json
{
  "GEMINI_API_KEY": "...",
  "OPENAI_API_KEY": "...",
  "ANTHROPIC_API_KEY": "...",
  "BEDROCK_MODEL_ID": "anthropic.claude-3-haiku-20240307-v1:0",
  "BEDROCK_REGION": "us-east-1"
}
```

Then set in `/etc/aiqav/backend.env`:

```
SECRETS_MANAGER_SECRET_ID=aiqav/backend
AWS_REGION=us-east-1
```

Amazon Bedrock is reached through the EC2 IAM role, so a Bedrock API key is not
required; only non-AWS providers (Gemini/OpenAI/Anthropic) need keys in the
secret.

## 8. CloudWatch logs

Install and configure the CloudWatch agent (or use journald + the agent) to
ship Nginx access/error logs and the systemd journal for `aiqav-backend` to
CloudWatch Logs under `/aiqav/*`. **Never log credentials or unredacted
sensitive database values** - the application redacts connection credentials
before logging, and this must be preserved end to end.

## Security guarantees (do not weaken)

- **No SQL is ever executed.** Neither user-entered nor AI-generated SQL is run.
  Database connections are used only for connection checks, schema
  introspection, statistics, and opt-in limited data sampling.
- **Credentials never reach the AI provider or the browser.** Database
  credentials stay server-side and are never sent to any AI provider. AI
  provider keys live in Secrets Manager / the IAM role and are never embedded in
  the frontend bundle or returned to the client.
- **The frontend never handles AWS credentials.** Only public Cognito values
  (`VITE_*`) are embedded in the client build.
