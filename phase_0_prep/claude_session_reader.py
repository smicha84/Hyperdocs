#!/usr/bin/env python3
"""
Claude Session Reader
=====================

Reads Claude Code session files from ~/.claude/projects/ to extract:
- Claude's responses with token usage (input_tokens, output_tokens)
- Claude's thinking content (verbose thinking)
- Full conversation context (user + assistant messages)

This complements the PERMANENT_ARCHIVE (user input only) with:
- Claude's token consumption per message
- Claude's internal reasoning/thinking

Usage:
    from claude_session_reader import ClaudeSessionReader

    reader = ClaudeSessionReader()
    sessions = reader.load_project_sessions(limit=5)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Iterator
from dataclasses import dataclass, field
from collections import defaultdict

import tiktoken
_encoder = tiktoken.get_encoding("cl100k_base")

def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken (more accurate than JSONL output_tokens)."""
    return len(_encoder.encode(text)) if text else 0


@dataclass
class ClaudeUsage:
    """Token usage for a single Claude response."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    service_tier: str = "standard"

    @property
    def total_input(self) -> int:
        """Total input tokens including cache."""
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens

    def to_dict(self) -> Dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation": self.cache_creation_tokens,
            "cache_read": self.cache_read_tokens,
            "total_input": self.total_input,
            "service_tier": self.service_tier
        }


@dataclass
class ClaudeMessage:
    """A message from a Claude Code session."""
    uuid: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    session_id: str

    # Claude-specific fields (for assistant messages)
    thinking: Optional[str] = None
    thinking_tokens: int = 0
    usage: Optional[ClaudeUsage] = None
    model: Optional[str] = None
    stop_reason: Optional[str] = None

    # Context
    cwd: Optional[str] = None
    git_branch: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "uuid": self.uuid,
            "role": self.role,
            "content_length": len(self.content) if self.content else 0,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "session_id": self.session_id,
            "has_thinking": self.thinking is not None,
            "thinking_length": len(self.thinking) if self.thinking else 0,
            "usage": self.usage.to_dict() if self.usage else None,
            "model": self.model,
            "stop_reason": self.stop_reason
        }


@dataclass
class ClaudeSession:
    """A Claude Code session with all messages."""
    session_id: str
    source_file: str
    messages: List[ClaudeMessage] = field(default_factory=list)

    # Aggregated stats
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_thinking_chars: int = 0

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "source_file": self.source_file,
            "message_count": len(self.messages),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_thinking_chars": self.total_thinking_chars,
            "assistant_messages": sum(1 for m in self.messages if m.role == "assistant"),
            "user_messages": sum(1 for m in self.messages if m.role == "user")
        }


class ClaudeSessionReader:
    """
    Reads Claude Code session files to extract token usage and thinking content.

    Data source: ~/.claude/projects/{project-path}/*.jsonl
    """

    def __init__(self, projects_dir: Optional[Path] = None, verbose: bool = True):
        self.projects_dir = projects_dir or Path.home() / ".claude" / "projects"
        self.verbose = verbose

        if not self.projects_dir.exists():
            raise ValueError(f"Claude projects directory not found: {self.projects_dir}")

    def discover_project_dirs(self) -> List[Path]:
        """Discover all project directories."""
        return [d for d in self.projects_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]

    def discover_session_files(self, project_dir: Optional[Path] = None) -> List[Path]:
        """Discover all session JSONL files in a project directory."""
        if project_dir is None:
            # Search all projects
            files = []
            for proj in self.discover_project_dirs():
                files.extend(sorted(proj.glob("*.jsonl")))
            return files
        return sorted(project_dir.glob("*.jsonl"))

    def parse_message_record(self, record: Dict) -> Optional[ClaudeMessage]:
        """Parse a single message record from JSONL."""
        record_type = record.get("type")
        if record_type not in ("user", "assistant"):
            return None

        # Extract timestamp
        ts = record.get("timestamp")
        if isinstance(ts, (int, float)):
            timestamp = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
        elif isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # Extract message content
        message_data = record.get("message", {})
        content_parts = message_data.get("content", [])

        # Separate text and thinking
        text_content = []
        thinking_content = None

        for part in content_parts:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    text_content.append(part.get("text", ""))
                elif part.get("type") == "thinking":
                    thinking_content = part.get("thinking", "")
            elif isinstance(part, str):
                text_content.append(part)

        content = "\n".join(text_content)

        # Extract usage
        usage_data = message_data.get("usage", {})
        usage = None
        if usage_data:
            usage = ClaudeUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                cache_creation_tokens=usage_data.get("cache_creation_input_tokens", 0),
                cache_read_tokens=usage_data.get("cache_read_input_tokens", 0),
                service_tier=usage_data.get("service_tier", "standard")
            )

        return ClaudeMessage(
            uuid=record.get("uuid", ""),
            role=record_type,
            content=content,
            timestamp=timestamp,
            session_id=record.get("sessionId", ""),
            thinking=thinking_content,
            thinking_tokens=len(thinking_content) if thinking_content else 0,
            usage=usage,
            model=message_data.get("model"),
            stop_reason=message_data.get("stop_reason"),
            cwd=record.get("cwd"),
            git_branch=record.get("gitBranch")
        )

    def load_session_file(self, file_path: Path) -> Optional[ClaudeSession]:
        """Load a single session file."""
        session_id = file_path.stem
        messages = []

        total_input = 0
        total_output = 0
        total_thinking = 0

        try:
            with open(file_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                        msg = self.parse_message_record(record)
                        if msg:
                            messages.append(msg)

                            # Aggregate usage
                            if msg.usage:
                                total_input += msg.usage.total_input
                                # output_tokens from JSONL is a streaming snapshot (often 1-3),
                                # not real output. Use tiktoken on actual content instead.
                                total_output += _count_tokens(msg.content or "")
                            if msg.thinking:
                                total_thinking += len(msg.thinking)

                    except json.JSONDecodeError:
                        continue
        except IOError as e:
            if self.verbose:
                print(f"  [error] Could not read {file_path}: {e}")
            return None

        if not messages:
            return None

        return ClaudeSession(
            session_id=session_id,
            source_file=str(file_path),
            messages=messages,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_thinking_chars=total_thinking
        )

    def load_project_sessions(
        self,
        project_name: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, ClaudeSession]:
        """
        Load sessions from a project.

        Args:
            project_name: Specific project directory name (or None for all)
            limit: Maximum number of sessions to load

        Returns:
            Dict mapping session_id to ClaudeSession
        """
        if project_name:
            project_dir = self.projects_dir / project_name
            if not project_dir.exists():
                raise ValueError(f"Project not found: {project_name}")
            files = self.discover_session_files(project_dir)
        else:
            files = self.discover_session_files()

        if limit:
            files = files[:limit]

        if self.verbose:
            print(f"📂 Loading {len(files)} Claude Code session files")

        sessions = {}
        total_messages = 0
        total_tokens = 0

        for file_path in files:
            session = self.load_session_file(file_path)
            if session:
                sessions[session.session_id] = session
                total_messages += len(session.messages)
                total_tokens += session.total_input_tokens + session.total_output_tokens

                if self.verbose:
                    print(f"  📄 {file_path.name}: {len(session.messages)} msgs, {session.total_input_tokens + session.total_output_tokens:,} tokens")

        if self.verbose:
            print(f"✅ Loaded {len(sessions)} sessions, {total_messages} messages, {total_tokens:,} total tokens")

        return sessions

    def get_session_token_summary(self, session: ClaudeSession) -> Dict[str, Any]:
        """Generate a token usage summary for a session."""
        assistant_msgs = [m for m in session.messages if m.role == "assistant"]

        input_by_model = defaultdict(int)
        output_by_model = defaultdict(int)

        for msg in assistant_msgs:
            if msg.usage and msg.model:
                input_by_model[msg.model] += msg.usage.total_input
                output_by_model[msg.model] += msg.usage.output_tokens

        return {
            "session_id": session.session_id,
            "total_messages": len(session.messages),
            "assistant_messages": len(assistant_msgs),
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "total_thinking_chars": session.total_thinking_chars,
            "input_by_model": dict(input_by_model),
            "output_by_model": dict(output_by_model),
            "avg_tokens_per_response": session.total_output_tokens // len(assistant_msgs) if assistant_msgs else 0
        }


def main():
    """CLI for testing the Claude session reader."""
    import argparse

    parser = argparse.ArgumentParser(description="Claude Session Reader")
    parser.add_argument("--limit", type=int, default=5, help="Limit sessions to load")
    parser.add_argument("--project", type=str, help="Specific project name")
    parser.add_argument("--stats", action="store_true", help="Show token statistics")

    args = parser.parse_args()

    reader = ClaudeSessionReader()

    # List projects
    projects = reader.discover_project_dirs()
    print(f"\n📁 Found {len(projects)} projects")
    for p in projects[:5]:
        print(f"  - {p.name}")
    if len(projects) > 5:
        print(f"  ... and {len(projects) - 5} more")

    # Load sessions
    sessions = reader.load_project_sessions(project_name=args.project, limit=args.limit)

    if args.stats:
        print("\n" + "=" * 60)
        print("TOKEN USAGE SUMMARY")
        print("=" * 60)

        total_input = 0
        total_output = 0
        total_thinking = 0

        for session in sessions.values():
            summary = reader.get_session_token_summary(session)
            total_input += summary["total_input_tokens"]
            total_output += summary["total_output_tokens"]
            total_thinking += summary["total_thinking_chars"]

            print(f"\n{session.session_id[:8]}...")
            print(f"  Messages: {summary['total_messages']} ({summary['assistant_messages']} from Claude)")
            print(f"  Input tokens: {summary['total_input_tokens']:,}")
            print(f"  Output tokens: {summary['total_output_tokens']:,}")
            print(f"  Thinking chars: {summary['total_thinking_chars']:,}")

        print("\n" + "-" * 60)
        print(f"TOTAL INPUT TOKENS: {total_input:,}")
        print(f"TOTAL OUTPUT TOKENS: {total_output:,}")
        print(f"TOTAL THINKING CHARS: {total_thinking:,}")


if __name__ == "__main__":
    main()
