import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import close_pool, init_pool
from app.jobs import expire_coins, send_expiry_notifications
from app.routers import admin, auth, coins, coupons, offers, transactions

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    scheduler.add_job(expire_coins, CronTrigger(hour=2, minute=0), id="expire_coins")
    scheduler.add_job(send_expiry_notifications, CronTrigger(hour=9, minute=0), id="expiry_notifs")
    scheduler.start()
    logger.info("Scheduler started")
    yield
    scheduler.shutdown()
    await close_pool()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Platform GC",
    version="0.1.0",
    lifespan=lifespan,
    debug=not settings.is_production,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(coins.router, prefix="/api/v1")
app.include_router(transactions.router, prefix="/api/v1")
app.include_router(coupons.router, prefix="/api/v1")
app.include_router(offers.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
