from datetime import timedelta

import pytest

from app.models import new_uuid, utcnow
from app.services.auth import OTP_KEY


# ── Helpers ───────────────────────────────────────────────────────────────────

async def login(client, redis, mobile="+919700000001"):
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def give_coins(conn, user_id: str, coins: int):
    """Seed coins that are immediately redeemable (redeemable_after in the past)."""
    now = utcnow()
    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
           VALUES ($1,$2,$3,'earned','active','seed',$4,$5,$6)""",
        new_uuid(), user_id, coins, now,
        now + timedelta(days=365),
        now - timedelta(days=1),   # already redeemable
    )


# ── Coin earn formula ─────────────────────────────────────────────────────────

async def test_purchase_awards_correct_coins(client, redis):
    """5 coins per ₹100 → ₹500 order → 25 coins."""
    headers = await login(client, redis, "+919700000001")
    resp = await client.post(
        "/api/v1/transactions",
        json={"amount": 500.0, "order_ref": "ORD-001"},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["coins_earned"] == 25       # floor(500 * 5 / 100)
    assert data["discount_applied"] == 0.0
    assert data["coins_redeemed"] == 0
    assert data["final_amount"] == 500.0
    assert data["coins_balance_after"] == 25


async def test_coins_earned_on_final_amount_not_gross(client, conn, redis):
    """Coins earned on final_amount (after discounts), not gross amount."""
    headers = await login(client, redis, "+919700000002")

    # Get user id and give redeemable coins
    me = await client.get("/api/v1/users/me", headers=headers)
    user_id = me.json()["user_id"]
    await give_coins(conn, user_id, 200)

    # ₹1000 order, redeem 200 coins (₹20 discount) → final = ₹980
    # coins_earned = floor(980 * 5 / 100) = 49
    resp = await client.post(
        "/api/v1/transactions",
        json={"amount": 1000.0, "coins_to_redeem": 200, "order_ref": "ORD-002"},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["coins_redeemed"] == 200
    assert data["coins_redeemed_value"] == 20.0
    assert data["final_amount"] == 980.0
    assert data["coins_earned"] == 49       # floor(980 * 5 / 100)


# ── Idempotency ───────────────────────────────────────────────────────────────

async def test_duplicate_order_ref_returns_same_transaction(client, conn, redis):
    headers = await login(client, redis, "+919700000003")

    resp1 = await client.post(
        "/api/v1/transactions",
        json={"amount": 300.0, "order_ref": "ORD-DUPE"},
        headers=headers,
    )
    resp2 = await client.post(
        "/api/v1/transactions",
        json={"amount": 300.0, "order_ref": "ORD-DUPE"},
        headers=headers,
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["transaction_id"] == resp2.json()["transaction_id"]

    # Only one transaction in DB
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE order_ref = 'ORD-DUPE'"
    )
    assert count == 1


# ── Coin redemption ───────────────────────────────────────────────────────────

async def test_coin_redemption_deducts_balance(client, conn, redis):
    headers = await login(client, redis, "+919700000004")
    me = await client.get("/api/v1/users/me", headers=headers)
    user_id = me.json()["user_id"]
    await give_coins(conn, user_id, 500)

    resp = await client.post(
        "/api/v1/transactions",
        json={"amount": 1000.0, "coins_to_redeem": 100},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    # Started with 500, redeemed 100, earned floor(990*5/100)=49 → 500-100+49=449
    assert data["coins_redeemed"] == 100
    assert data["coins_balance_after"] == 449


async def test_cannot_redeem_more_than_balance(client, redis):
    headers = await login(client, redis, "+919700000005")
    # No coins seeded
    resp = await client.post(
        "/api/v1/transactions",
        json={"amount": 500.0, "coins_to_redeem": 999},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "coins available" in resp.json()["detail"]


async def test_redemption_cap_20_percent(client, conn, redis):
    """Cannot redeem more than 20% of order value in coins."""
    headers = await login(client, redis, "+919700000006")
    me = await client.get("/api/v1/users/me", headers=headers)
    user_id = me.json()["user_id"]
    await give_coins(conn, user_id, 10000)  # lots of coins

    # ₹100 order, 20% cap = ₹20 = 200 coins max
    # Requesting 5000 coins → capped to 200
    resp = await client.post(
        "/api/v1/transactions",
        json={"amount": 100.0, "coins_to_redeem": 5000},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["coins_redeemed"] == 200   # capped to 20% of ₹100 / ₹0.10


# ── Transaction history ───────────────────────────────────────────────────────

async def test_transaction_history(client, redis):
    headers = await login(client, redis, "+919700000007")

    for i in range(3):
        await client.post(
            "/api/v1/transactions",
            json={"amount": 100.0, "order_ref": f"ORD-LIST-{i}"},
            headers=headers,
        )

    resp = await client.get("/api/v1/users/me/transactions", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


async def test_get_transaction_by_id(client, redis):
    headers = await login(client, redis, "+919700000008")
    create_resp = await client.post(
        "/api/v1/transactions",
        json={"amount": 250.0, "order_ref": "ORD-FETCH"},
        headers=headers,
    )
    txn_id = create_resp.json()["transaction_id"]

    resp = await client.get(f"/api/v1/transactions/{txn_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == txn_id


async def test_get_transaction_not_found(client, redis):
    headers = await login(client, redis, "+919700000009")
    resp = await client.get("/api/v1/transactions/nonexistent-id", headers=headers)
    assert resp.status_code == 404


async def test_transaction_without_order_ref(client, redis):
    """order_ref is optional — should still work."""
    headers = await login(client, redis, "+919700000010")
    resp = await client.post(
        "/api/v1/transactions",
        json={"amount": 200.0},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["coins_earned"] == 10   # floor(200 * 5 / 100)
