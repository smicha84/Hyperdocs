"""Tests for aggregate_dossiers.py — cross-session dossier aggregation."""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "phase_4_hyperdoc_writing"))

from aggregate_dossiers import normalize_dict_format, normalize_list_format


class TestNormalizeDictFormat:
    """Test dict-keyed dossier normalization."""

    def test_basic_dict_normalization(self):
        """Dict dossiers should be converted to list of entries with 'file' key."""
        dossiers = {
            "config.py": {
                "confidence": "stable",
                "total_mentions": 8,
                "story_arc": "Created for path centralization",
            },
            "main.py": {
                "confidence": "working",
                "total_mentions": 3,
            },
        }
        result = normalize_dict_format(dossiers, "test_session")
        assert len(result) == 2
        files = {e["file"] for e in result}
        assert "config.py" in files
        assert "main.py" in files
        config_entry = [e for e in result if e["file"] == "config.py"][0]
        assert config_entry["confidence"] == "stable"
        assert config_entry["session_id"] == "test_session"
        assert config_entry["total_mentions"] == 8

    def test_non_dict_values_skipped(self):
        """Non-dict values in the dossiers dict should be silently skipped."""
        dossiers = {
            "config.py": {"confidence": "stable"},
            "bad_entry": "not a dict",
            "also_bad": 42,
        }
        result = normalize_dict_format(dossiers, "test")
        assert len(result) == 1
        assert result[0]["file"] == "config.py"

    def test_missing_fields_get_defaults(self):
        """Missing fields should get sensible defaults, not crash."""
        dossiers = {"minimal.py": {}}
        result = normalize_dict_format(dossiers, "test")
        assert len(result) == 1
        assert result[0]["confidence"] == "unknown"
        assert result[0]["total_mentions"] == 0
        assert result[0]["warnings"] == []


class TestNormalizeListFormat:
    """Test list-based dossier normalization."""

    def test_basic_list_normalization(self):
        """List dossiers should keep entries with 'file' key."""
        dossiers = [
            {"file": "config.py", "confidence": "stable", "total_mentions": 8},
            {"file": "main.py", "confidence": "working"},
        ]
        result = normalize_list_format(dossiers, "test_session")
        assert len(result) == 2
        assert result[0]["file"] == "config.py"
        assert result[0]["session_id"] == "test_session"

    def test_file_path_key_variants(self):
        """Should accept file, file_path, and filename as the file key."""
        dossiers = [
            {"file": "a.py"},
            {"file_path": "b.py"},
            {"filename": "c.py"},
        ]
        result = normalize_list_format(dossiers, "test")
        assert len(result) == 3
        files = {e["file"] for e in result}
        assert files == {"a.py", "b.py", "c.py"}

    def test_unknown_file_skipped(self):
        """Entries with empty or TRULY_UNKNOWN file should be skipped."""
        dossiers = [
            {"file": ""},
            {"file": "TRULY_UNKNOWN"},
            {"file": "real.py"},
        ]
        result = normalize_list_format(dossiers, "test")
        assert len(result) == 1
        assert result[0]["file"] == "real.py"

    def test_non_dict_entries_skipped(self):
        """Non-dict entries in the list should be silently skipped."""
        dossiers = [
            {"file": "real.py"},
            "not a dict",
            42,
            None,
        ]
        result = normalize_list_format(dossiers, "test")
        assert len(result) == 1
