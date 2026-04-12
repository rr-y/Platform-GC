from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_admin
from app.models import Campaign, Coupon, User, utcnow
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
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    campaign = Campaign(
        title=body.title,
        type=body.type,
        discount_value=body.discount_value,
        min_order_value=body.min_order_value,
        max_discount_cap=body.max_discount_cap,
        valid_from=datetime.fromisoformat(body.valid_from),
        valid_to=datetime.fromisoformat(body.valid_to),
        audience_type=body.audience_type,
        usage_limit=body.usage_limit,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return _campaign_out(campaign)


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    active_only: bool = Query(False),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(Campaign)
    if active_only:
        query = query.where(Campaign.is_active == True)
    result = await db.execute(query.order_by(Campaign.created_at.desc()))
    return [_campaign_out(c) for c in result.scalars().all()]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return _campaign_out(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: str,
    body: dict,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    allowed = {"title", "discount_value", "min_order_value", "max_discount_cap",
               "valid_from", "valid_to", "is_active", "audience_type", "usage_limit"}
    for key, value in body.items():
        if key in allowed:
            if key in ("valid_from", "valid_to") and isinstance(value, str):
                value = datetime.fromisoformat(value)
            setattr(campaign, key, value)

    await db.commit()
    await db.refresh(campaign)
    return _campaign_out(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_campaign(
    campaign_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    campaign.is_active = False
    await db.commit()


@router.post("/campaigns/{campaign_id}/notify", status_code=status.HTTP_202_ACCEPTED)
async def blast_campaign_notification(
    campaign_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Trigger notification blast to campaign audience."""
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    from app.services.notifications import send_campaign_message
    result = await db.execute(select(User).where(User.is_active == True))
    users = result.scalars().all()

    sent = 0
    for user in users:
        try:
            msg = f"🎉 {campaign.title} — Don't miss out! Valid till {campaign.valid_to.strftime('%d %b %Y')}."
            await send_campaign_message(user.mobile_number, campaign.title, msg)
            sent += 1
        except Exception:
            pass

    return {"message": f"Notification dispatched to {sent} users"}


@router.post("/campaigns/{campaign_id}/coupons", status_code=status.HTTP_201_CREATED)
async def add_coupons(
    campaign_id: str,
    body: CouponAddIn,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    created = []
    for code in body.codes:
        coupon = Coupon(
            campaign_id=campaign_id,
            code=code.upper().strip(),
            is_auto_apply=body.is_auto_apply,
            max_uses=body.max_uses,
            per_user_limit=body.per_user_limit,
            valid_from=campaign.valid_from,
            valid_to=campaign.valid_to,
        )
        db.add(coupon)
        created.append(code.upper().strip())

    await db.commit()
    return {"created": created, "count": len(created)}


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    query = select(User)
    if search:
        query = query.where(User.mobile_number.contains(search))
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    out = []
    for u in users:
        balance = await get_balance(u.id, db)
        out.append(UserAdminOut(
            user_id=u.id,
            mobile_number=u.mobile_number,
            name=u.name,
            role=u.role,
            is_active=u.is_active,
            coin_balance=balance,
            created_at=u.created_at.isoformat(),
        ))
    return out


@router.get("/users/{user_id}", response_model=UserAdminOut)
async def get_user(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    balance = await get_balance(user.id, db)
    return UserAdminOut(
        user_id=user.id,
        mobile_number=user.mobile_number,
        name=user.name,
        role=user.role,
        is_active=user.is_active,
        coin_balance=balance,
        created_at=user.created_at.isoformat(),
    )


@router.post("/users/{user_id}/coins/adjust", status_code=status.HTTP_200_OK)
async def adjust_coins(
    user_id: str,
    body: CoinAdjustIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if body.coins == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Coins must be non-zero")

    from app.models import CoinsLedger
    from datetime import timedelta
    now = utcnow()

    entry = CoinsLedger(
        user_id=user_id,
        coins=body.coins,
        type="adjusted",
        status="active",
        reference_id=admin.id,
        issued_at=now,
        expiry_at=now + timedelta(days=36500) if body.coins < 0 else now + timedelta(days=365),
        redeemable_after=now,
    )
    db.add(entry)
    await db.commit()

    balance = await get_balance(user_id, db)
    return {"user_id": user_id, "adjustment": body.coins, "balance_after": balance}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _campaign_out(c: Campaign) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        title=c.title,
        type=c.type,
        discount_value=float(c.discount_value) if c.discount_value else None,
        min_order_value=float(c.min_order_value),
        max_discount_cap=float(c.max_discount_cap) if c.max_discount_cap else None,
        valid_from=c.valid_from.isoformat(),
        valid_to=c.valid_to.isoformat(),
        is_active=c.is_active,
        audience_type=c.audience_type,
        usage_limit=c.usage_limit,
        usage_count=c.usage_count,
    )
