from typing import Dict, Any

class OperationalRiskScorer:
    def __init__(self, custom_weights: Dict[str, float] = None):
        self.weights = {
            "night_mode": 20.0,
            "restricted_zone": 30.0,
            "fence_crossing": 30.0,
            "loitering": 10.0,
            "repeated_crossing": 15.0,
            "vehicle_stopping": 15.0,
            "crowd_threshold": 10.0
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
        elif score <= 40.0:
            severity = "LOW"
        elif score <= 60.0:
            severity = "MEDIUM"
        elif score <= 80.0:
            severity = "HIGH"
        else:
            severity = "CRITICAL"

        return {
            "risk_score": score,
            "severity": severity,
            "breakdown": breakdown
        }
