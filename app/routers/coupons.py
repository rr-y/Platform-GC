import asyncpg
from fastapi import APIRouter, Depends, Query

from app.database import get_conn
from app.deps import get_current_user
from app.schemas import AvailableOffer, CouponValidateIn, CouponValidateOut
from app.services.campaigns import get_available_coupons, validate_coupon

router = APIRouter(prefix="/coupons", tags=["coupons"])


@router.post("/validate", response_model=CouponValidateOut)
async def coupon_validate(
    body: CouponValidateIn,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        coupon, discount_amount = await validate_coupon(
            body.code, current_user["id"], body.order_amount, conn
        )
    except ValueError as e:
        return CouponValidateOut(valid=False, campaign_title=str(e))

    campaign = await conn.fetchrow(
        "SELECT type, discount_value, title FROM campaigns WHERE id = $1",
        coupon["campaign_id"],
    )
    return CouponValidateOut(
        valid=True,
        coupon_id=coupon["id"],
        discount_type=campaign["type"] if campaign else None,
        discount_value=float(campaign["discount_value"] or 0) if campaign else None,
        discount_amount=discount_amount,
        campaign_title=campaign["title"] if campaign else None,
    )


@router.get("/available", response_model=list[AvailableOffer])
async def available_coupons(
    order_amount: float = Query(0.0, ge=0),
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    offers = await get_available_coupons(current_user["id"], order_amount, conn)
    return [AvailableOffer(**o) for o in offers]
