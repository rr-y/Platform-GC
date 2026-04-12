import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.jobs import expire_coins, send_expiry_notifications
from app.routers import auth, coins, transactions, coupons, admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    scheduler.add_job(expire_coins, CronTrigger(hour=2, minute=0), id="expire_coins")
    scheduler.add_job(send_expiry_notifications, CronTrigger(hour=9, minute=0), id="expiry_notifs")
    scheduler.start()
    logger.info("Scheduler started")
    yield
    # Shutdown
    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(title="Platform GC", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(coins.router, prefix="/api/v1")
app.include_router(transactions.router, prefix="/api/v1")
app.include_router(coupons.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
