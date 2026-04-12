import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def expire_coins() -> None:
    """Bulk-expire coins past their expiry_at timestamp."""
    from app.database import get_pool
    async with get_pool().acquire() as conn:
        result = await conn.execute(
            """UPDATE coins_ledger
               SET status = 'expired'
               WHERE status = 'active'
                 AND type = 'earned'
                 AND expiry_at <= NOW()"""
        )
        # asyncpg returns "UPDATE N" as a string
        count = int(result.split()[-1])
        logger.info("expire_coins: expired %d rows", count)


async def send_expiry_notifications() -> None:
    """Find users with coins expiring soon and send notifications."""
    from datetime import timedelta
    from app.config import settings
    from app.database import get_pool
    from app.services.notifications import dispatch_expiry_notification

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT user_id
               FROM coins_ledger
               WHERE status = 'active'
                 AND type = 'earned'
                 AND expiry_at > NOW()
                 AND expiry_at <= NOW() + $1::interval""",
            timedelta(days=settings.EXPIRY_NOTIFY_DAYS),
        )
        user_ids = [r["user_id"] for r in rows]

    for user_id in user_ids:
        try:
            await dispatch_expiry_notification(user_id)
        except Exception as e:
            logger.error("Failed to send expiry notification to %s: %s", user_id, e)

    logger.info("send_expiry_notifications: notified %d users", len(user_ids))
