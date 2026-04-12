from datetime import timezone
from math import floor

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import CoinsLedger, utcnow


async def get_balance(user_id: str, db: AsyncSession) -> int:
    """Return net active coin balance (earned - redeemed, non-expired)."""
    now = utcnow()
    result = await db.execute(
        select(func.coalesce(func.sum(CoinsLedger.coins), 0)).where(
            CoinsLedger.user_id == user_id,
            CoinsLedger.status == "active",
            CoinsLedger.expiry_at > now,
        )
    )
    return int(result.scalar())


async def award_coins(
    user_id: str,
    coins: int,
    reference_id: str,
    db: AsyncSession,
) -> CoinsLedger:
    """Create an earned coins ledger entry. redeemable_after = now+1s (blocks same-txn redeem)."""
    from datetime import timedelta
    now = utcnow()
    entry = CoinsLedger(
        user_id=user_id,
        coins=coins,
        type="earned",
        status="active",
        reference_id=reference_id,
        issued_at=now,
        expiry_at=now + timedelta(days=settings.COINS_EXPIRY_DAYS),
        redeemable_after=now + timedelta(seconds=1),
    )
    db.add(entry)
    return entry


async def redeem_coins(
    user_id: str,
    coins: int,
    transaction_id: str,
    txn_start: object,
    db: AsyncSession,
) -> None:
    """Insert a negative ledger row to record redemption. Validates balance first."""
    now = utcnow()

    # Only count coins that were issued before this transaction started
    result = await db.execute(
        select(func.coalesce(func.sum(CoinsLedger.coins), 0)).where(
            CoinsLedger.user_id == user_id,
            CoinsLedger.status == "active",
            CoinsLedger.expiry_at > now,
            CoinsLedger.redeemable_after < txn_start,
        )
    )
    available = int(result.scalar())

    if coins > available:
        raise InsufficientCoinsError(f"Only {available} coins available for redemption")

    from datetime import timedelta
    entry = CoinsLedger(
        user_id=user_id,
        coins=-coins,
        type="redeemed",
        status="active",         # stays active so SUM includes negative value
        reference_id=transaction_id,
        issued_at=now,
        expiry_at=now + timedelta(days=36500),  # far future — never expires
        redeemable_after=now,
    )
    db.add(entry)


async def get_expiring_soon(user_id: str, db: AsyncSession) -> dict | None:
    """Return total coins and earliest expiry within the notification window."""
    from datetime import timedelta
    now = utcnow()
    window = now + timedelta(days=settings.EXPIRY_NOTIFY_DAYS)

    result = await db.execute(
        select(
            func.coalesce(func.sum(CoinsLedger.coins), 0),
            func.min(CoinsLedger.expiry_at),
        ).where(
            CoinsLedger.user_id == user_id,
            CoinsLedger.status == "active",
            CoinsLedger.type == "earned",
            CoinsLedger.expiry_at > now,
            CoinsLedger.expiry_at <= window,
        )
    )
    row = result.one()
    total, earliest = row
    if not total or total <= 0:
        return None
    return {"coins": int(total), "expiry_at": earliest.isoformat()}


class InsufficientCoinsError(Exception):
    pass
