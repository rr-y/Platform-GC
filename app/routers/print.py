import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.database import get_conn
from app.deps import get_current_user, require_device
from app.schemas import (
    AdminPrintLookupOut,
    DeviceJobOut,
    DeviceJobsOut,
    PrintJobCreate,
    PrintJobEstimateIn,
    PrintJobOut,
    PrintJobSubmitOut,
    PrintPriceBreakdown,
    PrintUploadOut,
)
from app.services import print as print_service
from app.services.coins import get_balance
from app.services.notifications import send_print_ready

router = APIRouter(prefix="/print", tags=["print"])


# ── User endpoints ───────────────────────────────────────────────────────────

@router.post("/upload", response_model=PrintUploadOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        return await print_service.save_upload(current_user["id"], file, conn)
    except print_service.PrintError as e:
        msg = str(e)
        if "exceeds" in msg.lower():
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=msg)
        if "unsupported" in msg.lower():
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


@router.post("/jobs/estimate", response_model=PrintPriceBreakdown)
async def estimate(
    body: PrintJobEstimateIn,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    balance = await get_balance(current_user["id"], conn)
    try:
        return print_service.calculate_breakdown(
            selected_pages=body.selected_pages,
            page_count=body.page_count,
            color_mode=body.color_mode,
            copies=body.copies,
            coins_to_redeem=body.coins_to_redeem,
            user_balance=balance,
        )
    except print_service.PrintError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/jobs", response_model=PrintJobSubmitOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: PrintJobCreate,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        submitted = await print_service.submit_job(
            user_id=current_user["id"],
            upload_id=body.upload_id,
            selected_pages=body.selected_pages,
            color_mode=body.color_mode,
            copies=body.copies,
            coins_to_redeem=body.coins_to_redeem,
            conn=conn,
        )
    except print_service.PrintError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    job = await print_service.get_user_job(submitted["job_id"], current_user["id"], conn)
    return {"job": job, "breakdown": submitted["breakdown"]}


@router.get("/jobs", response_model=list[PrintJobOut])
async def list_jobs(
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    return await print_service.list_user_jobs(current_user["id"], conn)


@router.get("/jobs/{job_id}", response_model=PrintJobOut)
async def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    job = await print_service.get_user_job(job_id, current_user["id"], conn)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        await print_service.cancel_job(job_id, current_user["id"], conn)
    except print_service.PrintError as e:
        msg = str(e)
        code = status.HTTP_404_NOT_FOUND if "not found" in msg.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg)


# ── Device (Raspberry Pi) endpoints ──────────────────────────────────────────

@router.get(
    "/device/jobs",
    response_model=DeviceJobsOut,
    dependencies=[Depends(require_device)],
)
async def device_queue(
    request: Request,
    conn: asyncpg.Connection = Depends(get_conn),
):
    jobs = await print_service.claim_queue(conn)
    base = str(request.base_url).rstrip("/") + request.scope.get("root_path", "")
    return {
        "jobs": [
            DeviceJobOut(
                job_id=j["job_id"],
                file_name=j["file_name"],
                mime_type=j["mime_type"],
                selected_pages=j["selected_pages"],
                color_mode=j["color_mode"],
                copies=j["copies"],
                file_url=f"{base}/print/device/jobs/{j['job_id']}/file",
            )
            for j in jobs
        ]
    }


@router.get(
    "/device/jobs/{job_id}/file",
    dependencies=[Depends(require_device)],
)
async def device_download(
    job_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
):
    job = await print_service.get_job_for_device(job_id, conn)
    if not job or not job["storage_path"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not available")
    return FileResponse(
        path=job["storage_path"],
        media_type=job["mime_type"],
        filename=job["file_name"],
    )


@router.post(
    "/device/jobs/{job_id}/printed",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_device)],
)
async def device_printed(
    job_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        result = await print_service.mark_printed(job_id, conn)
    except print_service.PrintError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        await send_print_ready(
            mobile=result["mobile_number"],
            name=result["name"],
            pickup_otp=result["pickup_otp"],
            final_amount=result["final_amount"],
            push_token=result["push_token"],
        )
    except Exception:
        # Notification failure is not fatal — the job is still printed and the
        # user can still collect it using the OTP shown at submit time.
        pass


@router.post(
    "/device/jobs/{job_id}/failed",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_device)],
)
async def device_failed(
    job_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        new_status = await print_service.mark_failed(job_id, conn)
    except print_service.PrintError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"status": new_status}
