from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc
from uuid import UUID
import os
from datetime import datetime, timezone
from typing import Optional, Union
from celery.result import AsyncResult

from ..core.database import get_db
from ..models.job import Job, JobStatus, ExportFormat
from ..schemas.job import (
    ExportRequest, ExportResponse, JobStatusResponse, 
    JobNotFoundResponse, FileInfo, ErrorInfo,
    JobHistoryResponse, JobHistoryItem
)
from ..tasks.export_tasks import process_export

# Helper for tests
async def execute_query(db: Union[AsyncSession, Session], query):
    if isinstance(db, AsyncSession):
        return await db.execute(query)
    else:
        return db.execute(query)

async def commit_db(db: Union[AsyncSession, Session]):
    if isinstance(db, AsyncSession):
        await db.commit()
    else:
        db.commit()

async def refresh_obj(db: Union[AsyncSession, Session], obj):
    if isinstance(db, AsyncSession):
        await db.refresh(obj)
    else:
        db.refresh(obj)

router = APIRouter(prefix="/api/export", tags=["export"])

@router.post("/csv", response_model=ExportResponse)
async def create_export(request: ExportRequest, db: Union[AsyncSession, Session] = Depends(get_db)):
    start_dt = request.start_datetime
    end_dt = request.end_datetime
    
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    
    job = Job(
        smart_meter_id=request.smart_meter_id,
        start_datetime=start_dt,
        end_datetime=end_dt,
        format=request.format or ExportFormat.CSV,
        status=JobStatus.PENDING.value
    )
    
    db.add(job)
    await commit_db(db)
    await refresh_obj(db, job)
    
    # Queue task
    task = process_export.delay(str(job.id))
    
    return ExportResponse(
        job_id=str(job.id),
        status=JobStatus.PENDING.value,
        message="Export job created successfully"
    )

@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: UUID, db: Union[AsyncSession, Session] = Depends(get_db)):
    result = await execute_query(db, select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=JobNotFoundResponse(
                status="not_found",
                message=f"Job with ID '{job_id}' not found"
            ).model_dump()
        )
    
    response = JobStatusResponse(
        job_id=job.id,
        status=job.status,
        message=get_status_message(job.status),
        created_at=job.created_at,
        updated_at=job.updated_at,
        progress_percentage=job.progress_percentage if job.status == JobStatus.IN_PROGRESS else None
    )
    
    if job.status == JobStatus.COMPLETED and job.file_path:
        filename = os.path.basename(job.file_path)
        response.file_info = FileInfo(
            filename=filename,
            download_url=f"/api/export/download/{job.id}",
            file_size_bytes=job.file_size_bytes,
            record_count=job.record_count,
            export_period={
                "start": job.start_datetime,
                "end": job.end_datetime
            }
        )
    
    elif job.status == JobStatus.FAILED and job.error_message:
        response.error = ErrorInfo(
            code=job.error_code or "EXPORT_FAILED",
            message=job.error_message,
            details=f"Export failed for smart meter {job.smart_meter_id}"
        )
    
    return response

@router.get("/download/{job_id}")
async def download_file(job_id: UUID, db: Union[AsyncSession, Session] = Depends(get_db)):
    result = await execute_query(db, select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != JobStatus.COMPLETED or not job.file_path:
        raise HTTPException(status_code=400, detail="Export not ready or failed")
    
    if not os.path.exists(job.file_path):
        raise HTTPException(status_code=404, detail="Export file not found")
    
    filename = os.path.basename(job.file_path)
    
    if job.file_path.endswith('.gz'):
        def iterfile():
            with open(job.file_path, 'rb') as f:
                yield from f
        
        headers = {
            'Content-Encoding': 'gzip',
            'Content-Disposition': f'attachment; filename="{filename[:-3]}"'
        }
        
        media_type = get_media_type(filename[:-3])
        
        return StreamingResponse(
            iterfile(),
            media_type=media_type,
            headers=headers
        )
    else:
        return FileResponse(
            job.file_path,
            filename=filename,
            media_type=get_media_type(filename)
        )

@router.get("/history/{smart_meter_id}", response_model=JobHistoryResponse)
async def get_export_history(
    smart_meter_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Union[AsyncSession, Session] = Depends(get_db)
):
    count_result = await execute_query(db,
        select(Job).where(Job.smart_meter_id == smart_meter_id)
    )
    total_count = len(count_result.scalars().all())
    
    result = await execute_query(db,
        select(Job)
        .where(Job.smart_meter_id == smart_meter_id)
        .order_by(desc(Job.created_at))
        .limit(limit)
        .offset(offset)
    )
    jobs = result.scalars().all()
    
    exports = []
    for job in jobs:
        item = JobHistoryItem(
            job_id=job.id,
            smart_meter_id=job.smart_meter_id,
            status=job.status,
            format=job.format,
            created_at=job.created_at,
            updated_at=job.updated_at,
            start_datetime=job.start_datetime,
            end_datetime=job.end_datetime
        )
        
        if job.status == JobStatus.COMPLETED and job.file_path:
            item.file_info = FileInfo(
                filename=os.path.basename(job.file_path),
                download_url=f"/api/export/download/{job.id}",
                file_size_bytes=job.file_size_bytes,
                record_count=job.record_count,
                export_period={
                    "start": job.start_datetime,
                    "end": job.end_datetime
                }
            )
        
        exports.append(item)
    
    return JobHistoryResponse(
        smart_meter_id=smart_meter_id,
        total_exports=total_count,
        exports=exports
    )

def get_status_message(status: JobStatus) -> str:
    messages = {
        JobStatus.PENDING: "Job is being processed",
        JobStatus.IN_PROGRESS: "Job is being processed",
        JobStatus.COMPLETED: "Export completed successfully",
        JobStatus.FAILED: "Export failed"
    }
    return messages.get(status, "Unknown status")

def get_media_type(filename: str) -> str:
    if filename.endswith('.csv'):
        return 'text/csv'
    elif filename.endswith('.json'):
        return 'application/json'
    elif filename.endswith('.xml'):
        return 'application/xml'
    else:
        return 'application/octet-stream' 