"""Tests for claim_extractor.py — file list derivation from dossiers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "obsolete" / "phase_5_ground_truth"))
from claim_extractor import get_file_list


def test_file_list_dict_dossiers(tmp_path):
    """Dict-schema dossiers: keys are filenames."""
    session_dir = tmp_path / "session_test"
    session_dir.mkdir()
    dossiers = {"dossiers": {"main.py": {}, "utils.py": {}, "config.py": {}}}
    (session_dir / "file_dossiers.json").write_text(json.dumps(dossiers))
    result = get_file_list(session_dir)
    assert result == ["config.py", "main.py", "utils.py"]


def test_file_list_list_file_key(tmp_path):
    """List-schema dossiers with 'file' key."""
    session_dir = tmp_path / "session_test"
    session_dir.mkdir()
    dossiers = {"dossiers": [
        {"file": "main.py", "story_arc": "created"},
        {"file": "utils.py", "story_arc": "helper"},
    ]}
    (session_dir / "file_dossiers.json").write_text(json.dumps(dossiers))
    result = get_file_list(session_dir)
    assert "main.py" in result
    assert "utils.py" in result


def test_file_list_list_file_name_key(tmp_path):
    """List-schema dossiers with 'file_name' key."""
    session_dir = tmp_path / "session_test"
    session_dir.mkdir()
    dossiers = {"dossiers": [
        {"file_name": "app.py"},
        {"file_name": "server.py"},
    ]}
    (session_dir / "file_dossiers.json").write_text(json.dumps(dossiers))
    result = get_file_list(session_dir)
    assert "app.py" in result
    assert "server.py" in result


def test_file_list_list_file_path_key(tmp_path):
    """List-schema dossiers with 'file_path' key containing full paths."""
    session_dir = tmp_path / "session_test"
    session_dir.mkdir()
    dossiers = {"dossiers": [
        {"file_path": "/home/user/project/main.py"},
        {"file_path": "/home/user/project/lib/utils.py"},
    ]}
    (session_dir / "file_dossiers.json").write_text(json.dumps(dossiers))
    result = get_file_list(session_dir)
    assert "main.py" in result
    assert "utils.py" in result


def test_file_list_fallback_session_metadata(tmp_path):
    """When no dossiers exist, falls back to session_metadata file_mention_counts."""
    session_dir = tmp_path / "session_test"
    session_dir.mkdir()
    metadata = {
        "session_stats": {
            "file_mention_counts": {"app.py": 10, "db.py": 5},
        }
    }
    (session_dir / "session_metadata.json").write_text(json.dumps(metadata))
    result = get_file_list(session_dir)
    assert "app.py" in result
    assert "db.py" in result


def test_empty_dossiers_graceful(tmp_path):
    """Empty dict dossiers don't crash."""
    session_dir = tmp_path / "session_test"
    session_dir.mkdir()
    dossiers = {"dossiers": {}}
    (session_dir / "file_dossiers.json").write_text(json.dumps(dossiers))
    result = get_file_list(session_dir)
    assert result == []
