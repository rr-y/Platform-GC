"""
Central repository for all user-facing notification message templates.

Every SMS message sent to customers must be defined here.
To change any customer-facing copy, edit this file — nowhere else.
"""

from app.config import settings


# ── Auth ──────────────────────────────────────────────────────────────────────

def otp_message(otp: str) -> str:
    minutes = settings.OTP_EXPIRE_SECONDS // 60
    return f"Your OTP is {otp}. Valid for {minutes} minutes. Do not share."


# ── Coins expiry ──────────────────────────────────────────────────────────────

def expiry_reminder(coins: int, expiry_date: str) -> str:
    return (
        f"Hi! Your {coins} reward coins expire on {expiry_date}. "
        f"Use them on your next purchase before they expire!"
    )


# ── Campaign blast ────────────────────────────────────────────────────────────

def campaign_blast(title: str, valid_to: str) -> str:
    return f"\U0001f389 {title} \u2014 Don't miss out! Valid till {valid_to}."


# ── Transaction notifications ─────────────────────────────────────────────────

def transaction_summary(
    name: str | None,
    final_amount: float,
    coins_earned: int,
    coins_redeemed: int,
    coins_redeemed_value: float,
    balance: int,
) -> str:
    """
    Single post-payment message summarising everything in one notification.
    Sent to the customer after the admin marks payment as successful.
    """
    greeting = f"Hi {name}!" if name else "Hi!"
    parts = [f"{greeting} Payment of \u20b9{final_amount:.2f} confirmed."]

    if coins_redeemed > 0:
        parts.append(
            f"You redeemed {coins_redeemed} coins (\u20b9{coins_redeemed_value:.2f} off)."
        )

    if coins_earned > 0:
        parts.append(f"Earned {coins_earned} coins.")

    parts.append(f"Coin balance: {balance}.")
    return " ".join(parts)


def coins_expiry_warning(name: str | None, coins: int, expiry_date: str) -> str:
    """
    Appended to the transaction summary when coins are expiring soon
    (within EXPIRY_NOTIFY_DAYS) so the customer acts before their next visit.
    """
    greeting = f"Hey {name}," if name else "Hey,"
    return (
        f"{greeting} heads up — {coins} of your coins expire on {expiry_date}. "
        f"Use them soon!"
    )
