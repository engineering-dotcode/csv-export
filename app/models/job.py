from sqlalchemy import Column, String, DateTime, Integer, BigInteger, Text, types
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from ..core.database import Base
import uuid
from datetime import datetime, timezone
import enum

UUID = PostgresUUID

class JobStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class ExportFormat(str, enum.Enum):
    CSV = "csv"
    JSON = "json"
    XML = "xml"

JobStatusEnum = SQLEnum(
    'pending', 'in_progress', 'completed', 'failed',
    name='jobstatus',
    create_constraint=False
)

ExportFormatEnum = SQLEnum(
    'csv', 'json', 'xml',
    name='exportformat',
    create_constraint=False
)

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    smart_meter_id = Column(String, nullable=False)
    start_datetime = Column(DateTime(timezone=True), nullable=False)
    end_datetime = Column(DateTime(timezone=True), nullable=False)
    status = Column(JobStatusEnum, nullable=False, default=JobStatus.PENDING.value)
    format = Column(ExportFormatEnum, nullable=False, default=ExportFormat.CSV.value)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    file_path = Column(String)
    error_message = Column(Text)
    error_code = Column(String)
    record_count = Column(Integer)
    file_size_bytes = Column(BigInteger)
    progress_percentage = Column(Integer, default=0)
    task_id = Column(String) 