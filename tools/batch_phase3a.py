#!/usr/bin/env python3
"""
Batch runner for Phase 3a (collect_file_evidence.py) across multiple sessions.

Finds sessions that have Phase 2 complete but no file_evidence/ directory,
and runs collect_file_evidence.py on each. Pure Python, $0.

Usage:
    python3 tools/batch_phase3a.py --count 50
    python3 tools/batch_phase3a.py --count 50 --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.log_config import get_logger

logger = get_logger("tools.batch_phase3a")

REPO = Path(__file__).resolve().parent.parent
PHASE3_SCRIPT = REPO / "phase_3_hyperdoc_writing" / "collect_file_evidence.py"
OUTPUT_DIR = REPO / "output"
PERM_SESSIONS = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS"))) / "sessions"


def find_eligible_sessions(limit):
    """Find sessions with Phase 2 complete but no file_evidence/ directory."""
    eligible = []
    seen = set()

    for base in [PERM_SESSIONS, OUTPUT_DIR]:
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or not d.name.startswith("session_"):
                continue
            sid = d.name.replace("session_", "")[:8]
            if sid in seen:
                continue
            seen.add(sid)

            # Check prerequisites
            has_metadata = (d / "session_metadata.json").exists()
            has_threads = (d / "thread_extractions.json").exists()
            has_idea_graph = (d / "idea_graph.json").exists()
            has_markers = (d / "grounded_markers.json").exists()

            # Check if already done (in either location)
            has_evidence_local = (OUTPUT_DIR / f"session_{sid}" / "file_evidence").exists()
            has_evidence_perm = (PERM_SESSIONS / f"session_{sid}" / "file_evidence").exists()

            if has_metadata and has_threads and has_idea_graph and has_markers:
                if not has_evidence_local and not has_evidence_perm:
                    eligible.append(sid)

            if len(eligible) >= limit:
                break
        if len(eligible) >= limit:
            break

    return eligible


def run_phase3a(session_id):
    """Run collect_file_evidence.py on a single session."""
    env = {
        **os.environ,
        "HYPERDOCS_SESSION_ID": session_id,
        "HYPERDOCS_OUTPUT_DIR": str(OUTPUT_DIR),
    }

    result = subprocess.run(
        [sys.executable, str(PHASE3_SCRIPT), "--session", session_id],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Count evidence files created
    evidence_dir = OUTPUT_DIR / f"session_{session_id}" / "file_evidence"
    count = len(list(evidence_dir.glob("*_evidence.json"))) if evidence_dir.exists() else 0

    return result.returncode == 0, count, result.stderr[:200] if result.stderr else ""


def main():
    parser = argparse.ArgumentParser(description="Batch Phase 3a runner")
    parser.add_argument("--count", type=int, default=50, help="Number of sessions to process")
    parser.add_argument("--dry-run", action="store_true", help="List sessions without processing")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"Batch Phase 3a: collect_file_evidence.py")
    logger.info(f"Target: {args.count} sessions")
    logger.info("=" * 60)

    sessions = find_eligible_sessions(args.count)
    logger.info(f"Found {len(sessions)} eligible sessions (Phase 2 done, no file_evidence/)")

    if args.dry_run:
        for sid in sessions:
            logger.info(f"  Would process: {sid}")
        return

    total_files = 0
    successes = 0
    failures = 0
    t0 = time.time()

    for i, sid in enumerate(sessions):
        logger.info(f"\n[{i+1}/{len(sessions)}] Processing {sid}...", end=" ", flush=True)
        try:
            ok, count, err = run_phase3a(sid)
            if ok:
                successes += 1
                total_files += count
                logger.info(f"{count} evidence files")
            else:
                failures += 1
                logger.error(f"FAILED: {err[:100]}")
        except subprocess.TimeoutExpired:
            failures += 1
            logger.info("TIMEOUT (>120s)")
        except Exception as e:
            failures += 1
            logger.error(f"ERROR: {e}")

    elapsed = time.time() - t0
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Batch Phase 3a complete")
    logger.info(f"  Sessions processed: {successes + failures}")
    logger.info(f"  Successes: {successes}")
    logger.info(f"  Failures: {failures}")
    logger.info(f"  Total evidence files created: {total_files}")
    logger.info(f"  Time: {elapsed:.1f}s ({elapsed/max(len(sessions),1):.1f}s per session)")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
