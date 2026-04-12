import logging
from datetime import timezone
from math import floor

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Coupon, CouponRedemption, Transaction, utcnow
from app.services.coins import InsufficientCoinsError, award_coins, get_balance, redeem_coins

logger = logging.getLogger(__name__)


async def create_transaction(
    user_id: str,
    amount: float,
    db: AsyncSession,
    order_ref: str | None = None,
    coins_to_redeem: int = 0,
    coupon_code: str | None = None,
) -> dict:
    txn_start = utcnow()

    # ── 1. Idempotency ────────────────────────────────────────────────────────
    if order_ref:
        existing = await db.execute(
            select(Transaction).where(Transaction.order_ref == order_ref)
        )
        txn = existing.scalar_one_or_none()
        if txn:
            balance = await get_balance(user_id, db)
            return _format_result(txn, balance)

    # ── 2. Coupon validation ──────────────────────────────────────────────────
    coupon_discount = 0.0
    coupon_id = None
    if coupon_code:
        coupon, discount = await _apply_coupon(coupon_code, user_id, amount, db)
        coupon_discount = discount
        coupon_id = coupon.id

    # ── 3. Coin redemption cap ────────────────────────────────────────────────
    if coins_to_redeem > 0:
        max_inr = amount * settings.MAX_COINS_REDEEM_PERCENT
        max_coins = floor(max_inr / settings.COIN_RUPEE_VALUE)
        coins_to_redeem = min(coins_to_redeem, max_coins)

    # ── 4. Final amount & coins to earn ──────────────────────────────────────
    coin_discount = coins_to_redeem * settings.COIN_RUPEE_VALUE
    final_amount = max(0.0, amount - coupon_discount - coin_discount)
    coins_earned = floor(final_amount * settings.COINS_EARN_RATE / 100)

    # ── 5. Atomic DB write ────────────────────────────────────────────────────
    txn = Transaction(
        user_id=user_id,
        order_ref=order_ref,
        amount=amount,
        coins_earned=coins_earned,
        coins_used=coins_to_redeem,
        discount_amount=round(coupon_discount + coin_discount, 2),
        coupon_id=coupon_id,
        status="completed",
    )
    db.add(txn)
    await db.flush()  # get txn.id before inserting ledger rows

    if coins_to_redeem > 0:
        try:
            await redeem_coins(user_id, coins_to_redeem, txn.id, txn_start, db)
        except InsufficientCoinsError as e:
            await db.rollback()
            raise e

    if coins_earned > 0:
        await award_coins(user_id, coins_earned, txn.id, db)

    # Increment coupon usage
    if coupon_id:
        coupon_row = await db.get(Coupon, coupon_id)
        if coupon_row:
            coupon_row.uses_count += 1
            redemption = CouponRedemption(
                coupon_id=coupon_id,
                user_id=user_id,
                transaction_id=txn.id,
            )
            db.add(redemption)

    await db.commit()
    await db.refresh(txn)

    balance = await get_balance(user_id, db)
    return _format_result(txn, balance, coupon_discount=coupon_discount, coin_discount=coin_discount)


async def _apply_coupon(
    code: str,
    user_id: str,
    order_amount: float,
    db: AsyncSession,
) -> tuple[Coupon, float]:
    """Validate coupon and return (coupon, discount_amount). Raises ValueError on invalid."""
    from app.services.campaigns import validate_coupon
    return await validate_coupon(code, user_id, order_amount, db)


def _format_result(
    txn: Transaction,
    balance_after: int,
    coupon_discount: float = 0.0,
    coin_discount: float = 0.0,
) -> dict:
    total_discount = float(txn.discount_amount)
    coin_discount = txn.coins_used * settings.COIN_RUPEE_VALUE
    final_amount = max(0.0, float(txn.amount) - total_discount)
    return {
        "transaction_id": txn.id,
        "amount": float(txn.amount),
        "discount_applied": round(total_discount - coin_discount, 2),
        "coins_redeemed": txn.coins_used,
        "coins_redeemed_value": round(coin_discount, 2),
        "final_amount": round(final_amount, 2),
        "coins_earned": txn.coins_earned,
        "coins_balance_after": balance_after,
    }
