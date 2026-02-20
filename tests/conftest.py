"""Shared fixtures for the Hyperdocs test suite."""
import json
import sys
from pathlib import Path

import pytest

# Add project root to path so imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Minimal JSON data matching each pipeline output schema ──────────────

SESSION_METADATA = {
    "session_id": "test_session",
    "session_stats": {
        "total_messages": 200,
        "user_messages": 50,
        "assistant_messages": 150,
        "tier_distribution": {"1_skip": 100, "2_basic": 40, "3_standard": 30, "4_priority": 30},
        "total_input_tokens": 500000,
        "total_output_tokens": 100000,
        "file_mention_counts": {
            "main.py": 15,
            "utils.py": 8,
            "config.py": 5,
            "test_main.py": 3,
        },
        "error_count": 2,
        "frustration_peaks": [{"index": 42, "caps_ratio": 0.8}],
    },
}

SEMANTIC_PRIMITIVES = {
    "session_id": "test_session",
    "tagged_messages": [
        {"msg_index": 0, "action_vector": "created", "confidence_signal": "working",
         "emotional_tenor": "confident", "intent_marker": "feature",
         "friction_log": "import errors on first run", "decision_trace": "chose Flask over Django because simpler"},
        {"msg_index": 5, "action_vector": "debugged", "confidence_signal": "fragile",
         "emotional_tenor": "frustrated", "intent_marker": "bugfix",
         "friction_log": "", "decision_trace": ""},
        {"msg_index": 10, "action_vector": "modified", "confidence_signal": "stable",
         "emotional_tenor": "relieved", "intent_marker": "correctness",
         "friction_log": "", "decision_trace": ""},
    ],
}

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

GEOLOGICAL_NOTES = {
    "session_id": "test_session",
    "micro": [
        {"observation": f"Observation {i}", "message_range": [i * 10, i * 10 + 5], "evidence": f"evidence_{i}"}
        for i in range(6)
    ],
    "meso": [
        {"observation": "Phase 1: Setup", "message_range": [0, 50], "pattern": "linear"},
        {"observation": "Phase 2: Debug", "message_range": [50, 100], "pattern": "iterative"},
        {"observation": "Phase 3: Refactor", "message_range": [100, 200], "pattern": "convergent"},
    ],
    "macro": [{"observation": "Single-arc session", "scope": "full session", "significance": "medium"}],
}

EXPLORER_NOTES = {
    "session_id": "test_session",
    "observations": [
        {"id": f"obs-{i:03d}", "observation": f"Observation {i}", "evidence": f"evidence_{i}", "significance": "medium"}
        for i in range(8)
    ],
    "verification": {"overall_data_quality": "minor_issues"},
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

FILE_DOSSIERS = {
    "dossiers": {
        "main.py": {"story_arc": "Created and iterated", "warnings": ["no tests"], "key_decisions": ["argparse"], "confidence": "working"},
        "utils.py": {"story_arc": "Helper module", "warnings": [], "key_decisions": [], "confidence": "stable"},
        "config.py": {"story_arc": "Configuration", "warnings": [], "key_decisions": ["env vars"], "confidence": "stable"},
    },
}


@pytest.fixture
def tmp_session_dir(tmp_path):
    """Create a temporary session directory with all pipeline output files."""
    session_dir = tmp_path / "session_test1234"
    session_dir.mkdir()

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

    return session_dir
