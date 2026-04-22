import io
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from pypdf import PdfWriter

from app.config import settings
from app.models import new_uuid, utcnow
from app.services.auth import OTP_KEY


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff\xff?\x03\x00\x08\xfc\x02\xfe\xa7mN]"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def print_storage(tmp_path, monkeypatch):
    storage = tmp_path / "prints"
    monkeypatch.setattr(settings, "PRINT_STORAGE_DIR", str(storage))
    return storage


@pytest.fixture
def device_key(monkeypatch):
    monkeypatch.setattr(settings, "DEVICE_API_KEY", "test-device-key")
    return "test-device-key"


async def _login(client, conn, redis, mobile: str, role: str = "user") -> tuple[dict, str]:
    user_id = new_uuid()
    await conn.execute(
        "INSERT INTO users (id, mobile_number, role, is_active, created_at) VALUES ($1,$2,$3,true,NOW())",
        user_id, mobile, role,
    )
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


async def _upload_pdf(client, headers, pages: int = 3) -> dict:
    resp = await client.post(
        "/api/v1/print/upload",
        headers=headers,
        files={"file": ("doc.pdf", _make_pdf(pages), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Upload ────────────────────────────────────────────────────────────────────

async def test_upload_pdf_counts_pages(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919111111111")
    data = await _upload_pdf(client, headers, pages=4)
    assert data["page_count"] == 4
    assert data["mime_type"] == "application/pdf"
    assert Path(print_storage / f"{data['upload_id']}.pdf").exists()


async def test_upload_png_is_one_page(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919111111112")
    resp = await client.post(
        "/api/v1/print/upload",
        headers=headers,
        files={"file": ("pic.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["page_count"] == 1
    assert resp.json()["mime_type"] == "image/png"


async def test_upload_rejects_unsupported_type(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919111111113")
    resp = await client.post(
        "/api/v1/print/upload",
        headers=headers,
        files={"file": ("thing.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 415


async def test_upload_rejects_oversize(client, conn, redis, print_storage, monkeypatch):
    monkeypatch.setattr(settings, "PRINT_MAX_FILE_SIZE_MB", 0)  # any byte is oversize
    headers, _ = await _login(client, conn, redis, "+919111111114")
    resp = await client.post(
        "/api/v1/print/upload",
        headers=headers,
        files={"file": ("doc.pdf", _make_pdf(1), "application/pdf")},
    )
    assert resp.status_code == 413


async def test_upload_requires_auth(client, print_storage):
    resp = await client.post(
        "/api/v1/print/upload",
        files={"file": ("doc.pdf", _make_pdf(1), "application/pdf")},
    )
    assert resp.status_code in (401, 403)


# ── Estimate / pricing ───────────────────────────────────────────────────────

async def test_estimate_bw(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919222222221")
    resp = await client.post(
        "/api/v1/print/jobs/estimate",
        headers=headers,
        json={
            "page_count": 5,
            "selected_pages": [1, 2, 3],
            "color_mode": "bw",
            "copies": 2,
            "coins_to_redeem": 0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # 3 pages * 2 copies * 2.0 = 12.0
    assert data["subtotal"] == 12.0
    assert data["final_amount"] == 12.0
    assert data["coins_to_redeem"] == 0


async def test_estimate_color(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919222222222")
    resp = await client.post(
        "/api/v1/print/jobs/estimate",
        headers=headers,
        json={
            "page_count": 2,
            "selected_pages": [1, 2],
            "color_mode": "color",
            "copies": 3,
            "coins_to_redeem": 0,
        },
    )
    # 2 pages * 3 copies * 10.0 = 60.0
    assert resp.json()["subtotal"] == 60.0


async def test_estimate_coin_cap_at_20_percent(client, conn, redis, print_storage):
    headers, user_id = await _login(client, conn, redis, "+919222222223")
    # Award a large balance so the cap is the binding constraint, not balance.
    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, issued_at, expiry_at, redeemable_after)
           VALUES ($1,$2,10000,'earned','active',NOW(),NOW()+INTERVAL '1 year',NOW())""",
        new_uuid(), user_id,
    )
    resp = await client.post(
        "/api/v1/print/jobs/estimate",
        headers=headers,
        json={
            "page_count": 5,
            "selected_pages": [1, 2, 3, 4, 5],
            "color_mode": "color",
            "copies": 1,
            "coins_to_redeem": 500,  # would be ₹50, but cap is 20% of ₹50 = ₹10 = 100 coins
        },
    )
    data = resp.json()
    # subtotal = 5 * 1 * 10 = 50 → max 20% = ₹10 = 100 coins
    assert data["subtotal"] == 50.0
    assert data["coins_to_redeem"] == 100
    assert data["coin_value"] == 10.0
    assert data["final_amount"] == 40.0


async def test_estimate_coin_cap_at_balance(client, conn, redis, print_storage):
    headers, user_id = await _login(client, conn, redis, "+919222222224")
    await conn.execute(
        """INSERT INTO coins_ledger
               (id, user_id, coins, type, status, issued_at, expiry_at, redeemable_after)
           VALUES ($1,$2,30,'earned','active',NOW(),NOW()+INTERVAL '1 year',NOW())""",
        new_uuid(), user_id,
    )
    resp = await client.post(
        "/api/v1/print/jobs/estimate",
        headers=headers,
        json={
            "page_count": 5,
            "selected_pages": [1, 2, 3, 4, 5],
            "color_mode": "color",
            "copies": 1,
            "coins_to_redeem": 500,
        },
    )
    # balance = 30 (user has fewer than the 20% cap of 100)
    assert resp.json()["coins_to_redeem"] == 30


async def test_estimate_rejects_out_of_range_page(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919222222225")
    resp = await client.post(
        "/api/v1/print/jobs/estimate",
        headers=headers,
        json={
            "page_count": 3,
            "selected_pages": [1, 4],
            "color_mode": "bw",
            "copies": 1,
            "coins_to_redeem": 0,
        },
    )
    assert resp.status_code == 400


# ── Submit ────────────────────────────────────────────────────────────────────

async def test_submit_creates_queued_job_with_4_digit_otp(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919333333331")
    up = await _upload_pdf(client, headers, pages=2)
    resp = await client.post(
        "/api/v1/print/jobs",
        headers=headers,
        json={
            "upload_id": up["upload_id"],
            "selected_pages": [1, 2],
            "color_mode": "bw",
            "copies": 1,
            "coins_to_redeem": 0,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    job = body["job"]
    assert job["status"] == "queued"
    assert len(job["pickup_otp"]) == 4 and job["pickup_otp"].isdigit()
    assert body["breakdown"]["subtotal"] == 4.0


async def test_submit_rejects_already_submitted_upload(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919333333332")
    up = await _upload_pdf(client, headers, pages=1)
    payload = {
        "upload_id": up["upload_id"],
        "selected_pages": [1],
        "color_mode": "bw",
        "copies": 1,
        "coins_to_redeem": 0,
    }
    await client.post("/api/v1/print/jobs", headers=headers, json=payload)
    resp = await client.post("/api/v1/print/jobs", headers=headers, json=payload)
    assert resp.status_code == 400


# ── List / get / cancel ───────────────────────────────────────────────────────

async def test_list_jobs_is_scoped_to_user(client, conn, redis, print_storage):
    h1, _ = await _login(client, conn, redis, "+919444444441")
    h2, _ = await _login(client, conn, redis, "+919444444442")
    await _upload_pdf(client, h1, pages=1)
    resp1 = await client.get("/api/v1/print/jobs", headers=h1)
    resp2 = await client.get("/api/v1/print/jobs", headers=h2)
    assert len(resp1.json()) == 1
    assert resp2.json() == []


async def test_cancel_queued_job_deletes_file(client, conn, redis, print_storage):
    headers, _ = await _login(client, conn, redis, "+919444444443")
    up = await _upload_pdf(client, headers, pages=1)
    await client.post(
        "/api/v1/print/jobs",
        headers=headers,
        json={
            "upload_id": up["upload_id"],
            "selected_pages": [1],
            "color_mode": "bw",
            "copies": 1,
            "coins_to_redeem": 0,
        },
    )
    file_path = Path(print_storage / f"{up['upload_id']}.pdf")
    assert file_path.exists()

    resp = await client.delete(f"/api/v1/print/jobs/{up['upload_id']}", headers=headers)
    assert resp.status_code == 204
    assert not file_path.exists()


# ── Device (Raspberry Pi) ─────────────────────────────────────────────────────

async def test_device_endpoints_require_key(client, print_storage):
    # DEVICE_API_KEY not set here → endpoint disabled
    resp = await client.get("/api/v1/print/device/jobs")
    assert resp.status_code == 403


async def test_device_endpoint_rejects_wrong_key(client, print_storage, device_key):
    resp = await client.get(
        "/api/v1/print/device/jobs",
        headers={"X-Device-Key": "wrong"},
    )
    assert resp.status_code == 403


async def test_device_queue_claims_jobs(client, conn, redis, print_storage, device_key):
    headers, _ = await _login(client, conn, redis, "+919555555551")
    up = await _upload_pdf(client, headers, pages=1)
    await client.post(
        "/api/v1/print/jobs",
        headers=headers,
        json={
            "upload_id": up["upload_id"],
            "selected_pages": [1],
            "color_mode": "bw",
            "copies": 1,
            "coins_to_redeem": 0,
        },
    )
    resp = await client.get(
        "/api/v1/print/device/jobs",
        headers={"X-Device-Key": device_key},
    )
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == up["upload_id"]

    row = await conn.fetchrow("SELECT status FROM print_jobs WHERE id = $1", up["upload_id"])
    assert row["status"] == "printing"


async def test_device_printed_deletes_file_and_sends_push(client, conn, redis, print_storage, device_key):
    headers, _ = await _login(client, conn, redis, "+919555555552")
    up = await _upload_pdf(client, headers, pages=1)
    await client.post(
        "/api/v1/print/jobs",
        headers=headers,
        json={
            "upload_id": up["upload_id"],
            "selected_pages": [1],
            "color_mode": "bw",
            "copies": 1,
            "coins_to_redeem": 0,
        },
    )
    # Move to printing
    await client.get("/api/v1/print/device/jobs", headers={"X-Device-Key": device_key})

    file_path = Path(print_storage / f"{up['upload_id']}.pdf")
    assert file_path.exists()

    with patch("app.routers.print.send_print_ready", new_callable=AsyncMock) as push:
        resp = await client.post(
            f"/api/v1/print/device/jobs/{up['upload_id']}/printed",
            headers={"X-Device-Key": device_key},
        )
    assert resp.status_code == 204
    assert not file_path.exists()
    push.assert_awaited_once()

    row = await conn.fetchrow(
        "SELECT status, storage_path FROM print_jobs WHERE id = $1", up["upload_id"]
    )
    assert row["status"] == "printed"
    assert row["storage_path"] is None


# ── Admin pickup ──────────────────────────────────────────────────────────────

async def test_admin_lookup_and_collect(client, conn, redis, print_storage, device_key):
    user_headers, _ = await _login(client, conn, redis, "+919666666661")
    admin_headers, _ = await _login(client, conn, redis, "+919666666662", role="admin")

    up = await _upload_pdf(client, user_headers, pages=2)
    submit = await client.post(
        "/api/v1/print/jobs",
        headers=user_headers,
        json={
            "upload_id": up["upload_id"],
            "selected_pages": [1, 2],
            "color_mode": "color",
            "copies": 1,
            "coins_to_redeem": 0,
        },
    )
    otp = submit.json()["job"]["pickup_otp"]

    # Move through printing → printed
    await client.get("/api/v1/print/device/jobs", headers={"X-Device-Key": device_key})
    with patch("app.routers.print.send_print_ready", new_callable=AsyncMock):
        await client.post(
            f"/api/v1/print/device/jobs/{up['upload_id']}/printed",
            headers={"X-Device-Key": device_key},
        )

    # Admin looks up by OTP
    resp = await client.post(
        "/api/v1/admin/print/lookup",
        headers=admin_headers,
        json={"pickup_otp": otp},
    )
    assert resp.status_code == 200
    assert resp.json()["breakdown"]["final_amount"] == 20.0  # 2 pages * 10

    # Admin marks collected
    resp = await client.post(
        f"/api/v1/admin/print/jobs/{up['upload_id']}/collect",
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["final_amount"] == 20.0
    assert body["transaction_id"]
    # Coins earned: floor(20 * 5 / 100) = 1
    assert body["coins_earned"] == 1

    row = await conn.fetchrow(
        "SELECT status, transaction_id FROM print_jobs WHERE id = $1", up["upload_id"]
    )
    assert row["status"] == "collected"
    assert row["transaction_id"] == body["transaction_id"]


async def test_admin_collect_rejects_non_printed(client, conn, redis, print_storage):
    user_headers, _ = await _login(client, conn, redis, "+919666666663")
    admin_headers, _ = await _login(client, conn, redis, "+919666666664", role="admin")
    up = await _upload_pdf(client, user_headers, pages=1)
    await client.post(
        "/api/v1/print/jobs",
        headers=user_headers,
        json={
            "upload_id": up["upload_id"],
            "selected_pages": [1],
            "color_mode": "bw",
            "copies": 1,
            "coins_to_redeem": 0,
        },
    )
    # Still in 'queued', not 'printed' → should reject
    resp = await client.post(
        f"/api/v1/print/jobs/{up['upload_id']}/collect",
        headers=admin_headers,
    )
    assert resp.status_code == 404  # endpoint is under /admin/print/...
    resp = await client.post(
        f"/api/v1/admin/print/jobs/{up['upload_id']}/collect",
        headers=admin_headers,
    )
    assert resp.status_code == 400


# ── Housekeeping ──────────────────────────────────────────────────────────────

async def test_purge_abandoned_drafts(client, conn, redis, print_storage):
    from app.services.print import purge_abandoned_drafts

    headers, _ = await _login(client, conn, redis, "+919777777771")
    up = await _upload_pdf(client, headers, pages=1)
    file_path = Path(print_storage / f"{up['upload_id']}.pdf")
    assert file_path.exists()

    # Age the draft past the TTL
    old = utcnow() - timedelta(hours=settings.PRINT_DRAFT_TTL_HOURS + 1)
    await conn.execute("UPDATE print_jobs SET created_at = $1 WHERE id = $2", old, up["upload_id"])

    removed = await purge_abandoned_drafts(conn)
    assert removed == 1
    assert not file_path.exists()
    row = await conn.fetchrow("SELECT id FROM print_jobs WHERE id = $1", up["upload_id"])
    assert row is None
