from unittest.mock import AsyncMock, patch

import pytest

from app.models import new_uuid
from app.services.auth import OTP_KEY


# ── Helpers ───────────────────────────────────────────────────────────────────

async def login_as_role(client, conn, redis, role: str, mobile: str) -> dict:
    await conn.execute(
        "INSERT INTO users (id, mobile_number, role, is_active, created_at) VALUES ($1,$2,$3,true,NOW())",
        new_uuid(), mobile, role,
    )
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Invite endpoint ───────────────────────────────────────────────────────────

async def test_invite_sends_otp_to_customer(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")
    customer = "+919123456789"

    with patch("app.services.notifications.send_otp", new_callable=AsyncMock) as send:
        resp = await client.post(
            "/api/v1/admin/customers/invite",
            json={"mobile_number": customer},
            headers=headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mobile_number"] == customer
    assert body["expires_in_seconds"] == 300

    stored = await redis.get(OTP_KEY.format(customer))
    assert stored is not None
    assert len(stored) == 6

    send.assert_awaited_once()
    # user should NOT yet exist — creation happens on /auth/otp/verify
    row = await conn.fetchrow("SELECT id FROM users WHERE mobile_number = $1", customer)
    assert row is None


async def test_invite_then_verify_creates_user(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")
    customer = "+919123456789"

    with patch("app.services.notifications.send_otp", new_callable=AsyncMock):
        await client.post(
            "/api/v1/admin/customers/invite",
            json={"mobile_number": customer},
            headers=headers,
        )

    otp = await redis.get(OTP_KEY.format(customer))
    verify_resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": customer, "otp": otp},
    )
    assert verify_resp.status_code == 201

    row = await conn.fetchrow("SELECT id, role FROM users WHERE mobile_number = $1", customer)
    assert row is not None
    assert row["role"] == "user"


async def test_invite_rejects_non_admin(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "user", "+919600000002")

    resp = await client.post(
        "/api/v1/admin/customers/invite",
        json={"mobile_number": "+919123456789"},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_invite_rejects_invalid_mobile(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")

    resp = await client.post(
        "/api/v1/admin/customers/invite",
        json={"mobile_number": "not-a-number"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_invite_rate_limited(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")
    customer = "+919123456789"

    with patch("app.services.notifications.send_otp", new_callable=AsyncMock):
        for _ in range(3):
            await client.post(
                "/api/v1/admin/customers/invite",
                json={"mobile_number": customer},
                headers=headers,
            )
        resp = await client.post(
            "/api/v1/admin/customers/invite",
            json={"mobile_number": customer},
            headers=headers,
        )

    assert resp.status_code == 429
    assert "Too many OTP requests" in resp.json()["detail"]


# ── Checkout OTP gate ─────────────────────────────────────────────────────────

async def _make_customer(conn, mobile: str) -> str:
    uid = new_uuid()
    await conn.execute(
        "INSERT INTO users (id, mobile_number, role, is_active, created_at) VALUES ($1,$2,'user',true,NOW())",
        uid, mobile,
    )
    return uid


async def test_checkout_succeeds_with_valid_otp(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")
    customer = "+919123456789"
    await _make_customer(conn, customer)
    await redis.set(OTP_KEY.format(customer), "654321", ex=300)

    with patch("app.services.notifications.send_transaction_notification", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/admin/checkout",
            json={"mobile_number": customer, "amount": 500, "otp": "654321"},
            headers=headers,
        )

    assert resp.status_code == 201
    assert resp.json()["final_amount"] == 500
    # OTP should be consumed after verification
    assert await redis.get(OTP_KEY.format(customer)) is None


async def test_checkout_rejects_missing_otp(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")
    resp = await client.post(
        "/api/v1/admin/checkout",
        json={"mobile_number": "+919123456789", "amount": 500},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_checkout_rejects_wrong_otp(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")
    customer = "+919123456789"
    await _make_customer(conn, customer)
    await redis.set(OTP_KEY.format(customer), "654321", ex=300)

    resp = await client.post(
        "/api/v1/admin/checkout",
        json={"mobile_number": customer, "amount": 500, "otp": "000000"},
        headers=headers,
    )
    assert resp.status_code == 401
    # Wrong OTP should not consume the stored value
    assert await redis.get(OTP_KEY.format(customer)) == "654321"


async def test_checkout_rejects_expired_otp(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "admin", "+919600000001")
    customer = "+919123456789"
    await _make_customer(conn, customer)
    # No OTP in Redis → treated as expired

    resp = await client.post(
        "/api/v1/admin/checkout",
        json={"mobile_number": customer, "amount": 500, "otp": "654321"},
        headers=headers,
    )
    assert resp.status_code == 401


async def test_checkout_rejects_non_admin(client, conn, redis):
    headers = await login_as_role(client, conn, redis, "user", "+919600000002")
    resp = await client.post(
        "/api/v1/admin/checkout",
        json={"mobile_number": "+919123456789", "amount": 500, "otp": "123456"},
        headers=headers,
    )
    assert resp.status_code == 403
