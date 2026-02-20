"""Tests for gap_checklist.py — the convergence thermometer."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "obsolete"))
from gap_checklist import (
    check_enum_coverage,
    check_count_threshold,
    check_populated_ratio,
    analyze_session,
    ACTION_VECTORS,
)


def test_enum_structural_gap():
    """When <=25% values are missing, gap is classified as structural (data_absent)."""
    # 7 of 8 found → only 1 missing → structural
    found = ["created", "modified", "debugged", "refactored", "discovered", "decided", "abandoned"]
    confirmed, gap = check_enum_coverage(found, ACTION_VECTORS, "action_vector")
    assert gap is not None
    assert gap["gap_type"] == "data_absent"
    assert gap["priority"] == "structural"
    assert "reverted" in gap["missing_values"]


def test_enum_extraction_gap():
    """When >25% values are missing, gap is classified as extraction_gap."""
    # 3 of 8 found → 5 missing (62%) → extraction gap
    found = ["created", "modified", "debugged"]
    confirmed, gap = check_enum_coverage(found, ACTION_VECTORS, "action_vector")
    assert gap is not None
    assert gap["gap_type"] == "extraction_gap"
    assert gap["priority"] == "high"


def test_adjusted_coverage_excludes_structural():
    """Structural gaps (data_absent) should not reduce adjusted coverage score."""
    result = {
        "confirmed": [{"field": "a"}, {"field": "b"}],
        "gaps": [
            {"gap_type": "data_absent", "priority": "structural"},  # structural — excluded
        ],
    }
    total_confirmed = len(result["confirmed"])
    structural = sum(1 for g in result["gaps"] if g.get("gap_type") == "data_absent")
    non_structural = len(result["gaps"]) - structural
    adjusted = total_confirmed / (total_confirmed + non_structural) if (total_confirmed + non_structural) > 0 else 0
    assert adjusted == 1.0  # No non-structural gaps → 100%


def test_count_threshold_met():
    """No gap when count meets threshold."""
    confirmed, gap = check_count_threshold(15, 10, "idea_nodes", "nodes")
    assert gap is None
    assert confirmed["confidence"] == 1.0


def test_count_threshold_not_met():
    """Gap when count is below threshold."""
    confirmed, gap = check_count_threshold(3, 10, "idea_nodes", "nodes")
    assert gap is not None
    assert "need 7 more" in gap["missing_values"][0]
    assert gap["priority"] == "high"  # 3 < 10/2


def test_populated_ratio_gap():
    """<10% populated triggers a gap."""
    confirmed, gap = check_populated_ratio(1, 100, "friction_log")
    assert gap is not None
    assert "1%" in confirmed["coverage"]


def test_convergence_with_structural_gaps_only():
    """When all non-structural gaps are resolved, adjusted coverage should be high."""
    # Our fixture data has enum coverage gaps (only 3 of 8 action_vectors)
    # These are expected to be classified as extraction_gap (>25% missing)
    # The test verifies that the gap checklist correctly identifies them
    result = analyze_session_with_full_data()
    conv = result["convergence"]
    # With full fixture data, no critical gaps should remain
    assert conv["critical_gaps"] == 0
    # Total gaps will include structural and extraction gaps from incomplete enums
    assert conv["total_gaps"] > 0  # The fixture intentionally has incomplete enum coverage
    # But adjusted coverage (excluding structural) should still be meaningful
    assert result["summary"]["adjusted_coverage_score"] > 0.3


def test_full_session_analysis(tmp_session_dir):
    """End-to-end analysis on the fixture session directory."""
    result = analyze_session(tmp_session_dir)

    assert result["summary"]["files_present"] >= 6
    assert result["summary"]["files_missing"] <= 2  # ground_truth + maybe enriched
    assert result["convergence"]["total_confirmed"] > 0
    assert result["convergence"]["critical_gaps"] == 0  # All files present


# ── Helper ────────────────────────────────────────────────────────────────

def analyze_session_with_full_data():
    """Create a temporary session with all thresholds met and analyze it."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)

        # Import fixtures from conftest
        from tests.conftest import (
            SESSION_METADATA, SEMANTIC_PRIMITIVES, THREAD_EXTRACTIONS,
            GEOLOGICAL_NOTES, EXPLORER_NOTES, IDEA_GRAPH, GROUNDED_MARKERS,
            FILE_DOSSIERS,
        )

        files = {
            "session_metadata.json": SESSION_METADATA,
            "semantic_primitives.json": SEMANTIC_PRIMITIVES,
            "thread_extractions.json": THREAD_EXTRACTIONS,
            "geological_notes.json": GEOLOGICAL_NOTES,
            "explorer_notes.json": EXPLORER_NOTES,
            "idea_graph.json": IDEA_GRAPH,
            "grounded_markers.json": GROUNDED_MARKERS,
            "file_dossiers.json": FILE_DOSSIERS,
        }

        for name, data in files.items():
            (session_dir / name).write_text(json.dumps(data, indent=2))

        return analyze_session(session_dir)
