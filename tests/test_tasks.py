import pytest
import os
import gzip
import csv
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import tempfile

from app.tasks.export_tasks import export_to_csv, export_to_json, export_to_xml
from app.tasks.export_tasks import process_export as process_export_task
from app.models.job import Job, JobStatus
from app.services.smart_meter_data import generate_smart_meter_data, validate_smart_meter_id

process_export_func = process_export_task.__wrapped__.__func__

class TestSmartMeterDataService:
    def test_validate_smart_meter_id_valid(self):
        assert validate_smart_meter_id("123") == True
        assert validate_smart_meter_id("456abc") == True
        assert validate_smart_meter_id("789_meter") == True
    
    def test_validate_smart_meter_id_invalid(self):
        assert validate_smart_meter_id("abc123") == False
        assert validate_smart_meter_id("_meter") == False
        assert validate_smart_meter_id("") == False
        assert validate_smart_meter_id("meter123") == False
    
    def test_generate_smart_meter_data(self):
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = datetime.now(timezone.utc)
        
        data = list(generate_smart_meter_data("123", start, end, interval_minutes=30))
        
        assert len(data) == 3
        for record in data:
            assert "timestamp" in record
            assert "smart_meter_id" in record
            assert record["smart_meter_id"] == "123"
            assert "energy_kwh" in record
            assert "power_kw" in record
            assert "voltage_v" in record
            assert "current_a" in record
            assert record["power_kw"] > 0
            assert 225 <= record["voltage_v"] <= 235

class TestExportFunctions:
    @pytest.fixture
    def sample_data(self):
        return [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "smart_meter_id": "123",
                "energy_kwh": 0.5,
                "power_kw": 2.1,
                "voltage_v": 230.1,
                "current_a": 9.1
            },
            {
                "timestamp": "2024-01-01T01:00:00Z",
                "smart_meter_id": "123",
                "energy_kwh": 0.6,
                "power_kw": 2.3,
                "voltage_v": 230.2,
                "current_a": 9.2
            }
        ]
    
    def test_export_to_csv(self, sample_data):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('app.tasks.export_tasks.settings') as mock_settings:
                mock_settings.export_directory = tmpdir
                
                mock_task = MagicMock()
                mock_task.update_progress = MagicMock()
                
                file_path = export_to_csv(sample_data, "test_export", "job123", mock_task)
                
                assert file_path.endswith(".csv.gz")
                assert os.path.exists(file_path)
                
                with gzip.open(file_path, 'rt') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    assert len(rows) == 2
                    assert rows[0]["smart_meter_id"] == "123"
                    assert float(rows[0]["energy_kwh"]) == 0.5
    
    def test_export_to_json(self, sample_data):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('app.tasks.export_tasks.settings') as mock_settings:
                mock_settings.export_directory = tmpdir
                
                mock_task = MagicMock()
                mock_task.update_progress = MagicMock()
                
                file_path = export_to_json(sample_data, "test_export", "job123", mock_task)
                
                assert file_path.endswith(".json.gz")
                assert os.path.exists(file_path)
                
                with gzip.open(file_path, 'rt') as f:
                    data = json.load(f)
                    assert "metadata" in data
                    assert data["metadata"]["total_records"] == 2
                    assert "data" in data
                    assert len(data["data"]) == 2
    
    def test_export_to_xml(self, sample_data):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('app.tasks.export_tasks.settings') as mock_settings:
                mock_settings.export_directory = tmpdir
                
                mock_task = MagicMock()
                mock_task.update_progress = MagicMock()
                
                file_path = export_to_xml(sample_data, "test_export", "job123", mock_task)
                
                assert file_path.endswith(".xml.gz")
                assert os.path.exists(file_path)
                
                with gzip.open(file_path, 'rt') as f:
                    content = f.read()
                    root = ET.fromstring(content)
                    assert root.tag == "smart_meter_export"
                    readings = root.find("readings")
                    assert len(readings.findall("reading")) == 2

class TestProcessExportTask:
    @pytest.fixture
    def mock_db_session(self):
        with patch('app.tasks.export_tasks.sync_session_maker') as mock:
            session = MagicMock()
            mock.return_value.__enter__.return_value = session
            yield session
    
    def test_process_export_success(self, mock_db_session):
        job = Job(
            id="123e4567-e89b-12d3-a456-426614174000",
            smart_meter_id="123",
            start_datetime=datetime.now(timezone.utc) - timedelta(hours=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.PENDING,
            format="csv"
        )
        
        mock_db_session.query.return_value.filter.return_value.first.return_value = job
        
        with patch('app.tasks.export_tasks.settings') as mock_settings:
            mock_settings.export_directory = "/tmp"
            
            with patch('app.tasks.export_tasks.export_to_csv') as mock_export:
                mock_export.return_value = "/tmp/test.csv.gz"
                
                with patch('os.path.getsize') as mock_size:
                    mock_size.return_value = 1024
                    
                    mock_self = MagicMock()
                    mock_self.update_progress = MagicMock()
                    
                    process_export_func(mock_self, str(job.id))
                    
                    assert job.status == JobStatus.COMPLETED
                    assert job.file_path == "/tmp/test.csv.gz"
                    assert job.file_size_bytes == 1024
                    assert mock_db_session.commit.called
    
    def test_process_export_invalid_meter(self, mock_db_session):
        job = Job(
            id="123e4567-e89b-12d3-a456-426614174000",
            smart_meter_id="invalid_meter",
            start_datetime=datetime.now(timezone.utc) - timedelta(hours=1),
            end_datetime=datetime.now(timezone.utc),
            status=JobStatus.PENDING,
            format="csv"
        )
        
        mock_db_session.query.return_value.filter.return_value.first.return_value = job
        
        mock_self = MagicMock()
        mock_self.update_progress = MagicMock()
        
        with pytest.raises(ValueError) as exc_info:
            process_export_func(mock_self, str(job.id))
        
        assert "not found" in str(exc_info.value)
        assert job.status == JobStatus.FAILED
        assert job.error_code == "SMART_METER_NOT_FOUND"
        assert mock_db_session.commit.called
    
    def test_process_export_job_not_found(self, mock_db_session):
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        
        mock_self = MagicMock()
        
        result = process_export_func(mock_self, "nonexistent-job-id")
        assert result is None 