from celery import Task
from ..celery_app import celery_app
from ..core.database import sync_session_maker
from ..models.job import Job, JobStatus
from ..services.smart_meter_data import generate_smart_meter_data, validate_smart_meter_id
from ..core.config import settings
import csv
import json
import xml.etree.ElementTree as ET
import xml.dom.minidom
import os
import gzip
from datetime import datetime

class ExportTask(Task):
    def update_progress(self, job_id: str, percentage: int):
        with sync_session_maker() as db:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.progress_percentage = percentage
                job.updated_at = datetime.utcnow()
                db.commit()

@celery_app.task(bind=True, base=ExportTask)
def process_export(self, job_id: str):
    with sync_session_maker() as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        
        try:
            job.status = JobStatus.IN_PROGRESS
            job.updated_at = datetime.utcnow()
            db.commit()
            
            if not validate_smart_meter_id(job.smart_meter_id):
                raise ValueError(f"Smart meter with ID '{job.smart_meter_id}' not found")
            
            data = list(generate_smart_meter_data(
                job.smart_meter_id,
                job.start_datetime,
                job.end_datetime
            ))
            
            total_records = len(data)
            
            date_format = "%Y%m%d"
            filename_base = f"smart_meter_{job.smart_meter_id}_{job.start_datetime.strftime(date_format)}_{job.end_datetime.strftime(date_format)}"
            
            if job.format == "csv":
                file_path = export_to_csv(data, filename_base, job_id, self)
            elif job.format == "json":
                file_path = export_to_json(data, filename_base, job_id, self)
            elif job.format == "xml":
                file_path = export_to_xml(data, filename_base, job_id, self)
            else:
                raise ValueError(f"Unsupported format: {job.format}")
            
            # Job success
            file_size = os.path.getsize(file_path)
            job.status = JobStatus.COMPLETED
            job.file_path = file_path
            job.record_count = total_records
            job.file_size_bytes = file_size
            job.progress_percentage = 100
            job.updated_at = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            # Job failure
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.updated_at = datetime.utcnow()
            
            if "not found" in str(e).lower():
                job.error_code = "SMART_METER_NOT_FOUND"
            else:
                job.error_code = "EXPORT_FAILED"
            
            db.commit()
            raise

def export_to_csv(data, filename_base, job_id, task):
    file_path = os.path.join(settings.export_directory, f"{filename_base}.csv")
    gz_file_path = f"{file_path}.gz"
    
    total_records = len(data)
    
    with gzip.open(gz_file_path, 'wt', encoding='utf-8') as gz_file:
        if total_records > 0:
            fieldnames = data[0].keys()
            writer = csv.DictWriter(gz_file, fieldnames=fieldnames)
            writer.writeheader()
            
            for idx, row in enumerate(data):
                writer.writerow(row)
                if idx % 100 == 0:
                    progress = int((idx / total_records) * 90) + 10
                    task.update_progress(job_id, progress)
    
    return gz_file_path

def export_to_json(data, filename_base, job_id, task):
    file_path = os.path.join(settings.export_directory, f"{filename_base}.json")
    gz_file_path = f"{file_path}.gz"
    
    export_data = {
        "metadata": {
            "export_date": datetime.utcnow().isoformat() + "Z",
            "total_records": len(data),
            "format": "json"
        },
        "data": data
    }
    
    with gzip.open(gz_file_path, 'wt', encoding='utf-8') as gz_file:
        json.dump(export_data, gz_file, indent=2)
    
    task.update_progress(job_id, 95)
    return gz_file_path

def export_to_xml(data, filename_base, job_id, task):
    file_path = os.path.join(settings.export_directory, f"{filename_base}.xml")
    gz_file_path = f"{file_path}.gz"
    
    root = ET.Element("smart_meter_export")
    
    metadata = ET.SubElement(root, "metadata")
    ET.SubElement(metadata, "export_date").text = datetime.utcnow().isoformat() + "Z"
    ET.SubElement(metadata, "total_records").text = str(len(data))
    
    readings = ET.SubElement(root, "readings")
    
    total_records = len(data)
    for idx, row in enumerate(data):
        reading = ET.SubElement(readings, "reading")
        for key, value in row.items():
            ET.SubElement(reading, key).text = str(value)
        
        if idx % 100 == 0:
            progress = int((idx / total_records) * 90) + 10
            task.update_progress(job_id, progress)
    
    xml_str = ET.tostring(root, encoding='unicode')
    dom = xml.dom.minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ")
    
    with gzip.open(gz_file_path, 'wt', encoding='utf-8') as gz_file:
        gz_file.write(pretty_xml)
    
    task.update_progress(job_id, 95)
    return gz_file_path 