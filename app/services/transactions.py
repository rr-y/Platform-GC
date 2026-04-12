import logging
from decimal import Decimal
from math import floor

import asyncpg

from app.config import settings
from app.models import new_uuid, utcnow
from app.services.coins import InsufficientCoinsError, award_coins, get_balance, redeem_coins

logger = logging.getLogger(__name__)


async def create_transaction(
    user_id: str,
    amount: float,
    conn: asyncpg.Connection,
    order_ref: str | None = None,
    coins_to_redeem: int = 0,
    coupon_code: str | None = None,
) -> dict:
    txn_start = utcnow()

    # ── 1. Idempotency ────────────────────────────────────────────────────────
    if order_ref:
        existing = await conn.fetchrow(
            "SELECT * FROM transactions WHERE order_ref = $1", order_ref
        )
        if existing:
            balance = await get_balance(user_id, conn)
            return _format_row(existing, balance)

    # ── 2. Coupon validation ──────────────────────────────────────────────────
    coupon_discount = 0.0
    coupon_id = None
    if coupon_code:
        from app.services.campaigns import validate_coupon
        coupon, coupon_discount = await validate_coupon(coupon_code, user_id, amount, conn)
        coupon_id = coupon["id"]

    # ── 3. Coin redemption cap ────────────────────────────────────────────────
    if coins_to_redeem > 0:
        max_coins = floor(amount * settings.MAX_COINS_REDEEM_PERCENT / settings.COIN_RUPEE_VALUE)
        coins_to_redeem = min(coins_to_redeem, max_coins)

    # ── 4. Final amount & coins to earn ──────────────────────────────────────
    coin_discount = coins_to_redeem * settings.COIN_RUPEE_VALUE
    final_amount = max(0.0, amount - coupon_discount - coin_discount)
    coins_earned = floor(final_amount * settings.COINS_EARN_RATE / 100)
    total_discount = round(coupon_discount + coin_discount, 2)

    # ── 5. Atomic DB write ────────────────────────────────────────────────────
    txn_id = new_uuid()
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO transactions
                   (id, user_id, order_ref, amount, coins_earned, coins_used,
                    discount_amount, coupon_id, status, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'completed', $9)""",
            txn_id, user_id, order_ref, amount, coins_earned, coins_to_redeem,
            total_discount, coupon_id, utcnow(),
        )

        if coins_to_redeem > 0:
            await redeem_coins(user_id, coins_to_redeem, txn_id, txn_start, conn)

        if coins_earned > 0:
            await award_coins(user_id, coins_earned, txn_id, conn)

        if coupon_id:
            await conn.execute(
                "UPDATE coupons SET uses_count = uses_count + 1 WHERE id = $1", coupon_id
            )
            await conn.execute(
                """INSERT INTO coupon_redemptions (id, coupon_id, user_id, transaction_id, redeemed_at)
                   VALUES ($1, $2, $3, $4, $5)""",
                new_uuid(), coupon_id, user_id, txn_id, utcnow(),
            )

    txn = await conn.fetchrow("SELECT * FROM transactions WHERE id = $1", txn_id)
    balance = await get_balance(user_id, conn)
    return _format_row(txn, balance, coupon_discount=coupon_discount, coin_discount=coin_discount)


def _format_row(
    row,
    balance_after: int,
    coupon_discount: float = 0.0,
    coin_discount: float = 0.0,
) -> dict:
    coins_used = row["coins_used"]
    total_discount = float(row["discount_amount"] or 0)
    coin_discount_val = coins_used * settings.COIN_RUPEE_VALUE
    final_amount = max(0.0, float(row["amount"]) - total_discount)
    return {
        "transaction_id": row["id"],
        "amount": float(row["amount"]),
        "discount_applied": round(total_discount - coin_discount_val, 2),
        "coins_redeemed": coins_used,
        "coins_redeemed_value": round(coin_discount_val, 2),
        "final_amount": round(final_amount, 2),
        "coins_earned": row["coins_earned"],
        "coins_balance_after": balance_after,
    }
