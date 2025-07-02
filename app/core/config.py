from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env")
    
    database_url: str = "postgresql://smartmeter:smartmeter123@localhost:5432/smartmeter_db"
    redis_url: str = "redis://localhost:6379"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    
    export_directory: str = "/app/exports"
    max_date_range_days: int = 365

settings = Settings() 