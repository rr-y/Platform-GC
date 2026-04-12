from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import AvailableOffer, CouponValidateIn, CouponValidateOut
from app.services.campaigns import get_available_coupons, validate_coupon

router = APIRouter(prefix="/coupons", tags=["coupons"])


@router.post("/validate", response_model=CouponValidateOut)
async def coupon_validate(
    body: CouponValidateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        coupon, discount_amount = await validate_coupon(
            body.code, current_user.id, body.order_amount, db
        )
    except ValueError as e:
        return CouponValidateOut(valid=False, campaign_title=str(e))

    from app.models import Campaign
    campaign = await db.get(Campaign, coupon.campaign_id)
    return CouponValidateOut(
        valid=True,
        coupon_id=coupon.id,
        discount_type=campaign.type if campaign else None,
        discount_value=float(campaign.discount_value or 0) if campaign else None,
        discount_amount=discount_amount,
        campaign_title=campaign.title if campaign else None,
    )


@router.get("/available", response_model=list[AvailableOffer])
async def available_coupons(
    order_amount: float = Query(0.0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offers = await get_available_coupons(current_user.id, order_amount, db)
    return [AvailableOffer(**o) for o in offers]
