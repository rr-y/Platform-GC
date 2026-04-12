"""
Database helpers.
All table definitions live in alembic/versions/.
All data models (request/response shapes) live in schemas.py.
"""
import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())
