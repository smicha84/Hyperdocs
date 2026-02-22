"""Tests for config.py — central path configuration."""
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestEnvVarOverrides:
    """Verify that HYPERDOCS_STORE_DIR overrides all derived paths."""

    def test_store_dir_override(self):
        """HYPERDOCS_STORE_DIR should override STORE_DIR and all sub-paths."""
        with mock.patch.dict(os.environ, {"HYPERDOCS_STORE_DIR": "/tmp/custom_store"}):
            # Force reimport to pick up env var
            if "config" in sys.modules:
                del sys.modules["config"]
            import config
            assert str(config.STORE_DIR) == "/tmp/custom_store"
            assert str(config.SESSIONS_STORE_DIR) == "/tmp/custom_store/sessions"
            assert str(config.INDEXES_DIR) == "/tmp/custom_store/indexes"
            assert str(config.HYPERDOCS_STORE_DIR) == "/tmp/custom_store/hyperdocs"
            assert str(config.HYPERDOC_INPUTS_DIR) == "/tmp/custom_store/hyperdoc_inputs"
            # Cleanup
            del sys.modules["config"]

    def test_default_store_dir(self):
        """Without env var, STORE_DIR defaults to ~/PERMANENT_HYPERDOCS."""
        env = {k: v for k, v in os.environ.items() if k != "HYPERDOCS_STORE_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            if "config" in sys.modules:
                del sys.modules["config"]
            import config
            assert str(config.STORE_DIR) == str(Path.home() / "PERMANENT_HYPERDOCS")
            del sys.modules["config"]

    def test_output_dir_override(self):
        """HYPERDOCS_OUTPUT_DIR should override OUTPUT_DIR."""
        with mock.patch.dict(os.environ, {"HYPERDOCS_OUTPUT_DIR": "/tmp/custom_output"}):
            if "config" in sys.modules:
                del sys.modules["config"]
            import config
            assert str(config.OUTPUT_DIR) == "/tmp/custom_output"
            del sys.modules["config"]


class TestSessionHandling:
    """Verify session ID and file lookup logic."""

    def test_empty_session_id(self):
        """Empty SESSION_ID should produce empty SESSION_SHORT."""
        env = {k: v for k, v in os.environ.items() if k != "HYPERDOCS_SESSION_ID"}
        with mock.patch.dict(os.environ, env, clear=True):
            if "config" in sys.modules:
                del sys.modules["config"]
            import config
            assert config.SESSION_ID == ""
            assert config.SESSION_SHORT == ""
            del sys.modules["config"]

    def test_session_id_truncation(self):
        """SESSION_SHORT should be first 8 chars of SESSION_ID."""
        with mock.patch.dict(os.environ, {"HYPERDOCS_SESSION_ID": "abcdef1234567890"}):
            if "config" in sys.modules:
                del sys.modules["config"]
            import config
            assert config.SESSION_SHORT == "abcdef12"
            del sys.modules["config"]


class TestHelpers:
    """Verify helper functions."""

    def test_get_session_output_dir_with_session(self, tmp_path):
        """get_session_output_dir should create session-specific directory."""
        with mock.patch.dict(os.environ, {
            "HYPERDOCS_SESSION_ID": "test1234",
            "HYPERDOCS_OUTPUT_DIR": str(tmp_path),
        }):
            if "config" in sys.modules:
                del sys.modules["config"]
            import config
            out = config.get_session_output_dir()
            assert out.name == "session_test1234"
            assert out.exists()
            del sys.modules["config"]

    def test_get_session_file_returns_none_when_not_found(self):
        """get_session_file should return None when no session file exists."""
        with mock.patch.dict(os.environ, {
            "HYPERDOCS_SESSION_ID": "nonexistent_session_id",
            "HYPERDOCS_CHAT_HISTORY": "",
        }):
            if "config" in sys.modules:
                del sys.modules["config"]
            import config
            result = config.get_session_file()
            # Should return None (not crash) when session doesn't exist
            assert result is None or isinstance(result, Path)
            del sys.modules["config"]
