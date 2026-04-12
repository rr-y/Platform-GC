import asyncpg
from fastapi import APIRouter, Depends, Query

from app.database import get_conn
from app.deps import get_current_user
from app.schemas import (
    CoinBalanceOut,
    CoinHistoryItem,
    ExpiringSoon,
    PaginatedCoins,
    PaginatedTransactions,
    TransactionItem,
)
from app.services.coins import get_balance, get_expiring_soon

router = APIRouter(tags=["coins"])


@router.get("/users/me/coins/balance", response_model=CoinBalanceOut)
async def coin_balance(
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    total = await get_balance(current_user["id"], conn)
    expiring = await get_expiring_soon(current_user["id"], conn)
    return CoinBalanceOut(
        total_active_coins=total,
        expiring_soon=ExpiringSoon(**expiring) if expiring else None,
    )


@router.get("/users/me/coins/history", response_model=PaginatedCoins)
async def coin_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    offset = (page - 1) * limit
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM coins_ledger WHERE user_id = $1", current_user["id"]
    )
    rows = await conn.fetch(
        """SELECT id, coins, type, status, issued_at, expiry_at, reference_id
           FROM coins_ledger
           WHERE user_id = $1
           ORDER BY issued_at DESC
           LIMIT $2 OFFSET $3""",
        current_user["id"], limit, offset,
    )
    items = [
        CoinHistoryItem(
            id=r["id"],
            coins=r["coins"],
            type=r["type"],
            status=r["status"],
            issued_at=r["issued_at"].isoformat(),
            expiry_at=r["expiry_at"].isoformat(),
            reference_id=r["reference_id"],
        )
        for r in rows
    ]
    return PaginatedCoins(items=items, total=total, page=page, limit=limit)


@router.get("/users/me", response_model=dict)
async def my_profile(
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    balance = await get_balance(current_user["id"], conn)
    return {
        "user_id": current_user["id"],
        "mobile_number": current_user["mobile_number"],
        "name": current_user["name"],
        "role": current_user["role"],
        "coin_balance": balance,
    }


@router.patch("/users/me", response_model=dict)
async def update_profile(
    body: dict,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    if "name" in body:
        await conn.execute(
            "UPDATE users SET name = $1 WHERE id = $2", body["name"], current_user["id"]
        )
    row = await conn.fetchrow(
        "SELECT id, mobile_number, name FROM users WHERE id = $1", current_user["id"]
    )
    return {"user_id": row["id"], "mobile_number": row["mobile_number"], "name": row["name"]}


@router.get("/users/me/transactions", response_model=PaginatedTransactions)
async def my_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    offset = (page - 1) * limit
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE user_id = $1", current_user["id"]
    )
    rows = await conn.fetch(
        """SELECT id, amount, coins_earned, coins_used, discount_amount, status, created_at
           FROM transactions
           WHERE user_id = $1
           ORDER BY created_at DESC
           LIMIT $2 OFFSET $3""",
        current_user["id"], limit, offset,
    )
    items = [
        TransactionItem(
            id=r["id"],
            amount=float(r["amount"]),
            coins_earned=r["coins_earned"],
            coins_used=r["coins_used"],
            discount_amount=float(r["discount_amount"]),
            status=r["status"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]
    return PaginatedTransactions(items=items, total=total, page=page, limit=limit)
