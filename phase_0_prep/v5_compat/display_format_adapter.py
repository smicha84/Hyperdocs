#!/usr/bin/env python3
"""
Display Format Adapter
======================

Adapts the PERMANENT_ARCHIVE "display" format to the GeologicalMessage format
expected by the Hyperdocs pipeline.

PERMANENT_ARCHIVE Format:
{
    "display": "user message text",
    "pastedContents": {"1": {"id": 1, "type": "text", "content": "..."}},
    "timestamp": 1759178513477,  # Unix milliseconds
    "project": "/path/to/project"
}

GeologicalMessage Format:
{
    role: "user",
    content: "message text",
    timestamp: datetime,
    session_id: str,
    ...
}

Key insight: The PERMANENT_ARCHIVE contains USER INPUT only (no Claude responses).
This is still valuable because user frustration, ideas, and file references
are directly visible.

Usage:
    from display_format_adapter import DisplayFormatAdapter

    adapter = DisplayFormatAdapter(archive_path)
    sessions = adapter.load_all_sessions()
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Iterator
from dataclasses import dataclass, field

# Import the target format
try:
    from .geological_reader import GeologicalMessage, GeologicalSession
except ImportError:
    from geological_reader import GeologicalMessage, GeologicalSession


@dataclass
class DisplayMessage:
    """Raw message from PERMANENT_ARCHIVE display format."""
    display: str
    timestamp: int  # Unix milliseconds
    project: str
    pasted_contents: Dict[str, Any] = field(default_factory=dict)

    @property
    def datetime(self) -> datetime:
        """Convert Unix ms timestamp to datetime."""
        return datetime.fromtimestamp(self.timestamp / 1000)

    @property
    def full_content(self) -> str:
        """Get display text plus any pasted content."""
        parts = [self.display]
        for key, val in self.pasted_contents.items():
            if isinstance(val, dict) and 'content' in val:
                parts.append(f"\n[Pasted #{key}]: {val['content'][:500]}")
        return "\n".join(parts)


class DisplayFormatAdapter:
    """
    Adapts PERMANENT_ARCHIVE display format to GeologicalMessage format.

    The PERMANENT_ARCHIVE contains user inputs only. This adapter:
    1. Parses the display format
    2. Groups messages into sessions by date/hour
    3. Converts to GeologicalMessage objects
    4. Returns GeologicalSession objects that the pipeline can consume
    """

    def __init__(self, archive_path: Path, verbose: bool = True):
        self.archive_path = Path(archive_path)
        self.verbose = verbose

        if not self.archive_path.exists():
            raise ValueError(f"Archive path does not exist: {archive_path}")

    def discover_files(self) -> List[Path]:
        """Discover all JSONL files in the archive."""
        return sorted(self.archive_path.glob("*.jsonl"))

    def parse_display_message(self, line: str) -> Optional[DisplayMessage]:
        """Parse a single line from display format."""
        try:
            data = json.loads(line)
            return DisplayMessage(
                display=data.get("display", ""),
                timestamp=data.get("timestamp", 0),
                project=data.get("project", ""),
                pasted_contents=data.get("pastedContents", {})
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def convert_to_geological(self, msg: DisplayMessage, session_id: str, idx: int) -> GeologicalMessage:
        """Convert DisplayMessage to GeologicalMessage."""
        return GeologicalMessage(
            role="user",  # Display format is user-only
            content=msg.full_content,
            timestamp=msg.datetime,
            session_id=session_id,
            source_file=str(self.archive_path),
            message_index=idx,
            message_type="user_input",
            thinking=None,
            tool_calls=[],
            opus_analysis=None
        )

    def load_file(self, file_path: Path) -> Iterator[DisplayMessage]:
        """Load all messages from a single file."""
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                msg = self.parse_display_message(line)
                if msg and msg.display:  # Skip empty messages
                    yield msg

    def compute_session_id(self, file_path: Path) -> str:
        """Generate a session ID from the file path."""
        # Use filename as session ID base
        name = file_path.stem  # e.g., "history_20260205_032740"
        return name

    def load_single_file(self, filename: str) -> Optional[GeologicalSession]:
        """
        Load a single file by name.

        Args:
            filename: Just the filename (e.g., "history_20260205_032740.jsonl")

        Returns:
            GeologicalSession or None if not found
        """
        file_path = self.archive_path / filename
        if not file_path.exists():
            return None

        session_id = Path(filename).stem
        messages = []

        for idx, display_msg in enumerate(self.load_file(file_path)):
            geo_msg = self.convert_to_geological(display_msg, session_id, idx)
            messages.append(geo_msg)

        if messages:
            return GeologicalSession(
                session_id=session_id,
                source_file=str(file_path),
                messages=messages,
                opus_summary=None
            )
        return None

    def load_all_sessions(self, limit: Optional[int] = None) -> Dict[str, GeologicalSession]:
        """
        Load all sessions from the archive.

        Args:
            limit: Maximum number of files to process (for testing)

        Returns:
            Dict mapping session_id to GeologicalSession
        """
        files = self.discover_files()
        if limit:
            files = files[:limit]

        if self.verbose:
            print(f"📂 Loading {len(files)} files from PERMANENT_ARCHIVE")

        sessions = {}
        total_messages = 0

        for file_path in files:
            session_id = self.compute_session_id(file_path)
            messages = []

            for idx, display_msg in enumerate(self.load_file(file_path)):
                geo_msg = self.convert_to_geological(display_msg, session_id, idx)
                messages.append(geo_msg)

            if messages:
                sessions[session_id] = GeologicalSession(
                    session_id=session_id,
                    source_file=str(file_path),
                    messages=messages,
                    opus_summary=None
                )
                total_messages += len(messages)

                if self.verbose:
                    print(f"  📄 {file_path.name}: {len(messages)} user messages")

        if self.verbose:
            print(f"✅ Loaded {len(sessions)} sessions, {total_messages} total messages")

        return sessions

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the archive."""
        files = self.discover_files()

        total_lines = 0
        date_range = {"earliest": None, "latest": None}
        projects = set()

        for file_path in files:
            for msg in self.load_file(file_path):
                total_lines += 1
                projects.add(msg.project)

                if date_range["earliest"] is None or msg.datetime < date_range["earliest"]:
                    date_range["earliest"] = msg.datetime
                if date_range["latest"] is None or msg.datetime > date_range["latest"]:
                    date_range["latest"] = msg.datetime

        return {
            "total_files": len(files),
            "total_messages": total_lines,
            "date_range": {
                "earliest": date_range["earliest"].isoformat() if date_range["earliest"] else None,
                "latest": date_range["latest"].isoformat() if date_range["latest"] else None
            },
            "unique_projects": len(projects)
        }


def main():
    """CLI for testing the adapter."""
    import argparse

    parser = argparse.ArgumentParser(description="Display Format Adapter")
    parser.add_argument("--archive", type=str,
                        default=str(Path.home() / "Desktop" / "all chat history" / "PERMANENT_ARCHIVE"),
                        help="Path to PERMANENT_ARCHIVE")
    parser.add_argument("--stats", action="store_true", help="Show archive statistics")
    parser.add_argument("--limit", type=int, help="Limit files for testing")

    args = parser.parse_args()

    adapter = DisplayFormatAdapter(Path(args.archive))

    if args.stats:
        print("\n📊 Archive Statistics")
        print("=" * 50)
        stats = adapter.get_stats()
        print(f"Total files: {stats['total_files']}")
        print(f"Total messages: {stats['total_messages']}")
        print(f"Date range: {stats['date_range']['earliest']} to {stats['date_range']['latest']}")
        print(f"Unique projects: {stats['unique_projects']}")
    else:
        sessions = adapter.load_all_sessions(limit=args.limit)
        print(f"\nLoaded {len(sessions)} sessions")


if __name__ == "__main__":
    main()
