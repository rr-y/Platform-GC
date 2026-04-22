"""Print Store business logic.

Responsibilities:
- Validate and persist uploaded files on the local volume
- Count PDF pages (images are always 1 page)
- Compute pricing with coin redemption
- Generate unique 4-digit pickup OTPs
- Drive the print_jobs state machine
- Delete files once the Pi has printed them
"""
from __future__ import annotations

import io
import json
import logging
import os
import secrets
from datetime import timedelta
from math import floor
from pathlib import Path

import asyncpg
from fastapi import UploadFile

from app.config import settings
from app.models import new_uuid, utcnow
from app.services.coins import get_balance

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"
ALLOWED_MIMES = {PDF_MIME, JPEG_MIME, PNG_MIME}

EXT_FOR_MIME = {PDF_MIME: "pdf", JPEG_MIME: "jpg", PNG_MIME: "png"}

# Magic-byte prefixes: we re-sniff the uploaded bytes rather than trust the
# client-supplied Content-Type.
_MAGIC = [
    (PDF_MIME, b"%PDF-"),
    (JPEG_MIME, b"\xff\xd8\xff"),
    (PNG_MIME, b"\x89PNG\r\n\x1a\n"),
]

ACTIVE_STATUSES = ("queued", "printing", "printed")


class PrintError(Exception):
    """Raised when a print-job operation fails with a user-facing reason."""


def _storage_root() -> Path:
    root = Path(settings.PRINT_STORAGE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except PermissionError:
        pass
    return root


def _sniff_mime(head: bytes) -> str | None:
    for mime, prefix in _MAGIC:
        if head.startswith(prefix):
            return mime
    return None


def _count_pdf_pages(data: bytes) -> int:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        return len(reader.pages)
    except (PdfReadError, ValueError, OSError) as e:
        raise PrintError(f"Unreadable PDF: {e}") from e


async def save_upload(
    user_id: str,
    upload: UploadFile,
    conn: asyncpg.Connection,
) -> dict:
    """Validate + persist an uploaded file, then create a draft print_jobs row."""
    max_bytes = settings.PRINT_MAX_FILE_SIZE_MB * 1024 * 1024
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PrintError(f"File exceeds {settings.PRINT_MAX_FILE_SIZE_MB} MB limit")
    if not data:
        raise PrintError("Empty file")

    mime = _sniff_mime(data[:16])
    if mime not in ALLOWED_MIMES:
        raise PrintError("Unsupported file type. Only PDF, JPG, PNG are allowed.")

    page_count = _count_pdf_pages(data) if mime == PDF_MIME else 1
    if page_count <= 0:
        raise PrintError("File has no pages")

    job_id = new_uuid()
    ext = EXT_FOR_MIME[mime]
    path = _storage_root() / f"{job_id}.{ext}"
    path.write_bytes(data)

    file_name = (upload.filename or f"upload.{ext}")[:255]
    await conn.execute(
        """INSERT INTO print_jobs
               (id, user_id, file_name, mime_type, file_size, storage_path,
                page_count, status, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'draft', $8)""",
        job_id, user_id, file_name, mime, len(data), str(path), page_count, utcnow(),
    )
    return {
        "upload_id": job_id,
        "file_name": file_name,
        "mime_type": mime,
        "page_count": page_count,
        "file_size": len(data),
    }


def _validate_selection(selected_pages: list[int], page_count: int, copies: int, color_mode: str) -> None:
    if color_mode not in ("bw", "color"):
        raise PrintError("color_mode must be 'bw' or 'color'")
    if copies < 1:
        raise PrintError("copies must be at least 1")
    if not selected_pages:
        raise PrintError("Select at least one page")
    if any(p < 1 or p > page_count for p in selected_pages):
        raise PrintError(f"Page numbers must be between 1 and {page_count}")
    if len(set(selected_pages)) != len(selected_pages):
        raise PrintError("Duplicate page numbers")


def calculate_breakdown(
    selected_pages: list[int],
    page_count: int,
    color_mode: str,
    copies: int,
    coins_to_redeem: int,
    user_balance: int,
) -> dict:
    _validate_selection(selected_pages, page_count, copies, color_mode)
    pages_to_print = len(selected_pages)
    rate = (
        settings.PRINT_PRICE_COLOR_PER_PAGE
        if color_mode == "color"
        else settings.PRINT_PRICE_BW_PER_PAGE
    )
    subtotal = round(pages_to_print * copies * rate, 2)
    max_coins = floor(subtotal * settings.MAX_COINS_REDEEM_PERCENT / settings.COIN_RUPEE_VALUE)
    coins = max(0, min(coins_to_redeem, max_coins, user_balance))
    coin_value = round(coins * settings.COIN_RUPEE_VALUE, 2)
    final_amount = round(max(0.0, subtotal - coin_value), 2)
    return {
        "pages_to_print": pages_to_print,
        "copies": copies,
        "color_mode": color_mode,
        "rate_per_page": float(rate),
        "subtotal": subtotal,
        "coins_to_redeem": coins,
        "coin_value": coin_value,
        "final_amount": final_amount,
    }


def _generate_otp() -> str:
    return str(secrets.randbelow(10_000)).zfill(4)


async def _allocate_unique_otp(conn: asyncpg.Connection) -> str:
    for _ in range(15):
        otp = _generate_otp()
        existing = await conn.fetchval(
            "SELECT 1 FROM print_jobs WHERE pickup_otp = $1 AND status = ANY($2::text[])",
            otp, list(ACTIVE_STATUSES),
        )
        if not existing:
            return otp
    raise PrintError("Could not allocate a unique pickup OTP, try again")


async def submit_job(
    user_id: str,
    upload_id: str,
    selected_pages: list[int],
    color_mode: str,
    copies: int,
    coins_to_redeem: int,
    conn: asyncpg.Connection,
) -> dict:
    draft = await conn.fetchrow(
        """SELECT id, user_id, page_count, status, storage_path
           FROM print_jobs WHERE id = $1""",
        upload_id,
    )
    if not draft or draft["user_id"] != user_id:
        raise PrintError("Upload not found")
    if draft["status"] != "draft":
        raise PrintError("This upload has already been submitted")
    if not draft["storage_path"]:
        raise PrintError("Uploaded file is no longer available")

    balance = await get_balance(user_id, conn)
    breakdown = calculate_breakdown(
        selected_pages, draft["page_count"], color_mode, copies, coins_to_redeem, balance,
    )
    otp = await _allocate_unique_otp(conn)
    now = utcnow()
    await conn.execute(
        """UPDATE print_jobs
           SET selected_pages = $1::jsonb,
               color_mode     = $2,
               copies         = $3,
               subtotal       = $4,
               coins_to_redeem= $5,
               coin_value     = $6,
               final_amount   = $7,
               pickup_otp     = $8,
               status         = 'queued',
               queued_at      = $9
           WHERE id = $10""",
        json.dumps(selected_pages), color_mode, copies,
        breakdown["subtotal"], breakdown["coins_to_redeem"], breakdown["coin_value"],
        breakdown["final_amount"], otp, now, upload_id,
    )
    return {"job_id": upload_id, "pickup_otp": otp, "breakdown": breakdown}


async def list_user_jobs(user_id: str, conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM print_jobs WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )
    return [_row_to_dict(r) for r in rows]


async def get_user_job(job_id: str, user_id: str, conn: asyncpg.Connection) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM print_jobs WHERE id = $1 AND user_id = $2",
        job_id, user_id,
    )
    return _row_to_dict(row) if row else None


