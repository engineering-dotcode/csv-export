from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from typing import Optional, Dict
from uuid import UUID
from ..models.job import JobStatus, ExportFormat

class ExportRequest(BaseModel):
    smart_meter_id: str = Field(..., min_length=1, json_schema_extra={"example": "123"})
    start_datetime: datetime = Field(..., json_schema_extra={"example": "2025-07-01T00:00:00.000Z"})
    end_datetime: datetime = Field(..., json_schema_extra={"example": "2025-07-02T23:59:59.999Z"})
    format: ExportFormat = ExportFormat.CSV
    
    @field_validator('start_datetime')
    def start_datetime_must_be_past(cls, v):
        now = datetime.now(timezone.utc)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v > now:
            raise ValueError('start_datetime must be in the past')
        return v
    
    @field_validator('end_datetime')
    def end_datetime_validation(cls, v, info):
        if 'start_datetime' in info.data:
            start_dt = info.data['start_datetime']
            
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            
            if v <= start_dt:
                raise ValueError('end_datetime must be after start_datetime')
            
            date_range = v - start_dt
            if date_range.days > 365:
                raise ValueError('Date range cannot exceed 365 days')
            if date_range.total_seconds() < 60:
                raise ValueError('Date range must be at least 1 minute')
        
        return v

class ExportResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    message: str

class FileInfo(BaseModel):
    filename: str
    download_url: str
    file_size_bytes: int
    record_count: int
    export_period: Dict[str, datetime]

class ErrorInfo(BaseModel):
    code: str
    message: str
    details: str

class JobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    message: str
    created_at: datetime
    updated_at: datetime
    file_info: Optional[FileInfo] = None
    error: Optional[ErrorInfo] = None
    progress_percentage: Optional[int] = None

class JobNotFoundResponse(BaseModel):
    status: str = "not_found"
    message: str

class JobHistoryItem(BaseModel):
    job_id: UUID
    smart_meter_id: str
    status: JobStatus
    format: ExportFormat
    created_at: datetime
    updated_at: datetime
    start_datetime: datetime
    end_datetime: datetime
    file_info: Optional[FileInfo] = None
    
class JobHistoryResponse(BaseModel):
    smart_meter_id: str
    total_exports: int
    exports: list[JobHistoryItem] 