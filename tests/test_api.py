from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
import uuid
from unittest.mock import patch, MagicMock
import os
import tempfile
import gzip

from app.models.job import Job, JobStatus

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Smart Meter Export API"
    assert "endpoints" in data

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

class TestHappyPath:
    """Test 1: Happy path - Successful CSV export"""
    
    def test_successful_csv_export(self, client):
        export_data = {
            "smart_meter_id": "123",
            "start_datetime": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
            "end_datetime": (datetime.now(timezone.utc) - timedelta(days=6)).isoformat(),
            "format": "csv"
        }
        
        with patch('app.api.export.process_export.delay') as mock_task:
            response = client.post("/api/export/csv", json=export_data)
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert data["message"] == "Export job created successfully"
        assert mock_task.called
    
    def test_successful_json_export(self, client):
        export_data = {
            "smart_meter_id": "456",
            "start_datetime": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "end_datetime": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "format": "json"
        }
        
        with patch('app.api.export.process_export.delay'):
            response = client.post("/api/export/csv", json=export_data)
        
        assert response.status_code == 200
        assert response.json()["status"] == "pending"
    
    def test_successful_xml_export(self, client):
        export_data = {
            "smart_meter_id": "789",
            "start_datetime": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            "end_datetime": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "format": "xml"
        }
        
        with patch('app.api.export.process_export.delay'):
            response = client.post("/api/export/csv", json=export_data)
        
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

class TestErrorCases:
    """Test 2: Error cases - Invalid inputs, missing data"""
    
    def test_missing_required_fields(self, client):
        response = client.post("/api/export/csv", json={})
        assert response.status_code == 422
        
    def test_missing_smart_meter_id(self, client):
        response = client.post("/api/export/csv", json={
            "start_datetime": datetime.now(timezone.utc).isoformat(),
            "end_datetime": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        })
        assert response.status_code == 422
    
    def test_empty_smart_meter_id(self, client):
        response = client.post("/api/export/csv", json={
            "smart_meter_id": "",
            "start_datetime": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "end_datetime": datetime.now(timezone.utc).isoformat()
        })
        assert response.status_code == 422
    
    def test_start_datetime_in_future(self, client):
        response = client.post("/api/export/csv", json={
            "smart_meter_id": "123",
            "start_datetime": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "end_datetime": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        })
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("start_datetime must be in the past" in str(error) for error in errors)
    
    def test_end_before_start(self, client):
        response = client.post("/api/export/csv", json={
            "smart_meter_id": "123",
            "start_datetime": datetime.now(timezone.utc).isoformat(),
            "end_datetime": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        })
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("end_datetime must be after start_datetime" in str(error) for error in errors)
    
    def test_date_range_too_large(self, client):
        response = client.post("/api/export/csv", json={
            "smart_meter_id": "123",
            "start_datetime": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
            "end_datetime": datetime.now(timezone.utc).isoformat()
        })
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("Date range cannot exceed 365 days" in str(error) for error in errors)
    
    def test_date_range_too_small(self, client):
        now = datetime.now(timezone.utc)
        response = client.post("/api/export/csv", json={
            "smart_meter_id": "123",
            "start_datetime": now.isoformat(),
            "end_datetime": (now + timedelta(seconds=30)).isoformat()
        })
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("Date range must be at least 1 minute" in str(error) for error in errors)
    
    def test_invalid_datetime_format(self, client):
        response = client.post("/api/export/csv", json={
            "smart_meter_id": "123",
            "start_datetime": "2024-01-01",
            "end_datetime": "2024-01-02"
        })
        assert response.status_code == 422
    
    def test_job_not_found(self, client):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/export/status/{fake_id}")
        assert response.status_code == 404
        assert response.json()["detail"]["status"] == "not_found"

