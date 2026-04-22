import os
import pytest
import pytest_asyncio
import asyncpg
from httpx import ASGITransport, AsyncClient

from app.database import get_conn
from app.main import app
from app.redis import get_redis

# Tests require PostgreSQL — use docker-compose postgres with a separate test DB
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/platform_gc_test",
)

# DDL to create all tables for the test database (mirrors the alembic migration)
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id           VARCHAR(36) PRIMARY KEY,
    mobile_number VARCHAR(15) UNIQUE NOT NULL,
    name         VARCHAR(100),
    role         VARCHAR(10) NOT NULL DEFAULT 'user',
    is_active    BOOLEAN NOT NULL DEFAULT true,
    push_token   VARCHAR(255),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id               VARCHAR(36) PRIMARY KEY,
    title            VARCHAR(200) NOT NULL,
    type             VARCHAR(30) NOT NULL,
    discount_value   NUMERIC(10,2),
    min_order_value  NUMERIC(10,2) NOT NULL DEFAULT 0,
    max_discount_cap NUMERIC(10,2),
    valid_from       TIMESTAMPTZ NOT NULL,
    valid_to         TIMESTAMPTZ NOT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    audience_type    VARCHAR(20) NOT NULL DEFAULT 'all',
    usage_limit      INTEGER,
    usage_count      INTEGER NOT NULL DEFAULT 0,
    image_url        TEXT,
    description      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coupons (
    id              VARCHAR(36) PRIMARY KEY,
    campaign_id     VARCHAR(36) NOT NULL REFERENCES campaigns(id),
    code            VARCHAR(30) UNIQUE NOT NULL,
    is_auto_apply   BOOLEAN NOT NULL DEFAULT false,
    max_uses        INTEGER,
    uses_count      INTEGER NOT NULL DEFAULT 0,
    per_user_limit  INTEGER NOT NULL DEFAULT 1,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coupon_code ON coupons(code);

CREATE TABLE IF NOT EXISTS coins_ledger (
    id               VARCHAR(36) PRIMARY KEY,
    user_id          VARCHAR(36) NOT NULL REFERENCES users(id),
    coins            INTEGER NOT NULL,
    type             VARCHAR(20) NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'active',
    reference_id     VARCHAR(36),
    issued_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expiry_at        TIMESTAMPTZ NOT NULL,
    redeemable_after TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coins_user_status ON coins_ledger(user_id, status);
CREATE INDEX IF NOT EXISTS idx_coins_expiry ON coins_ledger(expiry_at);

CREATE TABLE IF NOT EXISTS transactions (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL REFERENCES users(id),
    order_ref       VARCHAR(100) UNIQUE,
    amount          NUMERIC(12,2) NOT NULL,
    coins_earned    INTEGER NOT NULL DEFAULT 0,
    coins_used      INTEGER NOT NULL DEFAULT 0,
    discount_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
    coupon_id       VARCHAR(36) REFERENCES coupons(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'completed',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_txn_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_txn_order_ref ON transactions(order_ref);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id             VARCHAR(36) PRIMARY KEY,
    coupon_id      VARCHAR(36) NOT NULL REFERENCES coupons(id),
    user_id        VARCHAR(36) NOT NULL REFERENCES users(id),
    transaction_id VARCHAR(36) NOT NULL REFERENCES transactions(id),
    redeemed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coupon_redemption_user_coupon ON coupon_redemptions(user_id, coupon_id);

CREATE TABLE IF NOT EXISTS notification_logs (
    id           VARCHAR(36) PRIMARY KEY,
    user_id      VARCHAR(36) NOT NULL REFERENCES users(id),
    channel      VARCHAR(20) NOT NULL,
    type         VARCHAR(50) NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_detail TEXT,
    sent_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_user_eligibility (
    id          VARCHAR(36) PRIMARY KEY,
    campaign_id VARCHAR(36) NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id     VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_campaign_user_elig ON campaign_user_eligibility(user_id, campaign_id);

CREATE TABLE IF NOT EXISTS print_jobs (
    id               VARCHAR(36) PRIMARY KEY,
    user_id          VARCHAR(36) NOT NULL REFERENCES users(id),
    file_name        VARCHAR(255) NOT NULL,
    mime_type        VARCHAR(50) NOT NULL,
    file_size        INTEGER NOT NULL,
    storage_path     TEXT,
    page_count       INTEGER NOT NULL,
    selected_pages   JSONB,
    color_mode       VARCHAR(10),
    copies           INTEGER,
    subtotal         NUMERIC(12,2),
    coins_to_redeem  INTEGER NOT NULL DEFAULT 0,
    coin_value       NUMERIC(12,2) NOT NULL DEFAULT 0,
    final_amount     NUMERIC(12,2),
    pickup_otp       CHAR(4),
    status           VARCHAR(20) NOT NULL DEFAULT 'draft',
    retry_count      INTEGER NOT NULL DEFAULT 0,
    transaction_id   VARCHAR(36) REFERENCES transactions(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    queued_at        TIMESTAMPTZ,
    claimed_at       TIMESTAMPTZ,
    printed_at       TIMESTAMPTZ,
    collected_at     TIMESTAMPTZ,
    cancelled_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_print_user_status ON print_jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_print_queued ON print_jobs(status, queued_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_print_active_pickup_otp
    ON print_jobs (pickup_otp)
    WHERE status IN ('queued','printing','printed');
"""


@pytest_asyncio.fixture(scope="session")
async def test_pool():
    """Session-scoped pool. Creates test DB and schema once per test run."""
    # Create test database if it doesn't exist
    admin_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    sys_conn = await asyncpg.connect(admin_url)
    exists = await sys_conn.fetchval(
        "SELECT 1 FROM pg_database WHERE datname = 'platform_gc_test'"
    )
    if not exists:
        await sys_conn.execute("CREATE DATABASE platform_gc_test")
    await sys_conn.close()

    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=2, max_size=5)

    # Drop and recreate all tables for a clean run
    async with pool.acquire() as conn:
        await conn.execute(
            """DROP TABLE IF EXISTS
               print_jobs, notification_logs, coupon_redemptions, transactions,
               coins_ledger, campaign_user_eligibility, coupons, campaigns, users CASCADE"""
        )
        await conn.execute(_SCHEMA_SQL)

    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def conn(test_pool):
    """Function-scoped connection wrapped in a transaction that is always rolled back."""
    async with test_pool.acquire() as connection:
        tr = connection.transaction()
        await tr.start()
        yield connection
        await tr.rollback()


@pytest_asyncio.fixture
async def redis():
    import fakeredis.aioredis as fakeredis
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def client(conn, redis):
    async def override_get_conn():
        yield conn

    app.dependency_overrides[get_conn] = override_get_conn
    app.dependency_overrides[get_redis] = lambda: redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
