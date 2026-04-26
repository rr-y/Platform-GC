# Platform GC — Backend

FastAPI loyalty & rewards platform for a retail shop.

## Stack
- **Framework**: FastAPI + Uvicorn (Python 3.11, uv package manager)
- **Database**: PostgreSQL + SQLAlchemy 2.0 async + Alembic migrations
- **Cache**: Redis (OTP storage, JWT refresh blacklist)
- **Scheduler**: APScheduler (in-process, replaces Celery — no separate worker)
- **Notifications**: Expo push (primary for logged-in users) → Twilio SMS fallback
- **Config**: pydantic-settings, single `.env` file

## Project structure
```
app/
  main.py          — FastAPI app + CORS + APScheduler lifespan
  config.py        — all settings via pydantic-settings
  models.py        — ALL SQLAlchemy models (single file)
  schemas.py       — ALL Pydantic schemas (single file)
  database.py      — async engine + get_db dependency
  redis.py         — Redis pool + get_redis dependency
  deps.py          — get_current_user, require_admin
  jobs.py          — APScheduler cron jobs
  routers/         — auth, coins, transactions, coupons, admin
  services/        — auth, coins, transactions, campaigns, notifications
  utils/security.py — JWT helpers
```

## Commands

```bash
# Local dev (Docker)
docker-compose up --build

# Run tests
uv run pytest tests/ -v

# Alembic migrations
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
```

## Git workflow
Every new feature or bug fix must follow this flow — no exceptions:
1. Create a branch: `git checkout -b feature/<name>` or `git checkout -b fix/<name>` for bugs
2. Make changes on the branch
3. Run tests: `uv run pytest tests/ -v` — all must pass
4. Commit on the branch
5. Push and raise a PR to `main` — **NEVER commit or push directly to `main`**

```bash
# New feature
git checkout -b feature/my-feature
# ... make changes ...
uv run pytest tests/ -v
git add <files>
git commit -m "feat: description"
git push -u origin feature/my-feature
# then open PR on GitHub

# Bug fix
git checkout -b fix/bug-description
# ... fix the bug ...
uv run pytest tests/ -v
git add <files>
git commit -m "fix: description"
git push -u origin fix/bug-description
# then open PR on GitHub
```

## Branch protection rule
**`main` is a protected branch — no exceptions:**
- Never run `git checkout main` then make changes
- Never run `git commit` on `main`
- Never run `git push` on `main` (or `git push origin main`)
- Never use `git merge` directly into `main`
- All changes reach `main` only through a merged PR on GitHub
- If already on `main` by mistake, stash changes and switch to a branch before committing

## Key rules
- All models in `models.py`, all schemas in `schemas.py` — split only if >300 lines
- Use `utcnow()` helper (naive UTC) for all datetime fields — SQLite/PostgreSQL compatible
- APScheduler runs inside the FastAPI process — no Celery, no separate worker
- Tests use SQLite (aiosqlite) + fakeredis — no real infrastructure needed
- Pre-push hook runs all 52 tests before every `git push`

## Dependency classification (non-negotiable)
Prod is deployed with dev groups excluded. A package imported under `app/` but listed only in the dev group will pass tests locally and in CI, then crash at runtime on Railway. This has already caused one production incident (httpx).

- **Any package imported anywhere under `app/` must live in `[project].dependencies` in `pyproject.toml`.** Not `[dependency-groups].dev`. No exceptions.
- **`[dependency-groups].dev` is strictly for test-only tooling** — `pytest`, `pytest-asyncio`, `pytest-cov`, `fakeredis`, etc. If `app/*` imports it, it is not dev.
- **Always add deps via `uv add`, never hand-edit `pyproject.toml`:**
  - Runtime: `uv add <pkg>`
  - Test-only: `uv add --group dev <pkg>`
  Hand-editing under the wrong table is the exact mistake that broke prod.
- **Before opening a PR that adds a new `import`**, confirm the package is in `[project].dependencies` and that `uv sync --frozen --no-dev && uv run python -c "import app.main"` succeeds. CI enforces this, but catch it locally first.

## Coin ledger design
- Signed ledger: earned = +N, redeemed = -N
- Balance = `SUM(coins) WHERE status='active' AND expiry_at > now()`
- `redeemable_after` column prevents same-order coin redemption

## Environment variables
See `.env.example` for the full list. Local dev reads `.env`; production reads from the Railway dashboard (never commit `.env`).

**Environment-aware settings** (`app/config.py`):
- `APP_ENV` — `development` (default) or `production`. Accessed via `settings.is_production` — do NOT hardcode the string elsewhere.
- `CORS_ORIGINS` — comma-separated allowlist; `"*"` in dev, explicit domains in prod.
- `LOG_LEVEL` — `DEBUG` in dev, `INFO` in prod.

**Tunable business values:**
- `COINS_EARN_RATE` — coins per ₹100 spent (default: 5.0)
- `COIN_RUPEE_VALUE` — 1 coin = ₹X (default: 0.10)
- `MAX_COINS_REDEEM_PERCENT` — max % of order payable via coins (default: 20%)
- `COINS_EXPIRY_DAYS` — coin validity in days (default: 365)

**Production (Railway dashboard) — required keys:**
`APP_ENV=production`, `SECRET_KEY` (32-byte random), `LOG_LEVEL=INFO`, `CORS_ORIGINS=<your frontend domains>`, `DATABASE_URL`, `REDIS_URL`, all four `TWILIO_*`. Leave `ADMIN_SECRET_KEY` unset once the first admin is bootstrapped.

## API prefix
All routes: `/api/v1/...`

## Deployment
- Local: `docker-compose up` (api + postgres + redis in one command)
- Production: Railway (api service + PostgreSQL add-on + Redis add-on)
- CI/CD: GitHub Actions — tests on every push, deploy to Railway on `main`
