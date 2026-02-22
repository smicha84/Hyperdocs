"""Tests for collect_file_evidence.py — per-file evidence collection."""
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "phase_3_hyperdoc_writing"))


@pytest.fixture
def session_dir(tmp_path):
    """Create a minimal session directory with test data."""
    sdir = tmp_path / "session_test1234"
    sdir.mkdir()

    # Minimal enriched session
    enriched = {
        "session_id": "test1234",
        "messages": [
            {"role": "user", "content": "Create config.py with database settings", "index": 0},
            {"role": "assistant", "content": "I'll create config.py with the database URL", "index": 1},
            {"role": "user", "content": "Now update utils.py to use the config", "index": 2},
            {"role": "assistant", "content": "Updated utils.py to import from config.py", "index": 3},
        ],
        "session_stats": {
            "total_messages": 4,
            "file_mention_counts": {"config.py": 3, "utils.py": 2},
        },
    }

    thread_extractions = {
        "threads": {
            "software": {"entries": [
                {"msg_index": 0, "content": "Create config.py with database settings"},
                {"msg_index": 2, "content": "Update utils.py to use the config"},
            ]},
            "ideas": {"entries": []},
        },
    }

    semantic_primitives = {
        "tagged_messages": [
            {"msg_index": 0, "action_vector": "created", "confidence": "tentative"},
            {"msg_index": 2, "action_vector": "modified", "confidence": "working"},
        ],
    }

    grounded_markers = {
        "markers": [
            {"marker_id": "W01", "category": "warning", "claim": "config.py has no validation"},
            {"marker_id": "R01", "category": "recommendation", "claim": "Add type hints to utils.py"},
        ],
    }

    idea_graph = {
        "nodes": [
            {"id": "N01", "label": "Database Config", "description": "config.py setup"},
        ],
        "edges": [],
    }

    geological_notes = {"micro": [], "meso": [], "macro": []}
    explorer_notes = {"observations": []}
    synthesis = {"session_id": "test1234", "passes": []}
    claude_md = {"gate_analysis": []}

    for name, data in [
        ("enriched_session.json", enriched),
        ("thread_extractions.json", thread_extractions),
        ("semantic_primitives.json", semantic_primitives),
        ("grounded_markers.json", grounded_markers),
        ("idea_graph.json", idea_graph),
        ("geological_notes.json", geological_notes),
        ("explorer_notes.json", explorer_notes),
        ("synthesis.json", synthesis),
        ("claude_md_analysis.json", claude_md),
    ]:
        with open(sdir / name, "w") as f:
            json.dump(data, f)

    return sdir


class TestLoadJson:
    """Test the load_json function in collect_file_evidence."""

    def test_loads_existing_file(self, session_dir):
        """load_json should find and parse files from search directories."""
        from collect_file_evidence import load_json
        result = load_json("thread_extractions.json", [session_dir])
        assert "threads" in result

    def test_returns_empty_for_missing_file(self, session_dir):
        """load_json should return {} for files not in any search dir."""
        from collect_file_evidence import load_json
        result = load_json("nonexistent_file.json", [session_dir])
        assert result == {}

    def test_handles_corrupt_json(self, session_dir):
        """load_json should return {} for corrupt JSON files."""
        corrupt = session_dir / "corrupt.json"
        corrupt.write_text("{invalid json content")
        from collect_file_evidence import load_json
        result = load_json("corrupt.json", [session_dir])
        assert result == {}


class TestMentionsFile:
    """Test the mentions_file function."""

    def test_exact_filename_match(self):
        """mentions_file should find exact filename in text."""
        from collect_file_evidence import mentions_file
        assert mentions_file("I modified config.py", "config.py")

    def test_stem_match(self):
        """mentions_file should find stem (without extension) in text."""
        from collect_file_evidence import mentions_file
        assert mentions_file("the config module is ready", "config.py")

    def test_no_match(self):
        """mentions_file should return False when file is not mentioned."""
        from collect_file_evidence import mentions_file
        assert not mentions_file("I created a database", "config.py")
