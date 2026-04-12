import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _twilio_client():
    from twilio.rest import Client
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


async def send_otp(mobile: str, otp: str) -> None:
    """Send OTP via WhatsApp (preferred) with SMS fallback."""
    message = f"Your OTP is {otp}. Valid for {settings.OTP_EXPIRE_SECONDS // 60} minutes. Do not share."

    if settings.TWILIO_WHATSAPP_FROM:
        try:
            await _send_whatsapp(mobile, message)
            return
        except Exception as e:
            logger.warning("WhatsApp OTP failed for %s, falling back to SMS: %s", mobile, e)

    await _send_sms(mobile, message)


async def _send_whatsapp(mobile: str, message: str) -> None:
    client = _twilio_client()
    client.messages.create(
        body=message,
        from_=settings.TWILIO_WHATSAPP_FROM,
        to=f"whatsapp:{mobile}",
    )
    logger.info("WhatsApp sent to %s", mobile)


async def _send_sms(mobile: str, message: str) -> None:
    client = _twilio_client()
    client.messages.create(
        body=message,
        from_=settings.TWILIO_FROM_NUMBER,
        to=mobile,
    )
    logger.info("SMS sent to %s", mobile)


async def send_expiry_reminder(mobile: str, coins: int, expiry_date: str) -> None:
    """Send coin expiry reminder via WhatsApp/SMS."""
    message = (
        f"Hi! Your {coins} reward coins expire on {expiry_date}. "
        f"Use them on your next purchase before they expire!"
    )
    if settings.TWILIO_WHATSAPP_FROM:
        try:
            await _send_whatsapp(mobile, message)
            return
        except Exception as e:
            logger.warning("WhatsApp expiry reminder failed for %s: %s", mobile, e)
    await _send_sms(mobile, message)


async def send_campaign_message(mobile: str, title: str, message_body: str) -> None:
    """Send campaign/offer notification."""
    if settings.TWILIO_WHATSAPP_FROM:
        try:
            await _send_whatsapp(mobile, message_body)
            return
        except Exception as e:
            logger.warning("WhatsApp campaign message failed for %s: %s", mobile, e)
    await _send_sms(mobile, message_body)


async def dispatch_expiry_notification(user_id: str) -> None:
    """Send coins expiry reminder to a user. Called by APScheduler job."""
    from datetime import timezone
    from sqlalchemy import func, select
    from app.database import AsyncSessionLocal
    from app.models import CoinsLedger, User, utcnow

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return

        now = utcnow()
        from datetime import timedelta
        window = now + timedelta(days=settings.EXPIRY_NOTIFY_DAYS)

        coins_result = await db.execute(
            select(func.sum(CoinsLedger.coins), func.min(CoinsLedger.expiry_at))
            .where(
                CoinsLedger.user_id == user_id,
                CoinsLedger.status == "active",
                CoinsLedger.type == "earned",
                CoinsLedger.expiry_at > now,
                CoinsLedger.expiry_at <= window,
            )
        )
        row = coins_result.one()
        total_expiring, earliest_expiry = row

        if not total_expiring or total_expiring <= 0:
            return

        expiry_str = earliest_expiry.strftime("%d %b %Y")
        try:
            await send_expiry_reminder(user.mobile_number, total_expiring, expiry_str)
            from app.models import NotificationLog
            log = NotificationLog(
                user_id=user_id,
                channel="whatsapp" if settings.TWILIO_WHATSAPP_FROM else "sms",
                type="coins_expiry",
                status="sent",
            )
            db.add(log)
            await db.commit()
        except Exception as e:
            logger.error("Expiry notification failed for user %s: %s", user_id, e)
            from app.models import NotificationLog
            log = NotificationLog(
                user_id=user_id,
                channel="sms",
                type="coins_expiry",
                status="failed",
                error_detail=str(e),
            )
            db.add(log)
            await db.commit()
