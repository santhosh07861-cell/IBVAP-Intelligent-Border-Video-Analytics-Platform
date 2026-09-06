import pytest
from event_engine.risk.scorer import OperationalRiskScorer

def test_risk_scorer_critical():
    custom_weights = {
        "night_mode": 20.0,
        "restricted_zone": 30.0,
        "fence_crossing": 30.0,
        "loitering": 10.0
    }
    scorer = OperationalRiskScorer(custom_weights=custom_weights)
    conditions = {
        "night_mode": True,
        "restricted_zone": True,
        "fence_crossing": True,
        "loitering": True
    }
    result = scorer.calculate_score(conditions)
    assert result["risk_score"] == 90.0
    assert result["severity"] == "CRITICAL"

def test_risk_scorer_low():
    custom_weights = {
        "loitering": 10.0
    }
    scorer = OperationalRiskScorer(custom_weights=custom_weights)
    conditions = {
        "night_mode": False,
        "restricted_zone": False,
        "fence_crossing": False,
        "loitering": True
    }
    result = scorer.calculate_score(conditions)
    assert result["risk_score"] == 10.0
    assert result["severity"] == "INFO"

