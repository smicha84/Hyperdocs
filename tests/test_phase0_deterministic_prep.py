"""Tests for Phase 0 deterministic prep functions.

Tests the pure-Python metadata extraction, protocol detection,
char-per-line collapse, and frustration detection — all the things
that run at $0 cost before any LLM agent is invoked.
"""
import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from phase_0_prep.deterministic_prep import (
    detect_protocol_message,
    collapse_char_per_line,
)


class TestDetectProtocolMessage:
    """Protocol detection identifies system-generated messages vs human input."""

    def test_empty_content_is_protocol(self):
        result = detect_protocol_message("", role="user")
        assert result["is_protocol"] is True
        assert result["protocol_type"] == "empty_wrapper"

    def test_whitespace_only_is_protocol(self):
        result = detect_protocol_message("   \n  ", role="user")
        assert result["is_protocol"] is True
        assert result["protocol_type"] == "empty_wrapper"

    def test_system_reminder_is_protocol(self):
        result = detect_protocol_message(
            "hello <system-reminder>some reminder</system-reminder> world"
        )
        assert result["is_protocol"] is True
        assert result["protocol_type"] == "system_reminder"

    def test_command_name_is_protocol(self):
        result = detect_protocol_message("<command-name>commit</command-name>")
        assert result["is_protocol"] is True
        assert result["protocol_type"] == "command_name"

    def test_clear_continuation_is_protocol(self):
        result = detect_protocol_message(
            "This session is being continued from a previous conversation. "
            "Here's what happened..."
        )
        assert result["is_protocol"] is True
        assert result["protocol_type"] == "clear_continuation"

    def test_skill_injection_is_protocol(self):
        result = detect_protocol_message(
            "Base directory for this skill: /Users/me/.claude/skills/pdf"
        )
        assert result["is_protocol"] is True
        assert result["protocol_type"] == "skill_injection"

    def test_subagent_relay_is_protocol(self):
        result = detect_protocol_message("Hello memory agent, here is context...")
        assert result["is_protocol"] is True
        assert result["protocol_type"] == "subagent_relay"

    def test_normal_user_message_not_protocol(self):
        result = detect_protocol_message("Please fix the bug in main.py")
        assert result["is_protocol"] is False
        assert result["protocol_type"] is None

    def test_normal_code_not_protocol(self):
        result = detect_protocol_message(
            "def hello():\n    print('world')\n"
        )
        assert result["is_protocol"] is False


class TestCollapseCharPerLine:
    """Char-per-line encoding collapses A\\nL\\nW\\nA\\nY\\nS → ALWAYS."""

    def test_normal_text_unchanged(self):
        text = "This is normal text with\nmultiple lines\nof content."
        result, was_encoded = collapse_char_per_line(text)
        assert result == text
        assert was_encoded is False

    def test_char_per_line_collapsed(self):
        # Simulate char-per-line: each character on its own line
        encoded = "A\nL\nW\nA\nY\nS\n \nO\nP\nU\nS"
        result, was_encoded = collapse_char_per_line(encoded)
        assert was_encoded is True
        assert "ALWAYS" in result
        assert "\n" not in result  # All newlines removed

    def test_empty_string_unchanged(self):
        result, was_encoded = collapse_char_per_line("")
        assert result == ""
        assert was_encoded is False

    def test_no_newlines_unchanged(self):
        result, was_encoded = collapse_char_per_line("hello world")
        assert result == "hello world"
        assert was_encoded is False

    def test_short_content_unchanged(self):
        # Less than 4 lines shouldn't trigger
        result, was_encoded = collapse_char_per_line("a\nb\nc")
        assert was_encoded is False


class TestExtractThreadsOutput:
    """Test that extract_threads.py process_message produces expected structure."""

    def test_process_message_returns_all_fields(self):
        from phase_1_extraction.extract_threads import process_message

        msg = {
            "index": 0,
            "role": "user",
            "content": "I want to build a CLI tool for hyperdocs",
            "timestamp": "2026-01-01T00:00:00Z",
            "filter_score": 5,
            "filter_signals": [],
            "metadata": {},
            "behavior_flags": {},
        }
        result = process_message(msg)
        assert "index" in result
        assert "role" in result
        assert "threads" in result
        assert "markers" in result
        assert "user_ideas" in result["threads"]
        assert "claude_response" in result["threads"]
        assert "reactions" in result["threads"]
        assert "software" in result["threads"]
        assert "code_blocks" in result["threads"]
        assert "plans" in result["threads"]

    def test_frustration_detection(self):
        from phase_1_extraction.extract_threads import detect_frustration_level

        calm_msg = {
            "content": "Please fix the import",
            "metadata": {"caps_ratio": 0, "profanity": False, "exclamations": 0},
            "role": "user",
        }
        assert detect_frustration_level(calm_msg) == 0

        angry_msg = {
            "content": "WHAT THE FUCK IS THIS",
            "metadata": {"caps_ratio": 0.9, "profanity": True, "exclamations": 3},
            "role": "user",
        }
        assert detect_frustration_level(angry_msg) >= 4

    def test_deception_detection_on_user_message_returns_false(self):
        from phase_1_extraction.extract_threads import detect_deception

        user_msg = {"role": "user", "content": "hello", "behavior_flags": {}, "filter_signals": []}
        assert detect_deception(user_msg) is False
