"""Tests for the schema normalizer — the 9 normalizers that fix agent-produced JSON.

Each normalizer takes heterogeneous JSON from different Opus agent runs
and produces a canonical schema. These tests verify that both canonical
and old-format inputs produce valid canonical output.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from phase_0_prep.schema_normalizer import (
    normalize_thread_extractions,
    normalize_semantic_primitives,
    normalize_geological_notes,
    extract_metadata,
    collect_extra,
)


class TestNormalizeThreadExtractions:
    """Thread extractions normalizer handles 5+ input schemas."""

    def test_canonical_dict_passthrough(self):
        """Canonical format (threads dict) should pass through cleanly."""
        data = {
            "session_id": "test",
            "threads": {
                "ideas": {"description": "Ideas", "entries": [{"msg_index": 1, "content": "idea1"}]},
                "software": {"description": "Software", "entries": []},
            },
        }
        result = normalize_thread_extractions(data)
        assert "threads" in result
        assert "ideas" in result["threads"]
        assert len(result["threads"]["ideas"]["entries"]) == 1
        assert result["_normalization_log"]

    def test_old_extractions_list_format(self):
        """Old format with 'extractions' list should be converted to threads dict."""
        data = {
            "session_id": "test",
            "extractions": [
                {"thread": "ideas", "content": "Build CLI", "msg_index": 0},
                {"thread": "ideas", "content": "Add tests", "msg_index": 5},
                {"thread": "software", "content": "Created main.py", "msg_index": 10},
            ],
        }
        result = normalize_thread_extractions(data)
        assert "threads" in result
        assert "ideas" in result["threads"]
        assert len(result["threads"]["ideas"]["entries"]) == 2
        assert "software" in result["threads"]

    def test_extractions_dict_format(self):
        """Extractions as dict of category→items should normalize."""
        data = {
            "extractions": {
                "ideas": [{"msg_index": 0, "content": "idea1"}],
                "code": [{"msg_index": 5, "content": "code block"}],
            },
        }
        result = normalize_thread_extractions(data)
        assert "ideas" in result["threads"]
        assert "code" in result["threads"]

    def test_thread_n_top_level_keys(self):
        """Top-level thread_1_, thread_2_ keys should be detected."""
        data = {
            "thread_1_topic_intent": [{"msg": "first thread"}],
            "thread_2_code_evolution": [{"msg": "second thread"}],
        }
        result = normalize_thread_extractions(data)
        assert len(result["threads"]) == 2

    def test_empty_data_produces_empty_threads(self):
        """Empty input should produce empty threads dict, not crash."""
        result = normalize_thread_extractions({})
        assert result["threads"] == {}
        assert "NO extractable thread data found" in result["_normalization_log"][0]

    def test_metadata_preserved(self):
        """Session metadata should be preserved in output."""
        data = {"session_id": "abc123", "generator": "test", "threads": {}}
        result = normalize_thread_extractions(data)
        assert result["session_id"] == "abc123"
        assert result["generator"] == "test"

    def test_extra_keys_captured(self):
        """Non-canonical keys go into _extra."""
        data = {
            "threads": {"ideas": {"entries": []}},
            "some_custom_field": "hello",
            "another_field": 42,
        }
        result = normalize_thread_extractions(data)
        assert result["_extra"] is not None
        assert "some_custom_field" in result["_extra"]


class TestNormalizeSemanticPrimitives:
    """Semantic primitives normalizer handles 5+ input schemas."""

    def test_canonical_tagged_messages(self):
        """Canonical format with tagged_messages list should pass through."""
        data = {
            "tagged_messages": [
                {"msg_index": 0, "action_vector": "created", "confidence_signal": "working"},
            ],
            "distributions": {"action_vector": {"created": 5}},
        }
        result = normalize_semantic_primitives(data)
        assert len(result["tagged_messages"]) == 1
        assert result["distributions"]["action_vector"]["created"] == 5

    def test_primitives_list_format(self):
        """Direct primitives list should become tagged_messages."""
        data = {
            "primitives": [
                {"action_vector": "debugged", "confidence_signal": "fragile"},
            ],
        }
        result = normalize_semantic_primitives(data)
        assert len(result["tagged_messages"]) == 1

    def test_empty_produces_empty_list(self):
        """Empty input should produce empty tagged_messages, not crash."""
        result = normalize_semantic_primitives({})
        assert result["tagged_messages"] == []


class TestNormalizeGeologicalNotes:
    """Geological notes normalizer handles micro/meso/macro schemas."""

    def test_canonical_micro_meso_macro(self):
        """Standard micro/meso/macro structure should pass through."""
        data = {
            "micro": [{"observation": "test micro"}],
            "meso": [{"observation": "test meso", "pattern": "linear"}],
            "macro": [{"observation": "test macro", "scope": "full"}],
        }
        result = normalize_geological_notes(data)
        assert len(result["micro"]) == 1
        assert len(result["meso"]) == 1
        assert len(result["macro"]) == 1

    def test_alternative_key_names(self):
        """Alternative keys like strata, layers should be captured."""
        data = {
            "strata": [{"observation": "a stratum"}],
            "geological_layers": [{"observation": "a layer"}],
        }
        result = normalize_geological_notes(data)
        # Alternative keys go into observations
        assert len(result["observations"]) == 2


class TestExtractMetadata:
    """Metadata extraction pulls standard fields from any schema."""

    def test_extracts_session_id(self):
        meta = extract_metadata({"session_id": "abc", "foo": "bar"})
        assert meta["session_id"] == "abc"
        assert "foo" not in meta

    def test_normalizes_generated_by(self):
        """generated_by should be normalized to generator."""
        meta = extract_metadata({"generated_by": "opus"})
        assert meta["generator"] == "opus"
        assert "generated_by" not in meta


class TestCollectExtra:
    """Extra field collection captures non-canonical keys."""

    def test_captures_unknown_keys(self):
        data = {"known": 1, "unknown_field": 2, "another": 3}
        extra = collect_extra(data, {"known"})
        assert "unknown_field" in extra
        assert "another" in extra
        assert "known" not in extra

    def test_returns_none_when_empty(self):
        data = {"known": 1}
        extra = collect_extra(data, {"known"})
        assert extra is None
