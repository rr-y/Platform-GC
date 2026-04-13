import logging
import asyncpg
from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


def _pg_url(url: str) -> str:
    """Strip SQLAlchemy driver prefix so asyncpg can use the URL."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def init_pool() -> None:
    global _pool
    url = _pg_url(settings.DATABASE_URL)
    # Log the host being connected to (hide password)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        logger.info("DB connecting to: %s:%s/%s (ssl=%s, APP_ENV=%s)",
                    parsed.hostname, parsed.port, parsed.path.lstrip("/"),
                    settings.APP_ENV != "development", settings.APP_ENV)
    except Exception:
        pass
    # Railway (and most managed PostgreSQL) requires SSL — pass ssl="require" when not local
    ssl = "require" if settings.APP_ENV != "development" else None
    _pool = await asyncpg.create_pool(
        url,
        min_size=2,
        max_size=10,
        ssl=ssl,
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    assert _pool is not None, "DB pool not initialised — call init_pool() in app lifespan"
    return _pool


async def get_conn():
    """FastAPI dependency: yields an asyncpg connection from the pool."""
    async with get_pool().acquire() as conn:
        yield conn
