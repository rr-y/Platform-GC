import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis

from app.database import get_conn
from app.deps import require_admin
from app.models import new_uuid, utcnow
from app.redis import get_redis
from app.schemas import (
    AdminCheckoutIn,
    AdminCheckoutOut,
    AdminCustomerLookupIn,
    AdminCustomerLookupOut,
    AdminInviteIn,
    AdminInviteOut,
    CampaignIn,
    CampaignOut,
    CoinAdjustIn,
    CouponAddIn,
    UserAdminOut,
)
from app.services.coins import award_coins, get_balance
from app.templates import messages

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Campaigns ─────────────────────────────────────────────────────────────────

@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignIn,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    cid = new_uuid()
    await conn.execute(
        """INSERT INTO campaigns
               (id, title, type, discount_value, min_order_value, max_discount_cap,
                valid_from, valid_to, is_active, audience_type, usage_limit, usage_count, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9,$10,0,$11)""",
        cid, body.title, body.type, body.discount_value,
        body.min_order_value or 0, body.max_discount_cap,
        body.valid_from, body.valid_to,
        body.audience_type, body.usage_limit, utcnow(),
    )
    row = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", cid)
    return _campaign_out(row)


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    active_only: bool = Query(False),
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    sql = "SELECT * FROM campaigns"
    if active_only:
        sql += " WHERE is_active = true"
    sql += " ORDER BY created_at DESC"
    rows = await conn.fetch(sql)
    return [_campaign_out(r) for r in rows]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: str,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return _campaign_out(row)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: str,
    body: dict,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow("SELECT id FROM campaigns WHERE id = $1", campaign_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    allowed = {"title", "discount_value", "min_order_value", "max_discount_cap",
               "valid_from", "valid_to", "is_active", "audience_type", "usage_limit"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        row = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
        return _campaign_out(row)

    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
    await conn.execute(
        f"UPDATE campaigns SET {set_clause} WHERE id = $1",
        campaign_id, *updates.values(),
    )
    row = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
    return _campaign_out(row)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_campaign(
    campaign_id: str,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow("SELECT id FROM campaigns WHERE id = $1", campaign_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    await conn.execute("UPDATE campaigns SET is_active = false WHERE id = $1", campaign_id)


@router.post("/campaigns/{campaign_id}/notify", status_code=status.HTTP_202_ACCEPTED)
async def blast_campaign_notification(
    campaign_id: str,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    campaign = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    from app.services.notifications import send_campaign_message
    users = await conn.fetch("SELECT mobile_number FROM users WHERE is_active = true")

    sent = 0
    for user in users:
        try:
            msg = messages.campaign_blast(
                campaign["title"], campaign["valid_to"].strftime("%d %b %Y")
            )
            await send_campaign_message(user["mobile_number"], campaign["title"], msg)
            sent += 1
        except Exception:
            pass

    return {"message": f"Notification dispatched to {sent} users"}


@router.post("/campaigns/{campaign_id}/coupons", status_code=status.HTTP_201_CREATED)
async def add_coupons(
    campaign_id: str,
    body: CouponAddIn,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    campaign = await conn.fetchrow(
        "SELECT id, valid_from, valid_to FROM campaigns WHERE id = $1", campaign_id
    )
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    created = []
    for code in body.codes:
        code_upper = code.upper().strip()
        await conn.execute(
            """INSERT INTO coupons
                   (id, campaign_id, code, is_auto_apply, max_uses, uses_count, per_user_limit, valid_from, valid_to)
               VALUES ($1,$2,$3,$4,$5,0,$6,$7,$8)""",
            new_uuid(), campaign_id, code_upper, body.is_auto_apply,
            body.max_uses, body.per_user_limit,
            campaign["valid_from"], campaign["valid_to"],
        )
        created.append(code_upper)

    return {"created": created, "count": len(created)}


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    offset = (page - 1) * limit
    if search:
        rows = await conn.fetch(
            "SELECT * FROM users WHERE mobile_number LIKE $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            f"%{search}%", limit, offset,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )

    result = []
    for u in rows:
        balance = await get_balance(u["id"], conn)
        result.append(UserAdminOut(
            user_id=u["id"],
            mobile_number=u["mobile_number"],
            name=u["name"],
            role=u["role"],
            is_active=u["is_active"],
            coin_balance=balance,
            created_at=u["created_at"].isoformat(),
        ))
    return result


@router.get("/users/{user_id}", response_model=UserAdminOut)
async def get_user(
    user_id: str,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    balance = await get_balance(row["id"], conn)
    return UserAdminOut(
        user_id=row["id"],
        mobile_number=row["mobile_number"],
        name=row["name"],
        role=row["role"],
        is_active=row["is_active"],
        coin_balance=balance,
        created_at=row["created_at"].isoformat(),
    )


@router.post("/users/{user_id}/coins/adjust", status_code=status.HTTP_200_OK)
async def adjust_coins(
    user_id: str,
    body: CoinAdjustIn,
    admin: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if body.coins == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Coins must be non-zero")

    from datetime import timedelta
    now = utcnow()
    expiry = now + timedelta(days=36500) if body.coins < 0 else now + timedelta(days=365)

    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
           VALUES ($1,$2,$3,'adjusted','active',$4,$5,$6,$7)""",
        new_uuid(), user_id, body.coins, admin["id"], now, expiry, now,
    )
    balance = await get_balance(user_id, conn)
    return {"user_id": user_id, "adjustment": body.coins, "balance_after": balance}


# ── Checkout ──────────────────────────────────────────────────────────────────

@router.post("/customers/invite", response_model=AdminInviteOut)
async def customer_invite(
    body: AdminInviteIn,
    _: dict = Depends(require_admin),
    redis: Redis = Depends(get_redis),
):
    """
    Admin-initiated onboarding for walk-in customers.

    Sends an OTP to the customer's phone. The admin then asks the customer
    for the code and calls `/auth/otp/verify` to create the user and log them
    in. Useful when enrolling a new customer at the shop counter before they
    have downloaded the app.
    """
    from app.config import settings
    from app.services.auth import RateLimitError, request_otp

    try:
        await request_otp(body.mobile_number, redis)
    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    return AdminInviteOut(
        message="OTP sent to customer",
        mobile_number=body.mobile_number,
        expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
    )


@router.post("/customers/lookup", response_model=AdminCustomerLookupOut)
async def customer_lookup(
    body: AdminCustomerLookupIn,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """
    Step 1 of admin checkout.

    Enter the customer's mobile number and the bill amount.
    Returns their coin balance, any coins expiring soon, and applicable offers
    so the admin can decide what to apply before confirming payment.
    """
    from math import floor
    from app.config import settings
    from app.services.campaigns import get_available_coupons
    from app.services.coins import get_expiring_soon

    user = await conn.fetchrow(
        "SELECT id, mobile_number, name FROM users WHERE mobile_number = $1",
        body.mobile_number,
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    balance = await get_balance(user["id"], conn)
    expiring = await get_expiring_soon(user["id"], conn)
    offers = await get_available_coupons(user["id"], body.amount, conn)

    max_redeemable = floor(body.amount * settings.MAX_COINS_REDEEM_PERCENT / settings.COIN_RUPEE_VALUE)
    max_redeemable = min(max_redeemable, balance)

    from app.schemas import AvailableOffer, ExpiringSoon
    return AdminCustomerLookupOut(
        user_id=user["id"],
        name=user["name"],
        mobile_number=user["mobile_number"],
        coin_balance=balance,
        expiring_soon=ExpiringSoon(
            coins=expiring["coins"], expiry_at=expiring["expiry_at"]
        ) if expiring else None,
        applicable_offers=[AvailableOffer(**o) for o in offers],
        max_redeemable_coins=max_redeemable,
        max_redeemable_value=round(max_redeemable * settings.COIN_RUPEE_VALUE, 2),
    )


@router.post("/checkout", response_model=AdminCheckoutOut, status_code=status.HTTP_201_CREATED)
async def admin_checkout(
    body: AdminCheckoutIn,
    _: dict = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """
    Step 2 of admin checkout.

    Confirm the payment. Optionally pass coins_to_redeem and/or coupon_code
    from the lookup step. Creates the transaction, awards/redeems coins, and
    sends the customer a WhatsApp/SMS summary.
    """
    import logging
    from app.services.transactions import create_transaction
    from app.services.notifications import send_transaction_notification

    logger = logging.getLogger(__name__)

    user = await conn.fetchrow(
        "SELECT id, mobile_number, name FROM users WHERE mobile_number = $1",
        body.mobile_number,
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    txn = await create_transaction(
        user_id=user["id"],
        amount=body.amount,
        conn=conn,
        coins_to_redeem=body.coins_to_redeem,
        coupon_code=body.coupon_code,
    )

    notification_sent = False
    try:
        await send_transaction_notification(
            mobile=user["mobile_number"],
            name=user["name"],
            final_amount=txn["final_amount"],
            coins_earned=txn["coins_earned"],
            coins_redeemed=txn["coins_redeemed"],
            coins_redeemed_value=txn["coins_redeemed_value"],
            balance=txn["coins_balance_after"],
        )
        notification_sent = True
    except Exception as e:
        logger.warning("Transaction notification failed for %s: %s", user["mobile_number"], e)

    return AdminCheckoutOut(**txn, notification_sent=notification_sent)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _campaign_out(row) -> CampaignOut:
    return CampaignOut(
        id=row["id"],
        title=row["title"],
        type=row["type"],
        discount_value=float(row["discount_value"]) if row["discount_value"] else None,
        min_order_value=float(row["min_order_value"]),
        max_discount_cap=float(row["max_discount_cap"]) if row["max_discount_cap"] else None,
        valid_from=row["valid_from"].isoformat(),
        valid_to=row["valid_to"].isoformat(),
        is_active=row["is_active"],
        audience_type=row["audience_type"],
        usage_limit=row["usage_limit"],
        usage_count=row["usage_count"],
    )
