"""Tests for run_pipeline.py — pipeline runner and validation."""
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from run_pipeline import validate_phase_output


class TestValidatePhaseOutput:
    """Test the per-phase schema validation."""

    def test_phase0_valid(self, tmp_path):
        """Phase 0 validation should pass when required files exist with right keys."""
        session_dir = tmp_path / "session_test1234"
        session_dir.mkdir()

        with open(session_dir / "enriched_session.json", "w") as f:
            json.dump({"session_id": "test", "messages": []}, f)
        with open(session_dir / "session_metadata.json", "w") as f:
            json.dump({"session_id": "test", "session_stats": {}}, f)

        # Patch OUTPUT_DIR
        import run_pipeline
        old_output = run_pipeline.OUTPUT_DIR
        run_pipeline.OUTPUT_DIR = tmp_path
        try:
            result = validate_phase_output("test1234", 0)
            assert result is True
        finally:
            run_pipeline.OUTPUT_DIR = old_output

    def test_phase0_missing_file(self, tmp_path):
        """Phase 0 validation should fail when required files are missing."""
        session_dir = tmp_path / "session_test1234"
        session_dir.mkdir()
        # Only create one of the two required files
        with open(session_dir / "enriched_session.json", "w") as f:
            json.dump({"session_id": "test", "messages": []}, f)

        import run_pipeline
        old_output = run_pipeline.OUTPUT_DIR
        run_pipeline.OUTPUT_DIR = tmp_path
        try:
            result = validate_phase_output("test1234", 0)
            assert result is False
        finally:
            run_pipeline.OUTPUT_DIR = old_output

    def test_phase2_valid(self, tmp_path):
        """Phase 2 validation should pass with correct schema."""
        session_dir = tmp_path / "session_test1234"
        session_dir.mkdir()

        with open(session_dir / "idea_graph.json", "w") as f:
            json.dump({"nodes": [], "edges": []}, f)
        with open(session_dir / "synthesis.json", "w") as f:
            json.dump({"session_id": "test"}, f)
        with open(session_dir / "grounded_markers.json", "w") as f:
            json.dump({"markers": []}, f)

        import run_pipeline
        old_output = run_pipeline.OUTPUT_DIR
        run_pipeline.OUTPUT_DIR = tmp_path
        try:
            result = validate_phase_output("test1234", 2)
            assert result is True
        finally:
            run_pipeline.OUTPUT_DIR = old_output

    def test_phase2_missing_key(self, tmp_path):
        """Phase 2 validation should fail when a required key is missing."""
        session_dir = tmp_path / "session_test1234"
        session_dir.mkdir()

        # idea_graph missing 'edges' key
        with open(session_dir / "idea_graph.json", "w") as f:
            json.dump({"nodes": []}, f)
        with open(session_dir / "synthesis.json", "w") as f:
            json.dump({"session_id": "test"}, f)
        with open(session_dir / "grounded_markers.json", "w") as f:
            json.dump({"markers": []}, f)

        import run_pipeline
        old_output = run_pipeline.OUTPUT_DIR
        run_pipeline.OUTPUT_DIR = tmp_path
        try:
            result = validate_phase_output("test1234", 2)
            assert result is False
        finally:
            run_pipeline.OUTPUT_DIR = old_output

    def test_corrupt_json_fails(self, tmp_path):
        """Phase validation should fail on corrupt JSON files."""
        session_dir = tmp_path / "session_test1234"
        session_dir.mkdir()

        (session_dir / "idea_graph.json").write_text("{invalid}")
        with open(session_dir / "synthesis.json", "w") as f:
            json.dump({"session_id": "test"}, f)
        with open(session_dir / "grounded_markers.json", "w") as f:
            json.dump({"markers": []}, f)

        import run_pipeline
        old_output = run_pipeline.OUTPUT_DIR
        run_pipeline.OUTPUT_DIR = tmp_path
        try:
            result = validate_phase_output("test1234", 2)
            assert result is False
        finally:
            run_pipeline.OUTPUT_DIR = old_output
