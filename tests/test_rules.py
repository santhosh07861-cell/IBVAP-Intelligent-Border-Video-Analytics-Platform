import pytest
from event_engine.rules.virtual_fence import point_in_polygon, line_intersection

def test_point_in_polygon():
    square = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
    inside_point = (0.5, 0.5)
    outside_point = (0.05, 0.5)

    assert point_in_polygon(inside_point, square) is True
    assert point_in_polygon(outside_point, square) is False

def test_line_intersection():
    p1 = (0.0, 0.5)
    p2 = (1.0, 0.5)
    q1 = (0.5, 0.0)
    q2 = (0.5, 1.0)

    assert line_intersection(p1, p2, q1, q2) is True

    # Parallel lines
    r1 = (0.0, 0.8)
    r2 = (1.0, 0.8)
    assert line_intersection(p1, p2, r1, r2) is False
