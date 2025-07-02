from celery import Celery
from .core.config import settings

celery_app = Celery(
    "smartmeter_export",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.export_tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
) 