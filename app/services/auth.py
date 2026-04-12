import hmac
import logging
import secrets
from datetime import timedelta

import asyncpg
from redis.asyncio import Redis

from app.config import settings
from app.models import new_uuid, utcnow
from app.utils.security import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)

OTP_KEY = "otp:{}"
OTP_REQ_COUNT_KEY = "otp_req_count:{}"
REFRESH_KEY = "refresh:{}"


# ── OTP ───────────────────────────────────────────────────────────────────────

async def request_otp(mobile: str, redis: Redis) -> None:
    """Generate OTP, enforce rate limit, store in Redis, send via Twilio."""
    count_key = OTP_REQ_COUNT_KEY.format(mobile)
    count = await redis.get(count_key)
    if count and int(count) >= settings.OTP_MAX_REQUESTS:
        ttl = await redis.ttl(count_key)
        raise RateLimitError(f"Too many OTP requests. Try after {ttl} seconds.")

    otp = str(secrets.randbelow(1_000_000)).zfill(6)
    await redis.set(OTP_KEY.format(mobile), otp, ex=settings.OTP_EXPIRE_SECONDS)

    pipe = redis.pipeline()
    pipe.incr(count_key)
    pipe.expire(count_key, settings.OTP_RATE_WINDOW_SECONDS)
    await pipe.execute()

    try:
        from app.services.notifications import send_otp
        await send_otp(mobile, otp)
    except Exception as e:
        logger.error("OTP send failed for %s: %s", mobile, e)


async def verify_otp(mobile: str, otp: str, redis: Redis) -> bool:
    stored = await redis.get(OTP_KEY.format(mobile))
    if not stored:
        return False
    if not hmac.compare_digest(stored, otp):
        return False
    await redis.delete(OTP_KEY.format(mobile))
    return True


# ── User ──────────────────────────────────────────────────────────────────────

async def get_or_create_user(mobile: str, conn: asyncpg.Connection) -> dict:
    row = await conn.fetchrow(
        "SELECT id, mobile_number, name, role, is_active FROM users WHERE mobile_number = $1",
        mobile,
    )
    if row:
        return dict(row)

    uid = new_uuid()
    await conn.execute(
        """INSERT INTO users (id, mobile_number, role, is_active, created_at)
           VALUES ($1, $2, 'user', true, $3)""",
        uid, mobile, utcnow(),
    )
    logger.info("New user created: %s", uid)
    return {"id": uid, "mobile_number": mobile, "name": None, "role": "user", "is_active": True}


# ── JWT ───────────────────────────────────────────────────────────────────────

async def issue_tokens(user: dict, redis: Redis) -> tuple[str, str]:
    access_token = create_access_token(user["id"], user["role"])
    refresh_token, jti = create_refresh_token(user["id"])
    ttl = int(timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())
    await redis.set(REFRESH_KEY.format(jti), user["id"], ex=ttl)
    return access_token, refresh_token


async def refresh_access_token(refresh_token: str, redis: Redis, conn: asyncpg.Connection) -> str:
    from app.utils.security import decode_token
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token")

    jti = payload.get("jti")
    user_id = await redis.get(REFRESH_KEY.format(jti))
    if not user_id:
        raise AuthError("Refresh token expired or revoked")

    row = await conn.fetchrow(
        "SELECT id, role FROM users WHERE id = $1 AND is_active = true", user_id
    )
    if not row:
        raise AuthError("User not found")

    return create_access_token(row["id"], row["role"])


async def logout(refresh_token: str, redis: Redis) -> None:
    from app.utils.security import decode_token
    payload = decode_token(refresh_token)
    if payload and payload.get("jti"):
        await redis.delete(REFRESH_KEY.format(payload["jti"]))


# ── Exceptions ────────────────────────────────────────────────────────────────

class RateLimitError(Exception):
    pass


class AuthError(Exception):
    pass
