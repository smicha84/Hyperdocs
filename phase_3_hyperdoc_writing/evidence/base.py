"""
Base evidence renderer class.

All 7 evidence renderers inherit from EvidenceRenderer, which provides
shared data loading from session output directories using the same
PERM-first search strategy as collect_file_evidence.py.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from tools.json_io import load_json as _load_json

from tools.log_config import get_logger

logger = get_logger("phase3.evidence")

# Permanent storage paths (mirroring collect_file_evidence.py L3 pattern)
_PERM_SESSIONS = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"


def load_json(filename, search_dirs):
    """Load JSON from the first directory where the file exists.

    Reuses the same multi-directory search pattern from collect_file_evidence.py:
    PERM session dir is checked first (rich Opus data), then local output dir.
    """
    for d in search_dirs:
        path = d / filename
        if path.exists():
            try:
                return _load_json(path)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to load {filename} from {d}: {e}")
                continue
    return {}


class EvidenceRenderer:
    """Base class for all evidence renderers.

    Subclasses implement render(params) -> str to produce formatted
    evidence blocks from pipeline data.

    Data sources are lazy-loaded on first access via properties.
    """

    def __init__(self, session_dir: Path, session_id: str = ""):
        self.session_dir = session_dir
        self.session_id = session_id or session_dir.name.replace("session_", "")

        # Build search dirs: PERM first (rich data), then local output
        perm_dir = _PERM_SESSIONS / session_dir.name
        self._search_dirs = [perm_dir, session_dir]

        # Lazy-loaded data caches
        self._enriched_session = None
        self._semantic_primitives = None
        self._idea_graph = None
        self._thread_extractions = None
        self._geological_notes = None
        self._grounded_markers = None
        self._file_dossiers = None

    def _load(self, filename):
        """Load a JSON file using the search directory strategy."""
        return load_json(filename, self._search_dirs)

    @property
    def enriched_session(self):
        if self._enriched_session is None:
            self._enriched_session = self._load("enriched_session.json")
        return self._enriched_session

    @property
    def semantic_primitives(self):
        if self._semantic_primitives is None:
            self._semantic_primitives = self._load("semantic_primitives.json")
        return self._semantic_primitives

    @property
    def idea_graph(self):
        if self._idea_graph is None:
            self._idea_graph = self._load("idea_graph.json")
        return self._idea_graph

    @property
    def thread_extractions(self):
        if self._thread_extractions is None:
            self._thread_extractions = self._load("thread_extractions.json")
        return self._thread_extractions

    @property
    def geological_notes(self):
        if self._geological_notes is None:
            self._geological_notes = self._load("geological_notes.json")
        return self._geological_notes

    @property
    def grounded_markers(self):
        if self._grounded_markers is None:
            self._grounded_markers = self._load("grounded_markers.json")
        return self._grounded_markers

    @property
    def file_dossiers(self):
        if self._file_dossiers is None:
            self._file_dossiers = self._load("file_dossiers.json")
        return self._file_dossiers

    def get_messages(self):
        """Get the messages list from enriched_session.json."""
        return self.enriched_session.get("messages", [])

    def get_message(self, index):
        """Get a single message by index, or None if out of range."""
        messages = self.get_messages()
        for msg in messages:
            if isinstance(msg, dict) and msg.get("index") == index:
                return msg
        return None

    def get_messages_in_range(self, start, end):
        """Get messages with index in [start, end] inclusive."""
        messages = self.get_messages()
        return [
            m for m in messages
            if isinstance(m, dict) and start <= m.get("index", -1) <= end
        ]

    def get_tagged_message(self, msg_index):
        """Get semantic primitives for a message by index.

        Handles both schema variants:
          - Nested: primitives under a 'primitives' dict
          - Flat: primitives as top-level keys on the tagged message
        """
        for tm in self.semantic_primitives.get("tagged_messages", []):
            idx = tm.get("msg_index", tm.get("index", -1))
            if idx == msg_index:
                # Flat schema (normalized): primitives are top-level
                if "emotional_tenor" in tm:
                    return tm
                # Nested schema: primitives under 'primitives' key
                prims = tm.get("primitives", {})
                if prims:
                    return {**tm, **prims}
                return tm
        return {}

    def format_timestamp(self, timestamp_str):
        """Extract HH:MM:SS from an ISO timestamp string."""
        if not timestamp_str or not isinstance(timestamp_str, str):
            return "??:??:??"
        # Handle "2026-01-20T15:27:25.883000+00:00" -> "15:27:25"
        try:
            t_part = timestamp_str.split("T")[1] if "T" in timestamp_str else timestamp_str
            return t_part[:8]
        except (IndexError, TypeError):
            return "??:??:??"

    def render(self, params: dict) -> str:
        """Render evidence block. Subclasses must implement this."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement render()")
