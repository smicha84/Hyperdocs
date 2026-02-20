# OPUS TRANSFORMATION: Replace JSON parsing heuristics and timestamp extraction
#                      with Opus-based semantic understanding of chat messages
################################################################################

#!/usr/bin/env python3
"""
Geological Reader - OPUS EDITION

WHAT CHANGED:
- Message parsing: Was JSON field extraction → Now Opus understands message structure
- Timestamp extraction: Was datetime parsing → Now Opus interprets various formats
- Content extraction: Was nested dict traversal → Now Opus extracts meaningful content
- Statistics: Was manual counting → Now Opus provides semantic analysis

OPUS READS AND UNDERSTANDS. Python handles file I/O.
"""
#ARCHITECTURE: Opus wrapper around chat history - delegates ALL parsing/interpretation to LLM instead of code
#WHY: opus_parse_message: Uses LLM to handle arbitrary JSON message formats rather than brittle field lookups - trades speed for robustness
#PERFORMANCE: EXPENSIVE: Every message line triggers an Opus API call - O(n) API calls where n=total lines across all files
#FRAGILE: Relies on Opus returning valid JSON from freeform prompt - no schema validation, silent fallback to None on parse failure


import json
import anthropic
from pathlib import Path
from datetime import datetime
from typing import Iterator, List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# Load .env file — walk up from current location until we find one
from dotenv import load_dotenv
_search = Path(__file__).resolve().parent
for _ in range(10):
    if (_search / ".env").exists():
        load_dotenv(_search / ".env")
        break
    _search = _search.parent
else:
    load_dotenv()  # Try default locations

client = anthropic.Anthropic()

# API call logging for viewer visibility
API_CALL_LOG_FILE = Path(__file__).parent / "api_call_log.json"

def log_api_call(call_type: str, prompt: str, system: str = "", response: str = "", status: str = "pending"):
    """Log API calls so the viewer can show what's happening."""
    return  # DISABLED
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "call_type": call_type,
        "status": status,
        "system_prompt": system if system else "(default)",
        "user_prompt": prompt,
        "prompt_length": len(prompt),
        "response": response if response else "",
        "response_length": len(response) if response else 0,
    }

    try:
        if API_CALL_LOG_FILE.exists():
            with open(API_CALL_LOG_FILE) as f:
                logs = json.load(f)
        else:
            logs = []
        logs.append(log_entry)
        with open(API_CALL_LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2)
    except (json.JSONDecodeError, OSError, PermissionError):
        pass

def call_opus(prompt: str, system: str = "", call_type: str = "geological_reader") -> str:
    """Call Claude Opus 4.5 for all reasoning tasks."""
    # Log BEFORE the call
    log_api_call(call_type, prompt, system, status="calling")

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
        system=system if system else "You are analyzing chat history data. Be precise.",
        messages=[{"role": "user", "content": prompt}]
    )
    result = response.content[0].text if response.content else ""

    # Log AFTER with response
    log_api_call(call_type, prompt, system, result, status="completed")

    return result

@dataclass
class GeologicalMessage:
    """A single message from the geological record."""
    role: str
    content: str
    timestamp: datetime
    session_id: str
    source_file: str
    message_index: int
    message_type: str
    thinking: Optional[str] = None
    tool_calls: List[Dict] = field(default_factory=list)
    opus_analysis: Optional[str] = None  # NEW: Opus's semantic understanding

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "opus_analysis": self.opus_analysis,
        }

@dataclass
class GeologicalSession:
    """A complete conversation session."""
    session_id: str
    source_file: str
    messages: List[GeologicalMessage] = field(default_factory=list)
    opus_summary: Optional[str] = None  # NEW: Opus's session summary

    @property
    def start_time(self) -> Optional[datetime]:
        return min(m.timestamp for m in self.messages) if self.messages else None

    @property
    def end_time(self) -> Optional[datetime]:
        return max(m.timestamp for m in self.messages) if self.messages else None


