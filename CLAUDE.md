# Platform GC — Backend

FastAPI loyalty & rewards platform for a retail shop.

## Stack
- **Framework**: FastAPI + Uvicorn (Python 3.11, uv package manager)
- **Database**: PostgreSQL + SQLAlchemy 2.0 async + Alembic migrations
- **Cache**: Redis (OTP storage, JWT refresh blacklist)
- **Scheduler**: APScheduler (in-process, replaces Celery — no separate worker)
- **Notifications**: Twilio WhatsApp → SMS fallback
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
Every new feature must follow this flow — no exceptions:
1. Create a branch: `git checkout -b feature/<name>` (or `fix/<name>` for bug fixes)
2. Make changes on the branch
3. Run tests: `uv run pytest tests/ -v` — all must pass
4. Commit on the branch
5. Push and raise a PR to `main` — never commit directly to `main`

```bash
git checkout -b feature/my-feature
# ... make changes ...
uv run pytest tests/ -v
git add <files>
git commit -m "feat: description"
git push -u origin feature/my-feature
# then open PR on GitHub
```

## Key rules
- All models in `models.py`, all schemas in `schemas.py` — split only if >300 lines
- Use `utcnow()` helper (naive UTC) for all datetime fields — SQLite/PostgreSQL compatible
- APScheduler runs inside the FastAPI process — no Celery, no separate worker
- Tests use SQLite (aiosqlite) + fakeredis — no real infrastructure needed
- Pre-push hook runs all 52 tests before every `git push`

## Coin ledger design
- Signed ledger: earned = +N, redeemed = -N
- Balance = `SUM(coins) WHERE status='active' AND expiry_at > now()`
- `redeemable_after` column prevents same-order coin redemption

## Environment variables
See `.env.example`. Key tunable values:
- `COINS_EARN_RATE` — coins per ₹100 spent (default: 5.0)
- `COIN_RUPEE_VALUE` — 1 coin = ₹X (default: 0.10)
- `MAX_COINS_REDEEM_PERCENT` — max % of order payable via coins (default: 20%)
- `COINS_EXPIRY_DAYS` — coin validity in days (default: 365)

## API prefix
All routes: `/api/v1/...`

## Deployment
- Local: `docker-compose up` (api + postgres + redis in one command)
- Production: Railway (api service + PostgreSQL add-on + Redis add-on)
- CI/CD: GitHub Actions — tests on every push, deploy to Railway on `main`
