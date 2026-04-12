from datetime import timedelta

import asyncpg

from app.config import settings
from app.models import new_uuid, utcnow


async def get_balance(user_id: str, conn: asyncpg.Connection) -> int:
    """Net active coin balance: SUM(coins) WHERE status=active AND expiry_at > NOW()."""
    val = await conn.fetchval(
        """SELECT COALESCE(SUM(coins), 0)
           FROM coins_ledger
           WHERE user_id = $1 AND status = 'active' AND expiry_at > NOW()""",
        user_id,
    )
    return int(val or 0)


async def award_coins(
    user_id: str,
    coins: int,
    reference_id: str,
    conn: asyncpg.Connection,
) -> None:
    """Insert an earned coins ledger entry. redeemable_after=now+1s blocks same-txn redeem."""
    now = utcnow()
    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
           VALUES ($1, $2, $3, 'earned', 'active', $4, $5, $6, $7)""",
        new_uuid(), user_id, coins, reference_id, now,
        now + timedelta(days=settings.COINS_EXPIRY_DAYS),
        now + timedelta(seconds=1),
    )


async def redeem_coins(
    user_id: str,
    coins: int,
    transaction_id: str,
    txn_start: object,
    conn: asyncpg.Connection,
) -> None:
    """Insert a negative ledger entry to record redemption. Validates available balance first."""
    available = await conn.fetchval(
        """SELECT COALESCE(SUM(coins), 0)
           FROM coins_ledger
           WHERE user_id = $1
             AND status = 'active'
             AND expiry_at > NOW()
             AND redeemable_after < $2""",
        user_id, txn_start,
    )
    available = int(available or 0)
    if coins > available:
        raise InsufficientCoinsError(f"Only {available} coins available for redemption")

    now = utcnow()
    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, reference_id, issued_at, expiry_at, redeemable_after)
           VALUES ($1, $2, $3, 'redeemed', 'active', $4, $5, $6, $7)""",
        new_uuid(), user_id, -coins, transaction_id, now,
        now + timedelta(days=36500),
        now,
    )


async def get_expiring_soon(user_id: str, conn: asyncpg.Connection) -> dict | None:
    """Return total coins and earliest expiry within EXPIRY_NOTIFY_DAYS window."""
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
        return None
    return {"coins": int(row["total"]), "expiry_at": row["earliest"].isoformat()}


class InsufficientCoinsError(Exception):
    pass
