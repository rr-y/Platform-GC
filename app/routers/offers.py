import asyncpg
from fastapi import APIRouter, Depends

from app.database import get_conn
from app.deps import get_current_user
from app.schemas import OfferBannerItem
from app.services.campaigns import get_offer_banners

router = APIRouter(tags=["offers"])


@router.get("/users/me/offers", response_model=list[OfferBannerItem])
async def list_offer_banners(
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """
    Returns active offer banners visible to the current user.
    Respects audience_type cohort targeting (all / specific_users / has_coins / new_users).
    Max 10 items ordered by soonest expiry.
    """
    banners = await get_offer_banners(current_user["id"], conn)
    return banners
