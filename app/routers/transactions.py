import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_conn
from app.deps import get_current_user
from app.schemas import PaginatedTransactions, TransactionIn, TransactionItem, TransactionOut
from app.services.coins import InsufficientCoinsError
from app.services.transactions import create_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def post_transaction(
    body: TransactionIn,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        result = await create_transaction(
            user_id=current_user["id"],
            amount=body.amount,
            conn=conn,
            order_ref=body.order_ref,
            coins_to_redeem=body.coins_to_redeem,
            coupon_code=body.coupon_code,
        )
    except InsufficientCoinsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return result


@router.get("/{transaction_id}", response_model=TransactionItem)
async def get_transaction(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        """SELECT id, amount, coins_earned, coins_used, discount_amount, status, created_at
           FROM transactions
           WHERE id = $1 AND user_id = $2""",
        transaction_id, current_user["id"],
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return TransactionItem(
        id=row["id"],
        amount=float(row["amount"]),
        coins_earned=row["coins_earned"],
        coins_used=row["coins_used"],
        discount_amount=float(row["discount_amount"]),
        status=row["status"],
        created_at=row["created_at"].isoformat(),
    )


@router.get("", response_model=PaginatedTransactions)
async def list_transactions(
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