async def cancel_job(job_id: str, user_id: str, conn: asyncpg.Connection) -> None:
    row = await conn.fetchrow(
        "SELECT status, storage_path FROM print_jobs WHERE id = $1 AND user_id = $2",
        job_id, user_id,
    )
    if not row:
        raise PrintError("Job not found")
    if row["status"] not in ("draft", "queued"):
        raise PrintError(f"Cannot cancel a job in status '{row['status']}'")
    _delete_file(row["storage_path"])
    await conn.execute(
        """UPDATE print_jobs
           SET status = 'cancelled', cancelled_at = $1, storage_path = NULL
           WHERE id = $2""",
        utcnow(), job_id,
    )


async def claim_queue(conn: asyncpg.Connection, limit: int = 20) -> list[dict]:
    """Atomically move up to `limit` queued jobs to `printing` and return them."""
    rows = await conn.fetch(
        """UPDATE print_jobs
           SET status = 'printing', claimed_at = $1
           WHERE id = ANY(
               SELECT id FROM print_jobs
               WHERE status = 'queued'
               ORDER BY queued_at ASC
               LIMIT $2
               FOR UPDATE SKIP LOCKED
           )
           RETURNING id, file_name, mime_type, selected_pages, color_mode, copies""",
        utcnow(), limit,
    )
    jobs = []
    for r in rows:
        pages = r["selected_pages"]
        if isinstance(pages, str):
            pages = json.loads(pages)
        jobs.append({
            "job_id": r["id"],
            "file_name": r["file_name"],
            "mime_type": r["mime_type"],
            "selected_pages": pages,
            "color_mode": r["color_mode"],
            "copies": r["copies"],
        })
    return jobs


async def get_job_for_device(job_id: str, conn: asyncpg.Connection) -> dict | None:
    row = await conn.fetchrow(
        """SELECT id, storage_path, mime_type, file_name, status
           FROM print_jobs WHERE id = $1""",
        job_id,
    )
    return dict(row) if row else None