class TestJobLifecycle:
    """Test 3: Job lifecycle - Pending → Completed/Failed"""
    
    def test_job_status_pending(self, client, db_session):
        job = Job(
            smart_meter_id="123",
            start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.PENDING
        )
        db_session.add(job)
        db_session.commit()
        
        response = client.get(f"/api/export/status/{job.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["message"] == "Job is being processed"
        assert data["file_info"] is None
        assert data["error"] is None
    
    def test_job_status_in_progress(self, client, db_session):
        job = Job(
            smart_meter_id="123",
            start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.IN_PROGRESS,
            progress_percentage=45
        )
        db_session.add(job)
        db_session.commit()
        
        response = client.get(f"/api/export/status/{job.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["progress_percentage"] == 45
    
    def test_job_status_completed(self, client, db_session):
        job = Job(
            smart_meter_id="123",
            start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.COMPLETED,
            file_path="/app/exports/test_file.csv.gz",
            file_size_bytes=1024,
            record_count=100
        )
        db_session.add(job)
        db_session.commit()
        
        response = client.get(f"/api/export/status/{job.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["message"] == "Export completed successfully"
        assert "file_info" in data
        assert data["file_info"]["filename"] == "test_file.csv.gz"
        assert data["file_info"]["file_size_bytes"] == 1024
        assert data["file_info"]["record_count"] == 100
        assert f"/api/export/download/{job.id}" in data["file_info"]["download_url"]
    
    def test_job_status_failed(self, client, db_session):
        job = Job(
            smart_meter_id="999",
            start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.FAILED,
            error_message="Smart meter with ID '999' not found",
            error_code="SMART_METER_NOT_FOUND"
        )
        db_session.add(job)
        db_session.commit()
        
        response = client.get(f"/api/export/status/{job.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data
        assert data["error"]["code"] == "SMART_METER_NOT_FOUND"
        assert "999" in data["error"]["message"]

class TestFileDownload:
    """Test 4: File download - Correct file generation and download"""
    
    def test_download_completed_file(self, client, db_session):
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv.gz', delete=False) as tmp:
            with gzip.open(tmp.name, 'wt', encoding='utf-8') as gz_file:
                gz_file.write("timestamp,smart_meter_id,energy_kwh\n")
                gz_file.write("2024-01-01T00:00:00Z,123,0.5\n")
            
            job = Job(
                smart_meter_id="123",
                start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
                end_datetime=datetime.now(timezone.utc),
                status=JobStatus.COMPLETED,
                file_path=tmp.name,
                file_size_bytes=os.path.getsize(tmp.name),
                record_count=1
            )
            db_session.add(job)
            db_session.commit()
            
            response = client.get(f"/api/export/download/{job.id}")
            assert response.status_code == 200
            assert response.headers["content-encoding"] == "gzip"
            assert "attachment" in response.headers["content-disposition"]
            
            os.unlink(tmp.name)
    
    def test_download_job_not_found(self, client):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/export/download/{fake_id}")
        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]
    
    def test_download_pending_job(self, client, db_session):
        job = Job(
            smart_meter_id="123",
            start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.PENDING
        )
        db_session.add(job)
        db_session.commit()
        
        response = client.get(f"/api/export/download/{job.id}")
        assert response.status_code == 400
        assert "Export not ready or failed" in response.json()["detail"]
    
    def test_download_failed_job(self, client, db_session):
        job = Job(
            smart_meter_id="123",
            start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.FAILED,
            error_message="Export failed"
        )
        db_session.add(job)
        db_session.commit()
        
        response = client.get(f"/api/export/download/{job.id}")
        assert response.status_code == 400
        assert "Export not ready or failed" in response.json()["detail"]

class TestConcurrentRequests:
    """Test 5: Concurrent requests - Multiple simultaneous exports"""
    
    def test_multiple_export_requests(self, client):
        job_ids = []
        
        with patch('app.api.export.process_export.delay') as mock_task:
            # Create multiple export requests
            for i in range(5):
                export_data = {
                    "smart_meter_id": f"meter_{i}",
                    "start_datetime": (datetime.now(timezone.utc) - timedelta(days=i+1)).isoformat(),
                    "end_datetime": (datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
                    "format": "csv"
                }
                response = client.post("/api/export/csv", json=export_data)
                assert response.status_code == 200
                job_ids.append(response.json()["job_id"])
            
            # Verify queued
            assert mock_task.call_count == 5
        
        # Verify unique
        assert len(set(job_ids)) == 5
    
    def test_concurrent_status_checks(self, client, db_session):
        jobs = []
        for i in range(3):
            job = Job(
                smart_meter_id=f"meter_{i}",
                start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
                end_datetime=datetime.now(timezone.utc),
                status=JobStatus.PENDING if i == 0 else JobStatus.COMPLETED if i == 1 else JobStatus.IN_PROGRESS,
                progress_percentage=50 if i == 2 else None
            )
            db_session.add(job)
            jobs.append(job)
        db_session.commit()
        
        for i, job in enumerate(jobs):
            response = client.get(f"/api/export/status/{job.id}")
            assert response.status_code == 200
            data = response.json()
            if i == 0:
                assert data["status"] == "pending"
            elif i == 1:
                assert data["status"] == "completed"
            else:
                assert data["status"] == "in_progress"
                assert data["progress_percentage"] == 50

class TestExportHistory:
    """Bonus feature test: Export history"""
    
    def test_export_history(self, client, db_session):
        smart_meter_id = "meter_123"
        
        for i in range(3):
            job = Job(
                smart_meter_id=smart_meter_id,
                start_datetime=datetime.now(timezone.utc) - timedelta(days=i+2),
                end_datetime=datetime.now(timezone.utc) - timedelta(days=i+1),
                status=JobStatus.COMPLETED,
                file_path=f"/app/exports/export_{i}.csv.gz",
                file_size_bytes=1024 * (i + 1),
                record_count=100 * (i + 1)
            )
            db_session.add(job)
        
        # Add one for different meter
        other_job = Job(
            smart_meter_id="other_meter",
            start_datetime=datetime.now(timezone.utc) - timedelta(days=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.COMPLETED
        )
        db_session.add(other_job)
        db_session.commit()
        
        response = client.get(f"/api/export/history/{smart_meter_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["smart_meter_id"] == smart_meter_id
        assert data["total_exports"] == 3
        assert len(data["exports"]) == 3
        
        # Verify ordering (most recent first)
        for i, export in enumerate(data["exports"]):
            assert export["smart_meter_id"] == smart_meter_id
            assert export["status"] == "completed"
            assert export["file_info"]["file_size_bytes"] == 1024 * (3 - i)
    
    def test_export_history_pagination(self, client, db_session):
        smart_meter_id = "meter_456"
        
        for i in range(10):
            job = Job(
                smart_meter_id=smart_meter_id,
                start_datetime=datetime.now(timezone.utc) - timedelta(days=i+2),
                end_datetime=datetime.now(timezone.utc) - timedelta(days=i+1),
                status=JobStatus.COMPLETED
            )
            db_session.add(job)
        db_session.commit()
        
        response = client.get(f"/api/export/history/{smart_meter_id}?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["total_exports"] == 10
        assert len(data["exports"]) == 5
        
        response = client.get(f"/api/export/history/{smart_meter_id}?limit=5&offset=5")
        assert response.status_code == 200
        data = response.json()
        assert data["total_exports"] == 10
        assert len(data["exports"]) == 5 