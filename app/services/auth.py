import hmac
import logging
import secrets
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import NotificationLog, User, utcnow
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

    # Send OTP asynchronously (fire and forget — don't block API response)
    try:
        from app.services.notifications import send_otp
        await send_otp(mobile, otp)
    except Exception as e:
        logger.error("OTP send failed for %s: %s", mobile, e)
        # Don't raise — OTP is stored, user can retry sending


async def verify_otp(mobile: str, otp: str, redis: Redis) -> bool:
    """Verify OTP from Redis. Returns True on success, False on failure."""
    stored = await redis.get(OTP_KEY.format(mobile))
    if not stored:
        return False
    if not hmac.compare_digest(stored, otp):
        return False
    await redis.delete(OTP_KEY.format(mobile))
    return True


# ── User upsert ───────────────────────────────────────────────────────────────

async def get_or_create_user(mobile: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.mobile_number == mobile))
    user = result.scalar_one_or_none()
    if not user:
        user = User(mobile_number=mobile)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("New user created: %s", user.id)
    return user


# ── JWT ───────────────────────────────────────────────────────────────────────

async def issue_tokens(user: User, redis: Redis) -> tuple[str, str]:
    """Issue access + refresh tokens. Stores refresh JTI in Redis."""
    access_token = create_access_token(user.id, user.role)
    refresh_token, jti = create_refresh_token(user.id)
    ttl = int(timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())
    await redis.set(REFRESH_KEY.format(jti), user.id, ex=ttl)
    return access_token, refresh_token


async def refresh_access_token(refresh_token: str, redis: Redis, db: AsyncSession) -> str:
    """Validate refresh token, return new access token."""
    from app.utils.security import decode_token
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token")

    jti = payload.get("jti")
    user_id = await redis.get(REFRESH_KEY.format(jti))
    if not user_id:
        raise AuthError("Refresh token expired or revoked")

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise AuthError("User not found")

    return create_access_token(user.id, user.role)


async def logout(refresh_token: str, redis: Redis) -> None:
    """Blacklist refresh token by deleting its JTI from Redis."""
    from app.utils.security import decode_token
    payload = decode_token(refresh_token)
    if payload and payload.get("jti"):
        await redis.delete(REFRESH_KEY.format(payload["jti"]))


# ── Exceptions ────────────────────────────────────────────────────────────────

class RateLimitError(Exception):
    pass


class AuthError(Exception):
    pass
