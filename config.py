"""
Hyperdocs Configuration

All configurable values in one place. Set via environment variables or modify defaults here.

Environment variables:
    HYPERDOCS_SESSION_ID     — The Claude Code session ID to process
    HYPERDOCS_CHAT_HISTORY   — Path to the JSONL chat history file
    HYPERDOCS_OUTPUT_DIR     — Where to write pipeline outputs (default: ./output)
    ANTHROPIC_API_KEY        — Required for phases 1-3 (agent LLM calls)
"""
import os
import sys
from pathlib import Path

# Session to process
SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")

# Input: path to the JSONL chat history file
CHAT_HISTORY_PATH = os.getenv("HYPERDOCS_CHAT_HISTORY", "")

# Output directory (created automatically)
OUTPUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output"))

# Claude Code stores sessions here by default
CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "projects"

# Repo root (where this config.py lives)
REPO_ROOT = Path(__file__).resolve().parent


def get_session_path():
    """Resolve the chat history file path."""
    if CHAT_HISTORY_PATH:
        p = Path(CHAT_HISTORY_PATH)
        if p.exists():
            return p
        print(f"ERROR: Chat history not found at {p}")
        sys.exit(1)

    if SESSION_ID:
        # Search Claude Code's default location
        for project_dir in CLAUDE_SESSIONS_DIR.iterdir():
            candidate = project_dir / f"{SESSION_ID}.jsonl"
            if candidate.exists():
                return candidate

        print(f"ERROR: Session {SESSION_ID} not found in {CLAUDE_SESSIONS_DIR}")
        sys.exit(1)

    print("ERROR: Set HYPERDOCS_SESSION_ID or HYPERDOCS_CHAT_HISTORY")
    print("  export HYPERDOCS_SESSION_ID=your-session-id")
    print("  export HYPERDOCS_CHAT_HISTORY=/path/to/session.jsonl")
    sys.exit(1)


def get_output_dir():
    """Get or create the output directory for this session."""
    if SESSION_ID:
        out = OUTPUT_DIR / f"session_{SESSION_ID[:8]}"
    else:
        out = OUTPUT_DIR / "session"
    out.mkdir(parents=True, exist_ok=True)
    return out