class GeologicalReader:
    """
    Reads chat history USING OPUS FOR ALL INTERPRETATION.

    Original: Complex JSON parsing with heuristics
    Opus Edition: Opus understands message structure semantically
    """

    def __init__(self, chat_dir: str, verbose: bool = False):
        self.chat_dir = Path(chat_dir)
        self.verbose = verbose
        # Note: Reading from real-time Claude history is now allowed (read-only operation)
        original_dir = Path.home() / ".claude" / "projects"
        if str(self.chat_dir.resolve()).startswith(str(original_dir)):
            print(f"📖 Reading from real-time Claude chat history (read-only)")
        self._sessions: Dict[str, GeologicalSession] = {}

    def discover_jsonl_files(self) -> List[Path]:
        """Discover all JSONL files."""
        return sorted(self.chat_dir.glob("**/*.jsonl"))

    def deterministic_parse_message(self, raw_line: str, session_id: str, line_idx: int) -> Optional[GeologicalMessage]:
        """
        Parse a JSONL message line using pure Python — no LLM calls.

        This replaced opus_parse_message() which called Opus at $0.05/line
        for what is essentially JSON traversal. V1 did this with pure Python
        for free. User insight at msg 2272: 'the v1 actually ran and produced
        hyperdocs... we didn't add a whole llm layer.'
        """
        try:
            msg = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None

        # Skip non-message types
        msg_type = msg.get("type", "")
        if msg_type in ("queue-operation", "system", "progress"):
            return None

        # Extract role
        role = msg.get("role", "")
        if not role:
            message_obj = msg.get("message", {})
            if isinstance(message_obj, dict):
                role = message_obj.get("role", "")
        if role not in ("user", "assistant"):
            return None

        # Extract content
        content = ""
        raw_content = msg.get("content", msg.get("message", {}).get("content", ""))
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            text_parts = []
            for block in raw_content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        pass  # Skip thinking blocks for content
            content = " ".join(text_parts)

        if not content:
            return None

        # Extract timestamp
        ts_str = msg.get("timestamp", msg.get("createdAt", ""))
        try:
            timestamp = datetime.fromisoformat(ts_str.replace('Z', '+00:00').split('+')[0]) if ts_str else datetime(1970, 1, 1)
        except (ValueError, TypeError, AttributeError):
            timestamp = datetime(1970, 1, 1)

        # Extract thinking
        thinking = None
        if isinstance(raw_content, list):
            for block in raw_content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    thinking = block.get("thinking", block.get("text", ""))
                    break

        # Extract tool calls
        tool_calls = []
        if isinstance(raw_content, list):
            for block in raw_content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append({
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                    })

        return GeologicalMessage(
            role=role,
            content=content,
            timestamp=timestamp,
            session_id=session_id,
            source_file=str(self.chat_dir),
            message_index=line_idx,
            message_type=msg_type or msg.get("type", "unknown"),
            thinking=thinking,
            tool_calls=tool_calls,
        )

    # ── DEPRECATED: Opus-per-line methods ──────────────────────────────────
    # These methods called Opus API per message line at ~$0.05/line.
    # Replaced by deterministic_parse_message() which uses pure Python for free.
    # Kept as stubs to prevent silent reactivation. See Chapter 4 in MEMORY.md.

    def opus_parse_message(self, raw_line: str, session_id: str, line_idx: int) -> Optional[GeologicalMessage]:
        """DEPRECATED: Called Opus per line ($0.05/line). Use deterministic_parse_message() instead."""
        raise NotImplementedError(
            "opus_parse_message is deprecated. Use deterministic_parse_message() instead. "
            "This method called Opus API per message line, costing ~$0.05/line."
        )

    def opus_analyze_session(self, session: GeologicalSession) -> str:
        """DEPRECATED: Called Opus to summarize each session. No longer used."""
        raise NotImplementedError(
            "opus_analyze_session is deprecated. Session analysis is now handled by "
            "Phase 1 agents (Thread Analyst, Geological Reader, etc.) via phase1_redo_orchestrator.py."
        )

    def load_all_sessions(self, limit: Optional[int] = None) -> Dict[str, GeologicalSession]:
        """DEPRECATED: Used opus_parse_message + opus_analyze_session. Do not call."""
        raise NotImplementedError(
            "load_all_sessions is deprecated. It called opus_parse_message per line and "
            "opus_analyze_session per session. Use ClaudeSessionReader + deterministic_prep.py instead."
        )

    def opus_get_statistics(self) -> Dict[str, Any]:
        """DEPRECATED: Called Opus for statistics. Do not call."""
        raise NotImplementedError(
            "opus_get_statistics is deprecated. Statistics are now computed by "
            "deterministic_prep.py (Phase 0) and the Explorer agent (Phase 1)."
        )


def main():
    """Standalone test: load a session using pure Python parsing."""
    print("=" * 60)
    print("GEOLOGICAL READER (deterministic mode)")
    print("=" * 60)

    chat_dir = Path(__file__).parent / "chat_history_copy"
    if not chat_dir.exists():
        print("Chat history copy not found. This file is used as a library by deterministic_prep.py.")
        print("Run: python3 deterministic_prep.py")
        return

    reader = GeologicalReader(str(chat_dir))
    files = reader.discover_jsonl_files()
    print(f"Found {len(files)} JSONL files")

    if files:
        # Parse first file using deterministic method
        count = 0
        with open(files[0], 'r', encoding='utf-8', errors='ignore') as f:
            for line_idx, line in enumerate(f):
                if line.strip():
                    msg = reader.deterministic_parse_message(line, files[0].stem, line_idx)
                    if msg:
                        count += 1
        print(f"Parsed {count} messages from {files[0].name} (deterministic, $0)")

if __name__ == "__main__":
    main()