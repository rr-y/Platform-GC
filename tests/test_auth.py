from unittest.mock import AsyncMock, patch

import pytest

from app.services.auth import OTP_KEY, OTP_REQ_COUNT_KEY, REFRESH_KEY


# ── OTP Request ───────────────────────────────────────────────────────────────

async def test_otp_request_success(client, redis):
    with patch("app.services.notifications.send_otp", new_callable=AsyncMock):
        response = await client.post("/api/v1/auth/otp/request", json={"mobile_number": "+919876543210"})
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "OTP sent"
    assert data["expires_in_seconds"] == 300

    # OTP should be stored in Redis
    stored = await redis.get(OTP_KEY.format("+919876543210"))
    assert stored is not None
    assert len(stored) == 6


async def test_otp_request_invalid_number(client):
    response = await client.post("/api/v1/auth/otp/request", json={"mobile_number": "invalid"})
    assert response.status_code == 422


async def test_otp_request_rate_limit(client, redis):
    with patch("app.services.notifications.send_otp", new_callable=AsyncMock):
        for _ in range(3):
            await client.post("/api/v1/auth/otp/request", json={"mobile_number": "+919876543210"})
        response = await client.post("/api/v1/auth/otp/request", json={"mobile_number": "+919876543210"})
    assert response.status_code == 429
    assert "Too many OTP requests" in response.json()["detail"]


# ── OTP Verify ────────────────────────────────────────────────────────────────

async def test_otp_verify_success(client, redis):
    mobile = "+919876543210"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)

    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["mobile_number"] == mobile
    assert data["token_type"] == "bearer"


async def test_otp_verify_wrong_otp(client, redis):
    mobile = "+919876543210"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)

    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "000000"},
    )
    assert response.status_code == 401
    assert "Invalid or expired OTP" in response.json()["detail"]


async def test_otp_verify_expired(client):
    # No OTP stored in Redis → expired
    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": "+919876543210", "otp": "123456"},
    )
    assert response.status_code == 401


async def test_otp_is_one_time_use(client, redis):
    mobile = "+919876543210"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)

    await client.post("/api/v1/auth/otp/verify", json={"mobile_number": mobile, "otp": "123456"})
    # Second use should fail
    response = await client.post("/api/v1/auth/otp/verify", json={"mobile_number": mobile, "otp": "123456"})
    assert response.status_code == 401


async def test_otp_verify_creates_new_user(client, redis, db):
    from sqlalchemy import select
    from app.models import User

    mobile = "+919123456789"
    await redis.set(OTP_KEY.format(mobile), "654321", ex=300)

    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "654321"},
    )
    assert response.status_code == 200

    result = await db.execute(select(User).where(User.mobile_number == mobile))
    user = result.scalar_one_or_none()
    assert user is not None


async def test_otp_verify_returns_existing_user(client, redis, db):
    from app.models import User

    mobile = "+919000000001"
    existing = User(mobile_number=mobile, name="Test User")
    db.add(existing)
    await db.commit()

    await redis.set(OTP_KEY.format(mobile), "111222", ex=300)
    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "111222"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "Test User"


# ── Token Refresh ─────────────────────────────────────────────────────────────

async def test_token_refresh_success(client, redis):
    mobile = "+919876543210"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    verify_resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    refresh_token = verify_resp.json()["refresh_token"]

    response = await client.post("/api/v1/auth/token/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_token_refresh_invalid(client):
    response = await client.post("/api/v1/auth/token/refresh", json={"refresh_token": "bad.token.here"})
    assert response.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────

async def test_logout_blacklists_refresh_token(client, redis):
    mobile = "+919876543210"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    verify_resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    tokens = verify_resp.json()

    logout_resp = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout_resp.status_code == 204

    # Refresh should now fail
    refresh_resp = await client.post(
        "/api/v1/auth/token/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_resp.status_code == 401
