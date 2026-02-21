# Repo2CI SaaS

Repo2CI is a SaaS-style app that accepts a GitHub repository URL, detects stack/language/framework hints, and generates production-ready CI/CD templates (GitHub Actions) for that repository.

## Features

- GitHub URL intake (`https://github.com/org/repo`)
- Repository tree analysis using GitHub API
- Tech profile detection:
  - Primary language + language mix
  - Framework hints (React, Next.js, FastAPI, Django, Spring Boot, etc.)
  - Package manager hints
- CI/CD generation:
  - GitHub Actions output
  - GitLab CI output
  - Jenkinsfile output
  - Optional `Security` and `CD` stages
- Recent analysis history persisted in PostgreSQL (Compose) or SQLite fallback
- Web UI to copy/download generated files
- ZIP download with real target file paths
- JWT auth (signup/login) and tenant-scoped data
- Billing-ready foundation with Stripe webhook ingestion

## Project Structure

```text
.
├── backend
│   ├── app
│   │   ├── analyzer.py
│   │   ├── cicd.py
│   │   ├── db.py
│   │   ├── github_client.py
│   │   ├── main.py
│   │   └── schemas.py
│   └── requirements.txt
├── web
│   ├── assets
│   │   ├── app.js
│   │   └── styles.css
│   └── index.html
├── Dockerfile
└── docker-compose.yml
```

## Run With Docker Compose

```bash
docker compose up --build
```

Open `http://localhost:8000`.

## Run Locally (Without Docker)

```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

- `GITHUB_TOKEN` (optional but recommended): increases GitHub API limits
- `DATABASE_URL` (recommended): PostgreSQL URL (Compose uses `postgresql://repo2ci:repo2ci@db:5432/repo2ci`)
- `DB_PATH` (optional fallback): SQLite path override when `DATABASE_URL` is not set
- `JWT_SECRET` (recommended in production)
- `JWT_EXP_MINUTES` (token expiry, default `1440`)
- `STRIPE_WEBHOOK_SECRET` (optional; enables signature verification)

## API Endpoints

- `GET /api/health`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/analyze` (auth required)
- `POST /api/analyze/zip` (auth required)
- `GET /api/analyses?limit=10` (auth required)
- `GET /api/billing/subscription` (auth required)
- `POST /api/billing/link-customer?customer_id=cus_xxx` (auth required)
- `POST /api/billing/webhook` (Stripe webhook)

Example request:

```json
{
  "repo_url": "https://github.com/vercel/next.js",
  "ci_provider": "github",
  "include_deploy": true,
  "include_security": true
}
```

## Notes

- Generated workflows are strong defaults, but deployment steps are intentionally a placeholder because cloud targets vary.
- Private repos need a valid `GITHUB_TOKEN` with appropriate access.
