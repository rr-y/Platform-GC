import logging
from datetime import timedelta

from app.config import settings
from app.models import new_uuid, utcnow
from app.services.push import send_push
from app.templates import messages

logger = logging.getLogger(__name__)


def _twilio_client():
    from twilio.rest import Client
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


async def send_otp(mobile: str, otp: str) -> None:
    """Send OTP via SMS. Must stay SMS — pre-login, no push token yet."""
    await _send_sms(mobile, messages.otp_message(otp))


async def _send_sms(mobile: str, message: str) -> None:
    client = _twilio_client()
    client.messages.create(
        body=message,
        from_=settings.TWILIO_FROM_NUMBER,
        to=mobile,
    )
    logger.info("SMS sent to %s", mobile)


async def _send_push_or_sms(
    push_token: str | None,
    mobile: str,
    title: str,
    body: str,
) -> str:
    """
    Try push first when a token exists; fall back to SMS on any failure or
    when there is no token. Returns the channel actually used ("push" or "sms").
    """
    if push_token:
        if await send_push(push_token, title, body):
            return "push"
        logger.info("Push failed for %s, falling back to SMS", mobile)
    await _send_sms(mobile, body)
    return "sms"


async def send_expiry_reminder(
    mobile: str,
    coins: int,
    expiry_date: str,
    push_token: str | None = None,
) -> str:
    body = messages.expiry_reminder(coins, expiry_date)
    return await _send_push_or_sms(push_token, mobile, "Coins Expiring Soon", body)


async def send_campaign_message(mobile: str, title: str, message_body: str) -> None:
    await _send_sms(mobile, message_body)


async def send_transaction_notification(
    mobile: str,
    name: str | None,
    final_amount: float,
    coins_earned: int,
    coins_redeemed: int,
    coins_redeemed_value: float,
    balance: int,
    push_token: str | None = None,
) -> str:
    """
    Send a post-payment summary to the customer after the admin processes a
    transaction. Push-first when a token is on file, SMS fallback otherwise.
    Returns the channel used ("push" or "sms").
    """
    body = messages.transaction_summary(
        name=name,
        final_amount=final_amount,
        coins_earned=coins_earned,
        coins_redeemed=coins_redeemed,
        coins_redeemed_value=coins_redeemed_value,
        balance=balance,
    )
    return await _send_push_or_sms(push_token, mobile, "Payment Successful", body)


async def dispatch_expiry_notification(user_id: str) -> None:
    """Send coins expiry reminder to a user. Called by APScheduler job."""
    from app.database import get_pool

    async with get_pool().acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, mobile_number, push_token FROM users WHERE id = $1", user_id
        )
        if not user:
            return

        now = utcnow()
        window = now + timedelta(days=settings.EXPIRY_NOTIFY_DAYS)

        row = await conn.fetchrow(
            """SELECT COALESCE(SUM(coins), 0) AS total, MIN(expiry_at) AS earliest
               FROM coins_ledger
               WHERE user_id = $1
                 AND status = 'active'
                 AND type = 'earned'
                 AND expiry_at > $2
                 AND expiry_at <= $3""",
            user_id, now, window,
        )

        if not row or not row["total"] or int(row["total"]) <= 0:
            return

        expiry_str = row["earliest"].strftime("%d %b %Y")

        channel = "sms"
        try:
            channel = await send_expiry_reminder(
                user["mobile_number"],
                int(row["total"]),
                expiry_str,
                push_token=user["push_token"],
            )
            log_status = "sent"
            log_error = None
        except Exception as e:
            logger.error("Expiry notification failed for user %s: %s", user_id, e)
            log_status = "failed"
            log_error = str(e)

        await conn.execute(
            """INSERT INTO notification_logs
                   (id, user_id, channel, type, status, error_detail, sent_at, created_at)
               VALUES ($1,$2,$3,'coins_expiry',$4,$5,$6,$7)""",
            new_uuid(), user_id, channel, log_status, log_error,
            now if log_status == "sent" else None, now,
        )
