"""
Hyperdocs Configuration — Central settings for all phases.

All scripts import from here. Override with environment variables:
    HYPERDOCS_SESSION_ID     — Session UUID to process
    HYPERDOCS_CHAT_HISTORY   — Path to JSONL file
    HYPERDOCS_OUTPUT_DIR     — Where pipeline writes outputs
    HYPERDOCS_ARCHIVE_PATH   — Path to PERMANENT_ARCHIVE (optional)
    HYPERDOCS_PROJECT_ID     — Claude Code project identifier (optional)
    ANTHROPIC_API_KEY        — Required for phases 1-3
"""
import os
import sys
from pathlib import Path

# ── Session ────────────────────────────────────────────────────
SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
SESSION_SHORT = SESSION_ID[:8] if SESSION_ID else ""

# ── Paths ──────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent
CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "projects"

# Chat history input
CHAT_HISTORY_PATH = os.getenv("HYPERDOCS_CHAT_HISTORY", "")

# Canonical chat history directory (all sessions, never deleted)
CHAT_HISTORY_DIR = Path(os.getenv(
    "HYPERDOCS_CHAT_HISTORY_DIR",
    str(Path.home() / "PERMANENT_CHAT_HISTORY" / "sessions")
))

# Output directory
OUTPUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(REPO_ROOT / "output")))

# PERMANENT_ARCHIVE (optional, for bulk processing)
ARCHIVE_PATH = os.getenv("HYPERDOCS_ARCHIVE_PATH", "")

# Claude Code project identifier (for session file lookup)
PROJECT_ID = os.getenv("HYPERDOCS_PROJECT_ID", "")

# ── V5 Source Code Directory ──────────────────────────────────
# Phase 4 (insertion) and Phase 5 (ground truth) read source files from disk.
# The improved modules live directly in phase_0_prep/ (v5_compat dissolved).
V5_SOURCE_DIR = Path(os.getenv(
    "HYPERDOCS_V5_SOURCE",
    str(REPO_ROOT / "phase_0_prep")
))

# ── Permanent Storage ─────────────────────────────────────────
STORE_DIR = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS")))
SESSIONS_STORE_DIR = STORE_DIR / "sessions"
INDEXES_DIR = STORE_DIR / "indexes"
HYPERDOCS_STORE_DIR = STORE_DIR / "hyperdocs"
CHAT_ARCHIVE_DIR = Path(os.getenv("HYPERDOCS_CHAT_ARCHIVE", str(Path.home() / "PERMANENT_CHAT_HISTORY")))

# ── Helpers ────────────────────────────────────────────────────

def get_session_output_dir():
    """Get or create the output directory for the current session."""
    if SESSION_SHORT:
        out = OUTPUT_DIR / f"session_{SESSION_SHORT}"
    else:
        out = OUTPUT_DIR / "session"
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_session_file():
    """Find the JSONL chat history file."""
    if CHAT_HISTORY_PATH:
        p = Path(CHAT_HISTORY_PATH)
        if p.exists():
            return p

    if SESSION_ID and PROJECT_ID:
        candidate = CLAUDE_SESSIONS_DIR / PROJECT_ID / f"{SESSION_ID}.jsonl"
        if candidate.exists():
            return candidate

    # Check permanent chat history directory
    if SESSION_ID and CHAT_HISTORY_DIR.exists():
        candidate = CHAT_HISTORY_DIR / f"{SESSION_ID}.jsonl"
        if candidate.exists():
            return candidate

    if SESSION_ID:
        for project_dir in CLAUDE_SESSIONS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{SESSION_ID}.jsonl"
            if candidate.exists():
                return candidate

    return None
