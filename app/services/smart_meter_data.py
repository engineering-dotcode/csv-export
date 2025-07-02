from datetime import datetime, timedelta
import random
from typing import Generator, Dict, Any

def generate_smart_meter_data(
    smart_meter_id: str,
    start_datetime: datetime,
    end_datetime: datetime,
    interval_minutes: int = 1
) -> Generator[Dict[str, Any], None, None]:
    
    base_voltage = 230.0
    base_power = 2.0
    
    current_time = start_datetime
    
    while current_time <= end_datetime:
        hour = current_time.hour
        
        # Peak hours (morning and evening)
        if 6 <= hour <= 9 or 17 <= hour <= 22:
            power_multiplier = random.uniform(1.5, 2.5)
        # Night hours
        elif 23 <= hour or hour <= 5:
            power_multiplier = random.uniform(0.3, 0.8)
        # Regular hours
        else:
            power_multiplier = random.uniform(0.8, 1.5)
        
        power_kw = base_power * power_multiplier + random.uniform(-0.2, 0.2)
        voltage_v = base_voltage + random.uniform(-5, 5)
        current_a = (power_kw * 1000) / voltage_v
        energy_kwh = (power_kw * interval_minutes) / 60
        
        yield {
            "timestamp": current_time.isoformat() + "Z",
            "smart_meter_id": smart_meter_id,
            "energy_kwh": round(energy_kwh, 3),
            "power_kw": round(power_kw, 3),
            "voltage_v": round(voltage_v, 1),
            "current_a": round(current_a, 2)
        }
        
        current_time += timedelta(minutes=interval_minutes)

def validate_smart_meter_id(smart_meter_id: str) -> bool:

    return bool(smart_meter_id) and smart_meter_id[0].isdigit() 