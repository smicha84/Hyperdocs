"""Tests for iterate.py — gap classification logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "obsolete"))
from iterate import classify_gaps


def test_classify_structural():
    """data_absent gaps → structural."""
    gaps = [
        {"field": "action_vector", "gap_type": "data_absent", "priority": "structural"},
        {"field": "confidence_signal", "gap_type": "data_absent", "priority": "structural"},
    ]
    fixable, needs_agent, structural = classify_gaps(gaps)
    assert len(structural) == 2
    assert len(fixable) == 0
    assert len(needs_agent) == 0


def test_classify_fixable():
    """ground_truth gaps → fixable_by_phase5."""
    gaps = [
        {"field": "ground_truth", "priority": "medium", "missing_values": ["5 unverified"]},
    ]
    fixable, needs_agent, structural = classify_gaps(gaps)
    assert len(fixable) == 1
    assert fixable[0]["field"] == "ground_truth"


def test_classify_needs_agent():
    """critical/high priority gaps → needs_agent."""
    gaps = [
        {"field": "semantic_primitives", "priority": "critical", "missing_values": ["entire file"]},
        {"field": "idea_graph.nodes", "priority": "high", "missing_values": ["need 7 more nodes"]},
    ]
    fixable, needs_agent, structural = classify_gaps(gaps)
    assert len(needs_agent) == 2
    assert len(fixable) == 0


def test_classify_mixed():
    """Mixed gaps are correctly separated."""
    gaps = [
        {"field": "action_vector", "gap_type": "data_absent", "priority": "structural"},
        {"field": "ground_truth", "priority": "medium"},
        {"field": "thread_extractions", "priority": "critical", "missing_values": ["entire file"]},
        {"field": "idea_graph.nodes", "priority": "high", "missing_values": ["need 5 more"]},
        {"field": "friction_log", "priority": "medium"},  # medium non-ground_truth → needs_agent
    ]
    fixable, needs_agent, structural = classify_gaps(gaps)
    assert len(structural) == 1
    assert len(fixable) == 1  # ground_truth
    assert len(needs_agent) == 3  # critical + high + medium non-ground_truth
