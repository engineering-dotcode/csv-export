# Smart Meter Export API

API for exporting smart meter data in various formats (CSV, JSON, XML).

## Quick Start

```bash
docker compose up
```

The API will be available at http://localhost:8000
Swagger docs will be available at http://localhost:8000/docs

## API Endpoints

- `POST /api/export/csv` - Create export job
- `GET /api/export/status/{job_id}` - Check job status
- `GET /api/export/download/{job_id}` - Download exported file
- `GET /api/export/history/{smart_meter_id}` - View export history

## Features

- Async job processing with progress tracking
- Multiple export formats (CSV, JSON, XML)
- File compression (gzip)
- Export history tracking
- Comprehensive error handling

## Tech Stack

- FastAPI
- PostgreSQL
- Redis
- Celery
- Docker 