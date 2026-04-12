from datetime import timedelta
from unittest.mock import patch

import pytest

from app.models import new_uuid, utcnow
from app.services.auth import OTP_KEY
from app.services.coins import InsufficientCoinsError, award_coins, get_balance, redeem_coins


# ── Helpers ───────────────────────────────────────────────────────────────────

async def make_user(conn, mobile="+919800000001"):
    uid = new_uuid()
    await conn.execute(
        "INSERT INTO users (id, mobile_number, role, is_active, created_at) VALUES ($1,$2,'user',true,NOW())",
        uid, mobile,
    )
    return {"id": uid, "mobile_number": mobile, "name": None, "role": "user"}


async def login(client, redis, mobile="+919800000001"):
    """Log in and return auth headers."""
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def seed_coins(conn, user_id: str, coins: int, redeemable: bool = True):
    """Insert a coins ledger entry, optionally already redeemable."""
    now = utcnow()
    offset = timedelta(days=1) if redeemable else timedelta(seconds=1)
    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
           VALUES ($1,$2,$3,'earned','active','seed',$4,$5,$6)""",
        new_uuid(), user_id, coins, now,
        now + timedelta(days=365),
        now - offset,
    )


# ── Balance ───────────────────────────────────────────────────────────────────

async def test_balance_zero_new_user(conn):
    user = await make_user(conn, "+919800000010")
    assert await get_balance(user["id"], conn) == 0


async def test_balance_increases_on_earn(conn):
    user = await make_user(conn, "+919800000011")
    await award_coins(user["id"], 100, "txn-1", conn)
    assert await get_balance(user["id"], conn) == 100


async def test_balance_decreases_on_redeem(conn):
    user = await make_user(conn, "+919800000012")
    await award_coins(user["id"], 100, "txn-1", conn)

    # txn_start slightly in the future so redeemable_after check passes
    txn_start = utcnow() + timedelta(seconds=2)
    await redeem_coins(user["id"], 60, "txn-2", txn_start, conn)

    assert await get_balance(user["id"], conn) == 40


async def test_cannot_redeem_more_than_balance(conn):
    user = await make_user(conn, "+919800000013")
    await award_coins(user["id"], 50, "txn-1", conn)

    txn_start = utcnow() + timedelta(seconds=2)
    with pytest.raises(InsufficientCoinsError):
        await redeem_coins(user["id"], 100, "txn-2", txn_start, conn)


async def test_cannot_redeem_coins_earned_in_same_transaction(conn):
    user = await make_user(conn, "+919800000014")
    now = utcnow()
    await award_coins(user["id"], 100, "txn-1", conn)

    # txn_start is BEFORE the coins were issued → redeemable_after check blocks it
    txn_start = now - timedelta(seconds=1)
    with pytest.raises(InsufficientCoinsError):
        await redeem_coins(user["id"], 50, "txn-2", txn_start, conn)


async def test_expired_coins_not_counted_in_balance(conn):
    user = await make_user(conn, "+919800000015")
    now = utcnow()
    # Insert an already-expired entry directly
    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
           VALUES ($1,$2,200,'earned','active','txn-old',$3,$4,$5)""",
        new_uuid(), user["id"], now - timedelta(days=400),
        now - timedelta(days=1),       # already expired
        now - timedelta(days=400),
    )

    assert await get_balance(user["id"], conn) == 0


async def test_expire_coins_job(test_pool):
    """expire_coins uses its own DB connection; must use committed data, not rolled-back conn."""
    uid = new_uuid()
    entry_id = new_uuid()
    now = utcnow()

    # Commit data directly so expire_coins (separate connection) can see it
    async with test_pool.acquire() as direct_conn:
        await direct_conn.execute(
            "INSERT INTO users (id, mobile_number, role, is_active, created_at) VALUES ($1,$2,'user',true,NOW())",
            uid, "+919800000016",
        )
        await direct_conn.execute(
            """INSERT INTO coins_ledger
                   (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
               VALUES ($1,$2,100,'earned','active','txn-1',$3,$4,$5)""",
            entry_id, uid,
            now - timedelta(days=400),
            now - timedelta(days=1),   # past expiry
            now - timedelta(days=400),
        )

    with patch("app.database.get_pool", return_value=test_pool):
        from app.jobs import expire_coins
        await expire_coins()

    async with test_pool.acquire() as direct_conn:
        status = await direct_conn.fetchval(
            "SELECT status FROM coins_ledger WHERE id = $1", entry_id
        )
        assert status == "expired"
        # Cleanup so this doesn't bleed into other tests
        await direct_conn.execute("DELETE FROM coins_ledger WHERE id = $1", entry_id)
        await direct_conn.execute("DELETE FROM users WHERE id = $1", uid)


# ── API Endpoints ─────────────────────────────────────────────────────────────

async def test_get_balance_endpoint(client, redis):
    headers = await login(client, redis, "+919800000020")
    response = await client.get("/api/v1/users/me/coins/balance", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_active_coins"] == 0
    assert data["expiring_soon"] is None


async def test_coin_history_empty(client, redis):
    headers = await login(client, redis, "+919800000021")
    response = await client.get("/api/v1/users/me/coins/history", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


async def test_coin_history_pagination(client, conn, redis):
    headers = await login(client, redis, "+919800000022")

    # Get user id from profile
    me = await client.get("/api/v1/users/me", headers=headers)
    user_id = me.json()["user_id"]

    # Add 5 ledger entries directly
    now = utcnow()
    for i in range(5):
        await conn.execute(
            """INSERT INTO coins_ledger
                   (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
               VALUES ($1,$2,10,'earned','active',$3,$4,$5,$6)""",
            new_uuid(), user_id, f"txn-{i}",
            now, now + timedelta(days=365), now,
        )

    resp = await client.get("/api/v1/users/me/coins/history?page=1&limit=3", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 3


async def test_update_profile_name(client, redis):
    headers = await login(client, redis, "+919800000023")
    response = await client.patch("/api/v1/users/me", json={"name": "Ravi Kumar"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Ravi Kumar"


async def test_balance_endpoint_requires_auth(client):
    response = await client.get("/api/v1/users/me/coins/balance")
    assert response.status_code == 401
