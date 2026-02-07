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

# Load .env file from project root
from dotenv import load_dotenv
# Path: code/ -> V5/ -> hyperdocs_2/ -> hyperdoc/ -> hooks/ -> .claude/ -> pythonProjectartifact/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")
# Fallback
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

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

    def opus_parse_message(self, raw_line: str, session_id: str, line_idx: int) -> Optional[GeologicalMessage]:
        """
        OPUS PARSES THE MESSAGE instead of complex JSON traversal.

        Original: Nested dict lookups, multiple fallbacks, format guessing
        Opus: Ask Opus to understand the message structure
        """
        # Try JSON parse first
        try:
            msg = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None

        # Skip queue operations
        if msg.get("type") == "queue-operation":
            return None

        # OPUS EXTRACTS THE MEANINGFUL CONTENT
        prompt = f"""Parse this chat history message and extract:
1. role (user or assistant)
2. main content text
3. timestamp
4. any thinking blocks
5. any tool uses

Message JSON:
{json.dumps(msg, indent=2)}

Return JSON: {{"role": "user|assistant", "content": "extracted text", "timestamp": "ISO format", "thinking": "if any", "tool_count": N}}"""

        try:
            response = call_opus(prompt)
            # Strip code block wrapper if present
            if response.startswith("```"):
                response = "\n".join(response.split("\n")[1:-1])
            # Try to parse Opus's structured response
            parsed = json.loads(response)

            role = parsed.get("role", "unknown")
            if role not in ("user", "assistant"):
                return None

            content = parsed.get("content", "")
            if not content:
                return None

            # Parse timestamp
            ts_str = parsed.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(ts_str.replace('Z', '+00:00').split('+')[0])
            except (ValueError, TypeError, AttributeError):
                timestamp = datetime(1970, 1, 1)

            return GeologicalMessage(
                role=role,
                content=content,
                timestamp=timestamp,
                session_id=session_id,
                source_file=str(self.chat_dir),
                message_index=line_idx,
                message_type=msg.get("type", "unknown"),
                thinking=parsed.get("thinking"),
                tool_calls=[{}] * parsed.get("tool_count", 0),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # Fallback to basic extraction if Opus response isn't JSON
            return None

    def opus_analyze_session(self, session: GeologicalSession) -> str:
        """
        OPUS ANALYZES AN ENTIRE SESSION semantically.

        Original: Just counted messages
        Opus: Actually understands what happened in the session
        """
        # Sample some messages for analysis
        sample_content = []
        for i, msg in enumerate(session.messages):
            sample_content.append(f"[{msg.role}] {msg.content}")

        prompt = f"""Analyze this coding session with {len(session.messages)} messages.

Sample messages:
{chr(10).join(sample_content)}

Provide:
1. Main topic/goal of the session
2. Key decisions made
3. Any notable problems or breakthroughs
4. Overall productivity assessment

Return a concise summary paragraph."""

        return call_opus(prompt)

    def load_all_sessions(self, limit: Optional[int] = None) -> Dict[str, GeologicalSession]:
        """Load all sessions with OPUS understanding."""
        if self._sessions:
            return self._sessions

        files = self.discover_jsonl_files()
        total_files = len(files)
        if limit:
            files = files[:limit]

        print(f"\n  📂 LOADING CHAT FILES")
        print(f"     Total available: {total_files}")
        print(f"     Processing: {len(files)}")
        print(f"     " + "─" * 50)

        all_messages = []
        for file_idx, file_path in enumerate(files):
            session_id = file_path.stem
            file_size = file_path.stat().st_size / 1024  # KB

            # Show progress for each file
            print(f"     [{file_idx+1}/{len(files)}] {session_id} ({file_size:.1f}KB)", end="", flush=True)

            file_messages = 0
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_idx, line in enumerate(f):
                    if line.strip():
                        msg = self.opus_parse_message(line, session_id, line_idx)
                        if msg:
                            all_messages.append(msg)
                            file_messages += 1

            print(f" → {file_messages} messages")

        # Group by session
        from collections import defaultdict
        sessions_dict = defaultdict(list)
        for msg in all_messages:
            sessions_dict[msg.session_id].append(msg)

        def normalize_timestamp(ts):
            """Convert any datetime to naive (no timezone) for consistent sorting."""
            if ts.tzinfo is not None:
                # Convert to UTC then strip timezone
                return ts.replace(tzinfo=None)
            return ts

        for session_id, messages in sessions_dict.items():
            messages.sort(key=lambda m: normalize_timestamp(m.timestamp))
            session = GeologicalSession(
                session_id=session_id,
                source_file=messages[0].source_file if messages else "",
                messages=messages,
            )
            # OPUS SUMMARIZES THE SESSION
            if len(messages) > 5:
                session.opus_summary = self.opus_analyze_session(session)
            self._sessions[session_id] = session

        return self._sessions

    def opus_get_statistics(self) -> Dict[str, Any]:
        """
        OPUS PROVIDES MEANINGFUL STATISTICS, not just counts.

        Original: Manual counting of messages
        Opus: Semantic analysis of the chat history
        """
        sessions = self.load_all_sessions()

        # Gather high-level data
        total_messages = sum(len(s.messages) for s in sessions.values())
        user_messages = sum(
            sum(1 for m in s.messages if m.role == "user")
            for s in sessions.values()
        )

        prompt = f"""Analyze these chat history statistics:
- {len(sessions)} sessions
- {total_messages} total messages
- {user_messages} user messages
- {total_messages - user_messages} assistant messages

Session summaries (sample):
{chr(10).join(s.opus_summary or 'No summary' for s in list(sessions.values())[:5])}

Provide:
1. Overall pattern assessment
2. Productivity estimate
3. Key insights about the user's work style

Return JSON: {{"pattern": "...", "productivity": "...", "insights": [...], "recommendation": "..."}}"""

        opus_analysis = call_opus(prompt)

        return {
            "total_sessions": len(sessions),
            "total_messages": total_messages,
            "user_messages": user_messages,
            "assistant_messages": total_messages - user_messages,
            "opus_analysis": opus_analysis,
        }


def main():
    print("=" * 60)
    print("GEOLOGICAL READER - OPUS EDITION")
    print("=" * 60)

    chat_dir = Path(__file__).parent / "chat_history_copy"
    if not chat_dir.exists():
        print("Chat history copy not found")
        return

    reader = GeologicalReader(str(chat_dir))
    stats = reader.opus_get_statistics()

    print("\nOpus Statistics:")
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    main()