from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import Transaction, User
from app.schemas import PaginatedTransactions, TransactionIn, TransactionItem, TransactionOut
from app.services.coins import InsufficientCoinsError
from app.services.transactions import create_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def post_transaction(
    body: TransactionIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await create_transaction(
            user_id=current_user.id,
            amount=body.amount,
            db=db,
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == current_user.id,
        )
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return TransactionItem(
        id=txn.id,
        amount=float(txn.amount),
        coins_earned=txn.coins_earned,
        coins_used=txn.coins_used,
        discount_amount=float(txn.discount_amount),
        status=txn.status,
        created_at=txn.created_at.isoformat(),
    )


@router.get("", response_model=PaginatedTransactions)
async def list_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit

    count_result = await db.execute(
        select(func.count()).where(Transaction.user_id == current_user.id)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == current_user.id)
        .order_by(Transaction.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()
    items = [
        TransactionItem(
            id=r.id,
            amount=float(r.amount),
            coins_earned=r.coins_earned,
            coins_used=r.coins_used,
            discount_amount=float(r.discount_amount),
            status=r.status,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    return PaginatedTransactions(items=items, total=total, page=page, limit=limit)
