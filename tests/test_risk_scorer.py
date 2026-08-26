import pytest
from event_engine.risk.scorer import OperationalRiskScorer

def test_risk_scorer_critical():
    scorer = OperationalRiskScorer()
    conditions = {
        "night_mode": True,       # +20
        "restricted_zone": True,  # +30
        "fence_crossing": True,   # +30
        "loitering": True         # +10
    }
    result = scorer.calculate_score(conditions)
    assert result["risk_score"] == 90.0
    assert result["severity"] == "CRITICAL"

def test_risk_scorer_low():
    scorer = OperationalRiskScorer()
    conditions = {
        "night_mode": False,
        "restricted_zone": False,
        "fence_crossing": False,
        "loitering": True         # +10
    }
    result = scorer.calculate_score(conditions)
    assert result["risk_score"] == 10.0
    assert result["severity"] == "INFO"
