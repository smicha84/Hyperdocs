#!/usr/bin/env python3
"""
Session Metadata Tracker — Running Session Statistics
=====================================================

Maintains a JSON state file accumulating per-session statistics
from real-time Edit/Write captures. Pure Python, $0, <10ms per call.

Tracks:
  - Operation count (edits, writes)
  - Files touched (unique set)
  - File edit frequency (churn detection)
  - Session timing (start, last activity, duration)
  - Debugging loop detection (same file edited >5 times)

Usage:
    # As a library (called from realtime_dispatcher.py):
    from realtime.session_metadata_tracker import SessionTracker
    tracker = SessionTracker(session_id="abc123")
    tracker.record_operation("Edit", "/path/to/file.py")
    summary = tracker.get_summary()

    # CLI for testing:
    python3 session_metadata_tracker.py --status
    python3 session_metadata_tracker.py --record Edit /path/to/file.py
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict


class SessionTracker:
    """Accumulates session metadata in a JSON state file."""

    CHURN_THRESHOLD = 5  # >5 edits to same file = churn

    def __init__(self, session_id: str = None, state_dir: str = None):
        self.session_id = session_id or os.getenv("CLAUDE_SESSION_ID", "unknown")

        if state_dir:
            self.state_dir = Path(state_dir)
        else:
            self.state_dir = Path.home() / "PERMANENT_HYPERDOCS" / "realtime"

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / f"session_{self.session_id[:8]}_state.json"
        self.state = self._load()

    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        return {
            "session_id": self.session_id,
            "session_start": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "total_operations": 0,
            "edit_count": 0,
            "write_count": 0,
            "files_touched": [],
            "file_edit_counts": {},
            "churn_files": [],
            "debugging_loops": 0,
            "py_files_edited": [],
            "extensions_seen": {},
        }

    def _save(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def record_operation(self, tool_name: str, file_path: str):
        """Record a single Edit/Write operation."""
        now = datetime.now().isoformat()
        self.state["last_activity"] = now
        self.state["total_operations"] += 1

        if tool_name == "Edit":
            self.state["edit_count"] += 1
        elif tool_name == "Write":
            self.state["write_count"] += 1

        # Track file
        filename = Path(file_path).name
        if filename not in self.state["files_touched"]:
            self.state["files_touched"].append(filename)

        # Track edit frequency
        counts = self.state["file_edit_counts"]
        counts[filename] = counts.get(filename, 0) + 1

        # Detect churn
        if counts[filename] == self.CHURN_THRESHOLD + 1:
            if filename not in self.state["churn_files"]:
                self.state["churn_files"].append(filename)
                self.state["debugging_loops"] += 1

        # Track Python files specifically
        ext = Path(file_path).suffix
        if ext == ".py" and filename not in self.state["py_files_edited"]:
            self.state["py_files_edited"].append(filename)

        # Track extensions
        exts = self.state["extensions_seen"]
        exts[ext] = exts.get(ext, 0) + 1

        self._save()

    def get_summary(self) -> dict:
        """Return current session summary."""
        s = self.state

        # Calculate duration
        try:
            start = datetime.fromisoformat(s["session_start"])
            last = datetime.fromisoformat(s["last_activity"])
            duration_min = (last - start).total_seconds() / 60
        except (ValueError, TypeError):
            duration_min = 0

        # Top files by edit count
        sorted_files = sorted(
            s["file_edit_counts"].items(),
            key=lambda x: -x[1]
        )

        return {
            "session_id": s["session_id"],
            "duration_minutes": round(duration_min, 1),
            "total_operations": s["total_operations"],
            "edits": s["edit_count"],
            "writes": s["write_count"],
            "unique_files": len(s["files_touched"]),
            "py_files": len(s["py_files_edited"]),
            "churn_files": s["churn_files"],
            "debugging_loops": s["debugging_loops"],
            "top_files": sorted_files,
            "extensions": s["extensions_seen"],
        }

    def is_churn(self, file_path: str) -> bool:
        """Check if a specific file is in churn state."""
        return Path(file_path).name in self.state["churn_files"]


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Session Metadata Tracker")
    parser.add_argument("--status", action="store_true", help="Show current session state")
    parser.add_argument("--record", nargs=2, metavar=("TOOL", "FILE"), help="Record an operation")
    parser.add_argument("--session-id", type=str, default="test_session", help="Session ID")
    args = parser.parse_args()

    tracker = SessionTracker(session_id=args.session_id)

    if args.record:
        tool_name, file_path = args.record
        tracker.record_operation(tool_name, file_path)
        print(f"Recorded: {tool_name} {file_path}")
        summary = tracker.get_summary()
        print(f"  Total ops: {summary['total_operations']}, Files: {summary['unique_files']}, Churn: {summary['churn_files']}")
        return

    if args.status:
        summary = tracker.get_summary()
        print(json.dumps(summary, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