async def mark_printed(
    job_id: str,
    conn: asyncpg.Connection,
) -> dict | None:
    """Transition printing→printed, delete file, return user contact for push."""
    row = await conn.fetchrow(
        """SELECT pj.id, pj.user_id, pj.storage_path, pj.status, pj.pickup_otp,
                  pj.final_amount, u.mobile_number, u.name, u.push_token
           FROM print_jobs pj JOIN users u ON u.id = pj.user_id
           WHERE pj.id = $1""",
        job_id,
    )
    if not row:
        return None
    if row["status"] != "printing":
        raise PrintError(f"Cannot mark printed from status '{row['status']}'")
    _delete_file(row["storage_path"])
    await conn.execute(
        """UPDATE print_jobs
           SET status = 'printed', printed_at = $1, storage_path = NULL
           WHERE id = $2""",
        utcnow(), job_id,
    )
    return {
        "user_id": row["user_id"],
        "mobile_number": row["mobile_number"],
        "name": row["name"],
        "push_token": row["push_token"],
        "pickup_otp": row["pickup_otp"],
        "final_amount": float(row["final_amount"] or 0),
    }


async def mark_failed(job_id: str, conn: asyncpg.Connection, max_retries: int = 3) -> str:
    """Revert to queued, or cancel after max_retries failures. Returns new status."""
    row = await conn.fetchrow(
        "SELECT status, retry_count, storage_path FROM print_jobs WHERE id = $1", job_id,
    )
    if not row:
        raise PrintError("Job not found")
    if row["status"] != "printing":
        raise PrintError(f"Cannot fail a job in status '{row['status']}'")
    next_retry = row["retry_count"] + 1
    if next_retry >= max_retries:
        _delete_file(row["storage_path"])
        await conn.execute(
            """UPDATE print_jobs
               SET status = 'cancelled', cancelled_at = $1,
                   retry_count = $2, storage_path = NULL
               WHERE id = $3""",
            utcnow(), next_retry, job_id,
        )
        return "cancelled"
    await conn.execute(
        """UPDATE print_jobs
           SET status = 'queued', claimed_at = NULL, retry_count = $1
           WHERE id = $2""",
        next_retry, job_id,
    )
    return "queued"


async def lookup_by_otp(pickup_otp: str, conn: asyncpg.Connection) -> dict | None:
    row = await conn.fetchrow(
        """SELECT pj.*, u.mobile_number, u.name
           FROM print_jobs pj JOIN users u ON u.id = pj.user_id
           WHERE pj.pickup_otp = $1 AND pj.status = ANY($2::text[])""",
        pickup_otp, list(ACTIVE_STATUSES),
    )
    if not row:
        return None
    return {
        "job_id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "mobile_number": row["mobile_number"],
        "file_name": row["file_name"],
        "status": row["status"],
        "page_count": row["page_count"],
        "selected_pages": _parse_pages(row["selected_pages"]),
        "color_mode": row["color_mode"],
        "copies": row["copies"],
        "subtotal": float(row["subtotal"] or 0),
        "coins_to_redeem": row["coins_to_redeem"],
        "coin_value": float(row["coin_value"] or 0),
        "final_amount": float(row["final_amount"] or 0),
    }


async def mark_collected(
    job_id: str,
    transaction_id: str,
    conn: asyncpg.Connection,
) -> None:
    await conn.execute(
        """UPDATE print_jobs
           SET status = 'collected', collected_at = $1, transaction_id = $2
           WHERE id = $3""",
        utcnow(), transaction_id, job_id,
    )


# ── Housekeeping ─────────────────────────────────────────────────────────────

async def purge_abandoned_drafts(conn: asyncpg.Connection) -> int:
    cutoff = utcnow() - timedelta(hours=settings.PRINT_DRAFT_TTL_HOURS)
    rows = await conn.fetch(
        "SELECT id, storage_path FROM print_jobs WHERE status = 'draft' AND created_at < $1",
        cutoff,
    )
    for r in rows:
        _delete_file(r["storage_path"])
    await conn.execute(
        "DELETE FROM print_jobs WHERE status = 'draft' AND created_at < $1",
        cutoff,
    )
    return len(rows)


async def purge_old_printed_metadata(conn: asyncpg.Connection) -> int:
    cutoff = utcnow() - timedelta(days=settings.PRINT_UNCOLLECTED_RETENTION_DAYS)
    result = await conn.execute(
        "DELETE FROM print_jobs WHERE status = 'printed' AND printed_at < $1",
        cutoff,
    )
    return int(result.split()[-1]) if result else 0


# ── Internal helpers ─────────────────────────────────────────────────────────

def _delete_file(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Could not delete print file %s: %s", path, e)


def _parse_pages(value) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_dict(row) -> dict:
    def iso(v):
        return v.isoformat() if v else None
    return {
        "id": row["id"],
        "file_name": row["file_name"],
        "mime_type": row["mime_type"],
        "page_count": row["page_count"],
        "selected_pages": _parse_pages(row["selected_pages"]),
        "color_mode": row["color_mode"],
        "copies": row["copies"],
        "subtotal": float(row["subtotal"]) if row["subtotal"] is not None else None,
        "coins_to_redeem": row["coins_to_redeem"],
        "coin_value": float(row["coin_value"]) if row["coin_value"] is not None else 0.0,
        "final_amount": float(row["final_amount"]) if row["final_amount"] is not None else None,
        "pickup_otp": row["pickup_otp"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "queued_at": iso(row["queued_at"]),
        "printed_at": iso(row["printed_at"]),
        "collected_at": iso(row["collected_at"]),
    }
