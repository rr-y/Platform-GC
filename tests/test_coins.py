from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models import CoinsLedger, User, utcnow
from app.services.auth import OTP_KEY
from app.services.coins import InsufficientCoinsError, award_coins, get_balance, redeem_coins


# ── Helpers ───────────────────────────────────────────────────────────────────

async def make_user(db, mobile="+919800000001"):
    user = User(mobile_number=mobile)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login(client, redis, mobile="+919800000001"):
    """Log in and return auth headers."""
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Balance ───────────────────────────────────────────────────────────────────

async def test_balance_zero_new_user(db):
    user = await make_user(db, "+919800000010")
    assert await get_balance(user.id, db) == 0


async def test_balance_increases_on_earn(db):
    user = await make_user(db, "+919800000011")
    now = utcnow()
    await award_coins(user.id, 100, "txn-1", db)
    await db.commit()
    assert await get_balance(user.id, db) == 100


async def test_balance_decreases_on_redeem(db):
    user = await make_user(db, "+919800000012")
    now = utcnow()
    await award_coins(user.id, 100, "txn-1", db)
    await db.commit()

    # Use a txn_start slightly in the future so redeemable_after check passes
    txn_start = utcnow() + timedelta(seconds=2)
    await redeem_coins(user.id, 60, "txn-2", txn_start, db)
    await db.commit()

    assert await get_balance(user.id, db) == 40


async def test_cannot_redeem_more_than_balance(db):
    user = await make_user(db, "+919800000013")
    await award_coins(user.id, 50, "txn-1", db)
    await db.commit()

    txn_start = utcnow() + timedelta(seconds=2)
    with pytest.raises(InsufficientCoinsError):
        await redeem_coins(user.id, 100, "txn-2", txn_start, db)


async def test_cannot_redeem_coins_earned_in_same_transaction(db):
    user = await make_user(db, "+919800000014")
    now = utcnow()
    await award_coins(user.id, 100, "txn-1", db)
    await db.commit()

    # txn_start is BEFORE the coins were issued → redeemable_after check blocks it
    txn_start = now - timedelta(seconds=1)
    with pytest.raises(InsufficientCoinsError):
        await redeem_coins(user.id, 50, "txn-2", txn_start, db)


async def test_expired_coins_not_counted_in_balance(db):
    user = await make_user(db, "+919800000015")
    now = utcnow()
    # Insert an already-expired entry directly
    expired = CoinsLedger(
        user_id=user.id,
        coins=200,
        type="earned",
        status="active",
        reference_id="txn-old",
        issued_at=now - timedelta(days=400),
        expiry_at=now - timedelta(days=1),   # already expired
        redeemable_after=now - timedelta(days=400),
    )
    db.add(expired)
    await db.commit()

    assert await get_balance(user.id, db) == 0


async def test_expire_coins_job(db, engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from unittest.mock import patch

    user = await make_user(db, "+919800000016")
    now = utcnow()
    entry = CoinsLedger(
        user_id=user.id,
        coins=100,
        type="earned",
        status="active",
        reference_id="txn-1",
        issued_at=now - timedelta(days=400),
        expiry_at=now - timedelta(days=1),
        redeemable_after=now - timedelta(days=400),
    )
    db.add(entry)
    await db.commit()

    # Patch jobs to use the same test engine (tables already exist there)
    test_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    with patch("app.jobs.AsyncSessionLocal", test_session_factory):
        from app.jobs import expire_coins
        await expire_coins()

    await db.refresh(entry)
    assert entry.status == "expired"


# ── API Endpoints ─────────────────────────────────────────────────────────────

async def test_get_balance_endpoint(client, db, redis):
    headers = await login(client, redis, "+919800000020")
    response = await client.get("/api/v1/users/me/coins/balance", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_active_coins"] == 0
    assert data["expiring_soon"] is None


async def test_coin_history_empty(client, db, redis):
    headers = await login(client, redis, "+919800000021")
    response = await client.get("/api/v1/users/me/coins/history", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


async def test_coin_history_pagination(client, db, redis):
    headers = await login(client, redis, "+919800000022")

    # Get user id from profile
    me = await client.get("/api/v1/users/me", headers=headers)
    user_id = me.json()["user_id"]

    # Add 5 ledger entries directly
    now = utcnow()
    for i in range(5):
        entry = CoinsLedger(
            user_id=user_id,
            coins=10,
            type="earned",
            status="active",
            reference_id=f"txn-{i}",
            issued_at=now,
            expiry_at=now + timedelta(days=365),
            redeemable_after=now,
        )
        db.add(entry)
    await db.commit()

    resp = await client.get("/api/v1/users/me/coins/history?page=1&limit=3", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 3


async def test_update_profile_name(client, db, redis):
    headers = await login(client, redis, "+919800000023")
    response = await client.patch("/api/v1/users/me", json={"name": "Ravi Kumar"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Ravi Kumar"


async def test_balance_endpoint_requires_auth(client):
    response = await client.get("/api/v1/users/me/coins/balance")
    assert response.status_code == 401
