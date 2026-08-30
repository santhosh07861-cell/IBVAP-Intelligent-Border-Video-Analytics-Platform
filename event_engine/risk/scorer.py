from typing import Dict, Any

class OperationalRiskScorer:
    def __init__(self, custom_weights: Dict[str, float] = None):
        self.weights = {
            "night_mode": 15.0,
            "restricted_zone": 40.0,
            "fence_crossing": 35.0,
            "loitering": 25.0,
            "unknown_person": 35.0,
            "repeated_crossing": 20.0,
            "vehicle_stopping": 20.0,
            "crowd_threshold": 15.0
        }
        if custom_weights:
            self.weights.update(custom_weights)

    def calculate_score(self, conditions: Dict[str, bool]) -> Dict[str, Any]:
        """
        Calculates Operational Risk Score (0-100) based on detected rule conditions.
        Returns dict containing score, severity string, and breakdown.
        """
        raw_score = 0.0
        breakdown = {}

        for key, active in conditions.items():
            if active and key in self.weights:
                w = self.weights[key]
                raw_score += w
                breakdown[key] = w

        score = min(100.0, max(0.0, round(raw_score, 1)))

        if score <= 20.0:
            severity = "INFO"
        elif score <= 45.0:
            severity = "LOW"
        elif score <= 65.0:
            severity = "MEDIUM"
        elif score <= 84.0:
            severity = "HIGH"
        else:
            severity = "CRITICAL"

        return {
            "risk_score": score,
            "severity": severity,
            "breakdown": breakdown
        }
