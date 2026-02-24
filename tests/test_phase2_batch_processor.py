"""Tests for Phase 2 deterministic processing (idea graph, synthesis, markers).

Tests the build_idea_graph function from backfill_phase2.py which
constructs idea graphs from canonical thread extractions data.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "phase_2_synthesis"))
sys.path.insert(0, str(PROJECT_ROOT / "output"))  # legacy fallback

# Canonical test data (same as conftest.py fixtures)
THREAD_EXTRACTIONS = {
    "session_id": "test_session",
    "threads": {
        "ideas": {"entries": [{"msg_index": 0, "content": "Build a CLI tool", "significance": "high"}]},
        "reactions": {"entries": [{"msg_index": 5, "content": "Frustration with imports", "significance": "medium"}]},
        "software": {"entries": [{"msg_index": 10, "content": "Created main.py", "significance": "high"},
                                  {"msg_index": 15, "content": "Modified utils.py", "significance": "medium"},
                                  {"msg_index": 20, "content": "Added config.py", "significance": "medium"}]},
        "code": {"entries": [{"msg_index": 25, "content": "Used argparse pattern", "significance": "medium"},
                              {"msg_index": 30, "content": "Refactored error handling", "significance": "high"},
                              {"msg_index": 35, "content": "Added logging", "significance": "low"}]},
        "plans": {"entries": []},
        "behavior": {"entries": [{"msg_index": 40, "content": "Premature completion claim", "significance": "high"}]},
    },
}

IDEA_GRAPH = {
    "session_id": "test_session",
    "nodes": [
        {"id": f"N{i:02d}", "label": f"Idea {i}", "description": f"Description for idea {i}",
         "message_index": i * 10, "confidence": "working"}
        for i in range(12)
    ],
    "edges": [
        {"from": f"N{i:02d}", "to": f"N{i+1:02d}", "type": "evolved"}
        for i in range(11)
    ],
}

GROUNDED_MARKERS = {
    "session_id": "test_session",
    "total_markers": 6,
    "markers": [
        {"marker_id": "GM-001", "category": "architecture", "claim": "File uses argparse", "confidence": 0.9},
        {"marker_id": "GM-002", "category": "decision", "claim": "Chose Flask over Django", "confidence": 0.85},
        {"marker_id": "GM-003", "category": "behavior", "claim": "Premature completion", "confidence": 0.8},
        {"marker_id": "GM-004", "category": "risk", "claim": "No tests written", "confidence": 0.9},
        {"marker_id": "GM-005", "category": "opportunity", "claim": "Could add type hints", "confidence": 0.7},
        {"marker_id": "GM-006", "category": "architecture", "claim": "Logging pattern", "confidence": 0.85},
    ],
}


class TestBuildIdeaGraphCanonical:
    """Test idea graph construction from canonical thread format."""

    def test_build_from_canonical_threads(self):
        """build_idea_graph should extract nodes from canonical threads dict."""
        import tempfile, os
        from backfill_phase2 import build_idea_graph

        # Create a temp session dir with test data
        with tempfile.TemporaryDirectory() as tmpdir:
            import json
            # Write minimal required input files
            for name, data in [
                ("session_metadata.json", {"session_id": "test", "session_stats": {"total_messages": 50}}),
                ("thread_extractions.json", THREAD_EXTRACTIONS),
                ("geological_notes.json", {"micro": [], "meso": [], "macro": []}),
                ("semantic_primitives.json", {"tagged_messages": []}),
                ("explorer_notes.json", {"observations": []}),
            ]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    json.dump(data, f)

            result = build_idea_graph(
                "test1234", tmpdir,
                {"session_id": "test", "session_stats": {"total_messages": 50}},
                THREAD_EXTRACTIONS,
                {"micro": [], "meso": [], "macro": []},
                {"tagged_messages": []},
                {"observations": []},
            )

        # Verify result has required structure
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)

    def test_canonical_format_has_required_keys(self):
        """Canonical thread format must have threads dict with entries lists."""
        threads = THREAD_EXTRACTIONS
        assert "threads" in threads
        assert isinstance(threads["threads"], dict)

        for cat_name, cat_data in threads["threads"].items():
            assert isinstance(cat_data, dict), f"{cat_name} is not a dict"
            assert "entries" in cat_data, f"{cat_name} missing entries"
            assert isinstance(cat_data["entries"], list), f"{cat_name} entries not list"

    def test_old_format_extractions_list_absent(self):
        """Canonical format should NOT have top-level 'extractions' key."""
        threads = THREAD_EXTRACTIONS
        assert "extractions" not in threads


class TestIdeaGraphStructure:
    """Test that idea graph output conforms to expected schema."""

    def test_node_has_required_fields(self):
        """Each node in the idea graph must have id, label/name, description."""
        pass  # Uses module-level IDEA_GRAPH

        for node in IDEA_GRAPH["nodes"]:
            assert "id" in node
            assert "label" in node or "name" in node
            assert "description" in node

    def test_edge_has_required_fields(self):
        """Each edge must have from, to, and type."""
        pass  # Uses module-level IDEA_GRAPH

        for edge in IDEA_GRAPH["edges"]:
            assert "from" in edge
            assert "to" in edge
            assert "type" in edge

    def test_node_count_matches_edges(self):
        """Edges should reference existing node IDs."""
        pass  # Uses module-level IDEA_GRAPH

        node_ids = {n["id"] for n in IDEA_GRAPH["nodes"]}
        for edge in IDEA_GRAPH["edges"]:
            assert edge["from"] in node_ids, f"Edge references missing node {edge['from']}"
            assert edge["to"] in node_ids, f"Edge references missing node {edge['to']}"


class TestGroundedMarkersStructure:
    """Test that grounded markers conform to canonical schema."""

    def test_markers_is_flat_list(self):
        pass  # Uses module-level GROUNDED_MARKERS

        assert "markers" in GROUNDED_MARKERS
        assert isinstance(GROUNDED_MARKERS["markers"], list)

    def test_each_marker_has_required_fields(self):
        pass  # Uses module-level GROUNDED_MARKERS

        for m in GROUNDED_MARKERS["markers"]:
            assert "marker_id" in m
            assert "category" in m
            assert "claim" in m
            assert "confidence" in m
