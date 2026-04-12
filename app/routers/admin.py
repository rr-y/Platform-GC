import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_conn
from app.deps import require_admin
from app.models import new_uuid, utcnow
from app.schemas import (
    CampaignIn,
    CampaignOut,
    CoinAdjustIn,
    CouponAddIn,
    UserAdminOut,
)
from app.services.coins import award_coins, get_balance

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
            msg = f"🎉 {campaign['title']} — Don't miss out! Valid till {campaign['valid_to'].strftime('%d %b %Y')}."
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
