from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.models import new_uuid
from app.services.auth import OTP_KEY, OTP_REQ_COUNT_KEY


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
    assert response.status_code == 201
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


async def test_otp_verify_creates_new_user(client, conn, redis):
    mobile = "+919123456789"
    await redis.set(OTP_KEY.format(mobile), "654321", ex=300)

    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "654321"},
    )
    assert response.status_code == 201

    row = await conn.fetchrow("SELECT id FROM users WHERE mobile_number = $1", mobile)
    assert row is not None


async def test_otp_verify_returns_existing_user(client, conn, redis):
    mobile = "+919000000001"
    uid = new_uuid()
    await conn.execute(
        "INSERT INTO users (id, mobile_number, name, role, is_active, created_at) VALUES ($1,$2,'Test User','user',true,NOW())",
        uid, mobile,
    )

    await redis.set(OTP_KEY.format(mobile), "111222", ex=300)
    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "111222"},
    )
    assert response.status_code == 201
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

# ── Play Store / App Store review credentials ────────────────────────────────

REVIEW_MOBILE = "+919999999999"
REVIEW_OTP = "123456"


@pytest.fixture
def review_creds(monkeypatch):
    monkeypatch.setattr(settings, "TEST_MOBILE_NUMBER", REVIEW_MOBILE)
    monkeypatch.setattr(settings, "TEST_OTP", REVIEW_OTP)


async def test_review_mobile_request_skips_sms_and_redis(client, redis, review_creds):
    with patch("app.services.notifications.send_otp", new_callable=AsyncMock) as send:
        response = await client.post(
            "/api/v1/auth/otp/request", json={"mobile_number": "9999999999"}
        )
    assert response.status_code == 200
    send.assert_not_called()
    assert await redis.get(OTP_KEY.format(REVIEW_MOBILE)) is None
    assert await redis.get(OTP_REQ_COUNT_KEY.format(REVIEW_MOBILE)) is None


async def test_review_mobile_request_bypasses_rate_limit(client, redis, review_creds):
    with patch("app.services.notifications.send_otp", new_callable=AsyncMock):
        for _ in range(10):
            response = await client.post(
                "/api/v1/auth/otp/request", json={"mobile_number": REVIEW_MOBILE}
            )
            assert response.status_code == 200


async def test_review_otp_verify_success(client, review_creds):
    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": "9999999999", "otp": REVIEW_OTP},
    )
    assert response.status_code == 201
    assert response.json()["user"]["mobile_number"] == REVIEW_MOBILE


async def test_review_otp_verify_rejects_wrong_otp(client, review_creds):
    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": REVIEW_MOBILE, "otp": "000000"},
    )
    assert response.status_code == 401


async def test_review_bypass_disabled_by_default(client, redis):
    # With TEST_* unset, the review mobile follows the normal flow: request
    # stores a random OTP in Redis, and the fixed OTP 123456 does not verify.
    with patch("app.services.notifications.send_otp", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/otp/request", json={"mobile_number": REVIEW_MOBILE}
        )
    stored = await redis.get(OTP_KEY.format(REVIEW_MOBILE))
    assert stored is not None and stored != REVIEW_OTP

    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": REVIEW_MOBILE, "otp": REVIEW_OTP},
    )
    assert response.status_code == 401


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
