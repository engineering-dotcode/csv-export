from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
import logging

from .api import export
from .core.database import async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    yield
    logger.info("Shutting down...")
    await async_engine.dispose()

app = FastAPI(
    title="Smart Meter Export API",
    lifespan=lifespan
)

app.include_router(export.router)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"]
        })
    
    return JSONResponse(
        status_code=422,
        content={"detail": errors}
    )

@app.get("/")
async def root():
    return {
        "service": "Smart Meter Export API",
        "endpoints": {
            "export": "/api/export/csv",
            "status": "/api/export/status/{job_id}",
            "download": "/api/export/download/{job_id}",
            "history": "/api/export/history/{smart_meter_id}"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"} 