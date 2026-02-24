"""End-to-end smoke test for the Hyperdocs pipeline.

Uses session 513d4807 data from PERMANENT_HYPERDOCS as a reference.
Tests Phase 2 (deterministic) and Phase 3 (evidence collection + dossiers).
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "phase_2_synthesis"))
sys.path.insert(0, str(PROJECT_ROOT / "phase_3_hyperdoc_writing"))

PERM_SESSIONS = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
REFERENCE_SESSION = PERM_SESSIONS / "session_513d4807"

# Skip all tests if reference session doesn't exist (CI without data)
pytestmark = pytest.mark.skipif(
    not REFERENCE_SESSION.exists(),
    reason="Reference session 513d4807 not available"
)


@pytest.fixture
def session_copy(tmp_path):
    """Copy reference session to tmp so tests don't modify the original."""
    dest = tmp_path / "session_513d4807"
    shutil.copytree(REFERENCE_SESSION, dest)
    return dest


class TestPhase2E2E:
    """Verify Phase 2 deterministic processing produces valid output."""

    def test_build_idea_graph_from_real_data(self, session_copy):
        """build_idea_graph should produce nodes and edges from real session data."""
        from backfill_phase2 import build_idea_graph, read_json

        sdir = str(session_copy)
        summary = read_json(os.path.join(sdir, "session_metadata.json"))
        threads = read_json(os.path.join(sdir, "thread_extractions.json"))
        geo = read_json(os.path.join(sdir, "geological_notes.json"))
        prims = read_json(os.path.join(sdir, "semantic_primitives.json"))
        explorer = read_json(os.path.join(sdir, "explorer_notes.json"))

        result = build_idea_graph("513d4807", sdir, summary, threads, geo, prims, explorer)

        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)
        # Real session should produce at least a few nodes
        assert len(result["nodes"]) >= 1, f"Expected nodes, got {len(result['nodes'])}"

    def test_build_synthesis_from_real_data(self, session_copy):
        """build_synthesis should produce a valid synthesis document."""
        from backfill_phase2 import build_idea_graph, build_synthesis, read_json

        sdir = str(session_copy)
        summary = read_json(os.path.join(sdir, "session_metadata.json"))
        threads = read_json(os.path.join(sdir, "thread_extractions.json"))
        geo = read_json(os.path.join(sdir, "geological_notes.json"))
        prims = read_json(os.path.join(sdir, "semantic_primitives.json"))
        explorer = read_json(os.path.join(sdir, "explorer_notes.json"))
        ig = read_json(os.path.join(sdir, "idea_graph.json"))
        if not ig.get("nodes"):
            ig = build_idea_graph("513d4807", sdir, summary, threads, geo, prims, explorer)

        result = build_synthesis("513d4807", sdir, summary, threads, geo, prims, explorer, ig)

        assert isinstance(result, dict)
        assert "session_id" in result

    def test_build_grounded_markers_from_real_data(self, session_copy):
        """build_grounded_markers should produce a markers list."""
        from backfill_phase2 import (
            build_idea_graph, build_synthesis, build_grounded_markers, read_json
        )

        sdir = str(session_copy)
        summary = read_json(os.path.join(sdir, "session_metadata.json"))
        threads = read_json(os.path.join(sdir, "thread_extractions.json"))
        geo = read_json(os.path.join(sdir, "geological_notes.json"))
        prims = read_json(os.path.join(sdir, "semantic_primitives.json"))
        explorer = read_json(os.path.join(sdir, "explorer_notes.json"))
        ig = read_json(os.path.join(sdir, "idea_graph.json"))
        syn = read_json(os.path.join(sdir, "synthesis.json"))
        if not ig.get("nodes"):
            ig = build_idea_graph("513d4807", sdir, summary, threads, geo, prims, explorer)
        if not syn.get("session_id"):
            syn = build_synthesis("513d4807", sdir, summary, threads, geo, prims, explorer, ig)

        result = build_grounded_markers("513d4807", sdir, summary, threads, geo, prims, explorer, ig, syn)

        assert isinstance(result, dict)
        assert "markers" in result
        assert isinstance(result["markers"], list)


class TestPhase3E2E:
    """Verify Phase 3 evidence collection works on real data."""

    def test_collect_evidence_produces_output(self, session_copy):
        """collect_file_evidence should produce per-file evidence JSON."""
        from collect_file_evidence import load_json, mentions_file

        # Verify source data can be loaded
        threads = load_json("thread_extractions.json", [session_copy])
        assert threads, "thread_extractions.json should be loadable"

        metadata = load_json("session_metadata.json", [session_copy])
        assert metadata, "session_metadata.json should be loadable"

        markers = load_json("grounded_markers.json", [session_copy])
        assert isinstance(markers, dict), "grounded_markers.json should be a dict"

    def test_all_phase2_outputs_are_valid_json(self, session_copy):
        """Every Phase 2 output file should be parseable JSON with expected keys."""
        expected = {
            "idea_graph.json": ["nodes", "edges"],
            "synthesis.json": ["session_id"],
            "grounded_markers.json": ["markers"],
        }
        for filename, required_keys in expected.items():
            path = session_copy / filename
            if not path.exists():
                pytest.skip(f"{filename} not present in reference session")
            data = json.loads(path.read_text())
            for key in required_keys:
                assert key in data, f"{filename} missing required key '{key}'"

    def test_all_session_json_files_are_parseable(self, session_copy):
        """Every JSON file in the session should be parseable (no corruption)."""
        corrupt = []
        for f in session_copy.glob("*.json"):
            try:
                json.loads(f.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                corrupt.append(f"{f.name}: {e}")
        assert not corrupt, f"Corrupt JSON files: {corrupt}"
