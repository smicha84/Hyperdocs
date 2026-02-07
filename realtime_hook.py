#!/usr/bin/env python3
"""
Hyperdocs Real-Time Hook — Captures Edit/Write operations as they happen.

This runs as an async PostToolUse hook. It receives JSON on stdin describing
what Claude just edited, and appends it to a buffer file. Zero LLM calls.
Zero cost. Zero blocking.

Hook config (.claude/settings.json):
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "python3 /path/to/realtime_hook.py",
        "async": true,
        "timeout": 5
      }]
    }]
  }
}
"""
import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Buffer file location — in the hyperdocs output directory
BUFFER_DIR = Path(os.getenv(
    "HYPERDOCS_OUTPUT_DIR",
    str(Path(__file__).resolve().parent / "output")
))
BUFFER_FILE = BUFFER_DIR / "realtime_buffer.jsonl"


def extract_operation(hook_data):
    """Extract the relevant fields from a PostToolUse hook payload."""
    tool_input = hook_data.get("tool_input", {})
    tool_name = hook_data.get("tool_name", "unknown")

    if tool_name == "Edit":
        return {
            "timestamp": datetime.now().isoformat(),
            "tool": "Edit",
            "file_path": tool_input.get("file_path", ""),
            "old_string_len": len(tool_input.get("old_string", "")),
            "new_string_len": len(tool_input.get("new_string", "")),
            "old_preview": tool_input.get("old_string", "")[:80],
            "new_preview": tool_input.get("new_string", "")[:80],
            "replace_all": tool_input.get("replace_all", False),
        }
    elif tool_name == "Write":
        content = tool_input.get("content", "")
        return {
            "timestamp": datetime.now().isoformat(),
            "tool": "Write",
            "file_path": tool_input.get("file_path", ""),
            "content_len": len(content),
            "content_lines": content.count("\n") + 1,
        }
    else:
        return {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "raw_keys": list(tool_input.keys()),
        }


def append_to_buffer(operation):
    """Append one operation to the buffer file."""
    BUFFER_DIR.mkdir(parents=True, exist_ok=True)
    with open(BUFFER_FILE, "a") as f:
        f.write(json.dumps(operation) + "\n")


def get_buffer_stats():
    """Get current buffer statistics."""
    if not BUFFER_FILE.exists():
        return {"operations": 0, "files_touched": set()}

    operations = 0
    files = set()
    with open(BUFFER_FILE) as f:
        for line in f:
            operations += 1
            try:
                op = json.loads(line)
                fp = op.get("file_path", "")
                if fp:
                    files.add(fp)
            except json.JSONDecodeError:
                pass

    return {"operations": operations, "files_touched": files}


def main():
    # Read hook payload from stdin
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        hook_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return

    # Extract and buffer
    operation = extract_operation(hook_data)
    append_to_buffer(operation)

    # Every 10 operations, print a micro-summary to stderr (visible in hook logs)
    stats = get_buffer_stats()
    if stats["operations"] % 10 == 0:
        sys.stderr.write(
            f"[Hyperdocs] {stats['operations']} operations captured, "
            f"{len(stats['files_touched'])} files touched\n"
        )


if __name__ == "__main__":
    main()
