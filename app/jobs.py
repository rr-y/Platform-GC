import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import CoinsLedger, User

logger = logging.getLogger(__name__)


async def expire_coins() -> None:
    """Bulk-expire coins past their expiry_at timestamp."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(CoinsLedger)
            .where(
                CoinsLedger.status == "active",
                CoinsLedger.type == "earned",
                CoinsLedger.expiry_at <= now,
            )
            .values(status="expired")
        )
        await db.commit()
        logger.info("expire_coins: expired %d rows", result.rowcount)


async def send_expiry_notifications() -> None:
    """Find users with coins expiring soon and send notifications."""
    from datetime import timedelta

    from app.config import settings
    from app.services.notifications import dispatch_expiry_notification

    now = datetime.now(timezone.utc)
    notify_before = now + timedelta(days=settings.EXPIRY_NOTIFY_DAYS)

    async with AsyncSessionLocal() as db:
        # Find distinct users who have active coins expiring within the window
        result = await db.execute(
            select(CoinsLedger.user_id)
            .where(
                CoinsLedger.status == "active",
                CoinsLedger.type == "earned",
                CoinsLedger.expiry_at > now,
                CoinsLedger.expiry_at <= notify_before,
            )
            .distinct()
        )
        user_ids = result.scalars().all()

    for user_id in user_ids:
        try:
            await dispatch_expiry_notification(user_id)
        except Exception as e:
            logger.error("Failed to send expiry notification to %s: %s", user_id, e)

    logger.info("send_expiry_notifications: notified %d users", len(user_ids))
