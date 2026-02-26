#!/usr/bin/env python3
"""Batch pipeline runner with checkpoint-based retry/resume.

Processes multiple sessions through the pipeline, tracking progress in a
checkpoint file. If interrupted, re-running picks up from where it stopped.

Usage:
    python3 tools/batch_runner.py                          # All sessions, free phases
    python3 tools/batch_runner.py --full                   # All sessions, all phases
    python3 tools/batch_runner.py --phase 2                # All sessions, Phase 2 only
    python3 tools/batch_runner.py --resume                 # Resume from last checkpoint
    python3 tools/batch_runner.py --sessions s1 s2 s3      # Specific sessions
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from config import SESSIONS_STORE_DIR, INDEXES_DIR
from tools.log_config import get_logger

logger = get_logger("tools.batch_runner")

CHECKPOINT_FILE = INDEXES_DIR / "batch_runner_checkpoint.json"


def load_checkpoint():
    """Load checkpoint state or return empty."""
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"completed": [], "failed": [], "in_progress": None, "started_at": None}


def save_checkpoint(state):
    """Save checkpoint atomically."""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        from tools.file_lock import atomic_json_write
        atomic_json_write(CHECKPOINT_FILE, state)
    except ImportError:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(state, f, indent=2)


def discover_sessions():
    """Find all session directories."""
    if not SESSIONS_STORE_DIR.exists():
        return []
    return sorted(
        d.name.replace("session_", "")
        for d in SESSIONS_STORE_DIR.iterdir()
        if d.is_dir() and d.name.startswith("session_") and list(d.glob("*.json"))
    )


def run_session(session_id, phase=None, full=False, force=False):
    """Run pipeline on a single session. Returns (success, duration)."""
    import subprocess
    cmd = [sys.executable, str(REPO / "tools" / "run_pipeline.py"), session_id]
    if phase is not None:
        cmd.extend(["--phase", str(phase)])
    elif full:
        cmd.append("--full")
    if force:
        cmd.append("--force")

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0

    return result.returncode == 0, elapsed


def main():
    parser = argparse.ArgumentParser(description="Batch pipeline runner with retry/resume")
    parser.add_argument("--sessions", nargs="+", help="Specific session IDs to process")
    parser.add_argument("--phase", type=int, choices=[0, 1, 2, 3], help="Run only this phase")
    parser.add_argument("--full", action="store_true", help="Run all phases")
    parser.add_argument("--force", action="store_true", help="Re-run even if output exists")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()

    # Discover sessions
    if args.sessions:
        sessions = args.sessions
    else:
        sessions = discover_sessions()

    if not sessions:
        logger.info("No sessions found.")
        return

    # Load checkpoint for resume
    checkpoint = load_checkpoint()
    if args.resume:
        completed = set(checkpoint.get("completed", []))
        sessions = [s for s in sessions if s not in completed]
        logger.info(f"Resuming: {len(completed)} already done, {len(sessions)} remaining")
    else:
        checkpoint = {"completed": [], "failed": [], "in_progress": None,
                      "started_at": datetime.now(timezone.utc).isoformat()}
        save_checkpoint(checkpoint)

    logger.info(f"Batch Runner: {len(sessions)} sessions")
    logger.info(f"Checkpoint: {CHECKPOINT_FILE}")
    logger.info("")

    total_time = 0
    for i, sid in enumerate(sessions, 1):
        logger.info(f"[{i}/{len(sessions)}] {sid}")
        checkpoint["in_progress"] = sid
        save_checkpoint(checkpoint)

        ok, elapsed = run_session(sid, phase=args.phase, full=args.full, force=args.force)
        total_time += elapsed

        if ok:
            checkpoint["completed"].append(sid)
            checkpoint["in_progress"] = None
            logger.info(f"  OK ({elapsed:.1f}s)")
        else:
            checkpoint["failed"].append({"session": sid, "duration": elapsed})
            checkpoint["in_progress"] = None
            logger.error(f"  FAILED ({elapsed:.1f}s)")

        save_checkpoint(checkpoint)

    # Summary
    n_ok = len(checkpoint["completed"])
    n_fail = len(checkpoint["failed"])
    logger.error(f"\nBatch complete: {n_ok} succeeded, {n_fail} failed, {total_time:.0f}s total")
    if n_fail:
        logger.error("Failed sessions:")
        for f in checkpoint["failed"]:
            logger.info(f"  {f['session']} ({f['duration']:.1f}s)")


if __name__ == "__main__":
    main()
