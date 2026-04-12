from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import CoinsLedger, Transaction, User, utcnow
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total = await get_balance(current_user.id, db)
    expiring = await get_expiring_soon(current_user.id, db)
    return CoinBalanceOut(
        total_active_coins=total,
        expiring_soon=ExpiringSoon(**expiring) if expiring else None,
    )


@router.get("/users/me/coins/history", response_model=PaginatedCoins)
async def coin_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit

    count_result = await db.execute(
        select(func.count()).where(CoinsLedger.user_id == current_user.id)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(CoinsLedger)
        .where(CoinsLedger.user_id == current_user.id)
        .order_by(CoinsLedger.issued_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()

    items = [
        CoinHistoryItem(
            id=r.id,
            coins=r.coins,
            type=r.type,
            status=r.status,
            issued_at=r.issued_at.isoformat(),
            expiry_at=r.expiry_at.isoformat(),
            reference_id=r.reference_id,
        )
        for r in rows
    ]
    return PaginatedCoins(items=items, total=total, page=page, limit=limit)


@router.get("/users/me", response_model=dict)
async def my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    balance = await get_balance(current_user.id, db)
    return {
        "user_id": current_user.id,
        "mobile_number": current_user.mobile_number,
        "name": current_user.name,
        "role": current_user.role,
        "coin_balance": balance,
    }


@router.get("/users/me/transactions", response_model=PaginatedTransactions)
async def my_transactions(
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


@router.patch("/users/me", response_model=dict)
async def update_profile(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if "name" in body:
        current_user.name = body["name"]
        await db.commit()
        await db.refresh(current_user)
    return {
        "user_id": current_user.id,
        "mobile_number": current_user.mobile_number,
        "name": current_user.name,
    }
