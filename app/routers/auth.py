import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis

from app.database import get_conn
from app.redis import get_redis
from app.schemas import (
    AccessTokenOut,
    AdminBootstrapIn,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    RefreshIn,
    TokenOut,
    UserOut,
)
from app.services.auth import (
    AuthError,
    RateLimitError,
    get_or_create_user,
    issue_tokens,
    logout,
    refresh_access_token,
    request_otp,
    verify_otp,
)
from app.services.coins import get_balance

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request", response_model=OtpRequestOut)
async def otp_request(
    body: OtpRequestIn,
    redis: Redis = Depends(get_redis),
):
    try:
        await request_otp(body.mobile_number, redis)
    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    from app.config import settings
    return OtpRequestOut(message="OTP sent", expires_in_seconds=settings.OTP_EXPIRE_SECONDS)


@router.post("/otp/verify", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def otp_verify(
    body: OtpVerifyIn,
    conn: asyncpg.Connection = Depends(get_conn),
    redis: Redis = Depends(get_redis),
):
    valid = await verify_otp(body.mobile_number, body.otp, redis)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")

    user = await get_or_create_user(body.mobile_number, conn)
    access_token, refresh_token = await issue_tokens(user, redis)
    balance = await get_balance(user["id"], conn)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut(
            user_id=user["id"],
            mobile_number=user["mobile_number"],
            name=user["name"],
            role=user["role"],
            coin_balance=balance,
        ),
    )


@router.post("/token/refresh", response_model=AccessTokenOut)
async def token_refresh(
    body: RefreshIn,
    conn: asyncpg.Connection = Depends(get_conn),
    redis: Redis = Depends(get_redis),
):
    try:
        access_token = await refresh_access_token(body.refresh_token, redis, conn)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    return AccessTokenOut(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_endpoint(
    body: RefreshIn,
    redis: Redis = Depends(get_redis),
):
    await logout(body.refresh_token, redis)


@router.post("/admin/bootstrap", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def admin_bootstrap(
    body: AdminBootstrapIn,
    conn: asyncpg.Connection = Depends(get_conn),
    redis: Redis = Depends(get_redis),
):
    """
    Create or promote a user to admin role.

    Requires `secret` matching `ADMIN_SECRET_KEY` in server config.
    Set ADMIN_SECRET_KEY in your .env — leave it blank to disable this endpoint.

    Use this once to bootstrap your first admin account, then send OTPs normally.
    """
    from app.config import settings
    if not settings.ADMIN_SECRET_KEY or body.secret != settings.ADMIN_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret")

    # Get or create the user, then ensure admin role
    user = await get_or_create_user(body.mobile_number, conn)
    if user["role"] != "admin":
        await conn.execute(
            "UPDATE users SET role = 'admin' WHERE id = $1", user["id"]
        )
        user = {**user, "role": "admin"}

    access_token, refresh_token = await issue_tokens(user, redis)
    balance = await get_balance(user["id"], conn)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut(
            user_id=user["id"],
            mobile_number=user["mobile_number"],
            name=user["name"],
            role=user["role"],
            coin_balance=balance,
        ),
    )
