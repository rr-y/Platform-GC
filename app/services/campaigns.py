from datetime import timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, Coupon, CouponRedemption, utcnow


async def validate_coupon(
    code: str,
    user_id: str,
    order_amount: float,
    db: AsyncSession,
) -> tuple[Coupon, float]:
    """
    Validate a coupon code for a user and order amount.
    Returns (coupon, discount_amount) or raises ValueError with reason.
    """
    now = utcnow()

    result = await db.execute(select(Coupon).where(Coupon.code == code.upper()))
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise ValueError("Coupon not found")

    if now < coupon.valid_from or now > coupon.valid_to:
        raise ValueError("Coupon has expired or is not yet active")

    if coupon.max_uses is not None and coupon.uses_count >= coupon.max_uses:
        raise ValueError("Coupon usage limit reached")

    # Per-user limit check
    redemption_count = await db.execute(
        select(CouponRedemption).where(
            CouponRedemption.coupon_id == coupon.id,
            CouponRedemption.user_id == user_id,
        )
    )
    user_uses = len(redemption_count.scalars().all())
    if user_uses >= coupon.per_user_limit:
        raise ValueError("You have already used this coupon")

    # Fetch campaign for discount rules
    campaign = await db.get(Campaign, coupon.campaign_id)
    if not campaign or not campaign.is_active:
        raise ValueError("Campaign is inactive")

    if order_amount < float(campaign.min_order_value):
        raise ValueError(f"Minimum order value ₹{campaign.min_order_value} required")

    discount = _compute_discount(campaign, order_amount)
    return coupon, discount


def _compute_discount(campaign: Campaign, order_amount: float) -> float:
    if campaign.type == "flat":
        return min(float(campaign.discount_value or 0), order_amount)

    if campaign.type == "percentage":
        discount = order_amount * float(campaign.discount_value or 0) / 100
        if campaign.max_discount_cap:
            discount = min(discount, float(campaign.max_discount_cap))
        return round(discount, 2)

    # coins_bonus type — no direct monetary discount
    return 0.0


async def get_available_coupons(user_id: str, order_amount: float, db: AsyncSession) -> list[dict]:
    """Return auto-applicable coupons valid for this user and order amount."""
    now = utcnow()

    result = await db.execute(
        select(Coupon, Campaign)
        .join(Campaign, Coupon.campaign_id == Campaign.id)
        .where(
            Coupon.is_auto_apply == True,
            Coupon.valid_from <= now,
            Coupon.valid_to >= now,
            Campaign.is_active == True,
        )
    )
    rows = result.all()

    available = []
    for coupon, campaign in rows:
        if campaign.min_order_value and order_amount < float(campaign.min_order_value):
            continue
        if coupon.max_uses is not None and coupon.uses_count >= coupon.max_uses:
            continue
        discount = _compute_discount(campaign, order_amount)
        available.append({
            "coupon_id": coupon.id,
            "code": coupon.code,
            "campaign_title": campaign.title,
            "discount_type": campaign.type,
            "discount_value": float(campaign.discount_value or 0),
            "is_auto_apply": True,
        })

    return available
