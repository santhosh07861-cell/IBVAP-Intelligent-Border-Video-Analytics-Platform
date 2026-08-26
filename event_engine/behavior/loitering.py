from datetime import datetime, time as dtime
from typing import Dict, Any, List

class BehavioralAnalyzer:
    def __init__(self, night_start_hour: int = 20, night_end_hour: int = 6):
        self.night_start_hour = night_start_hour
        self.night_end_hour = night_end_hour

    def is_night_time(self, dt: datetime = None) -> bool:
        if dt is None:
            dt = datetime.utcnow()
        hour = dt.hour
        if self.night_start_hour > self.night_end_hour:
            return hour >= self.night_start_hour or hour < self.night_end_hour
        return self.night_start_hour <= hour < self.night_end_hour

    def check_loitering(self, track_dwell_sec: float, threshold_sec: float = 10.0) -> bool:
        return track_dwell_sec >= threshold_sec

    def check_crowd(self, detection_count: int, threshold: int = 5) -> bool:
        return detection_count >= threshold
