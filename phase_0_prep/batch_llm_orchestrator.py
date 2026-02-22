#!/usr/bin/env python3
"""
Phase 0.5 LLM Batch Orchestrator
====================================

Runs all 4 LLM passes across all unique sessions with concurrent processing.

Pass order:
  Pass 1 (Haiku, 50 concurrent):  Content-referential + assumption subtypes
  Pass 2 (Opus, 30 concurrent):   Silent decisions + unverified claims + overconfidence
  Pass 3 (Opus, 30 concurrent):   Intent assumption resolution (targeted, needs Pass 1)
  Pass 4 (Haiku, 50 concurrent):  Strategic importance scoring

After all passes: merge results into enriched_session_v2.json

Usage:
    python3 batch_llm_orchestrator.py                       # run all passes
    python3 batch_llm_orchestrator.py --pass 1              # run only Pass 1
    python3 batch_llm_orchestrator.py --dry-run             # estimate costs only
    python3 batch_llm_orchestrator.py --session session_X   # one session only
    python3 batch_llm_orchestrator.py --merge-only          # only merge step
    python3 batch_llm_orchestrator.py --status              # show current progress

Cost estimate (~$77 total):
  Pass 1 (Haiku):  162 sessions, ~$8
  Pass 2 (Opus):   162 sessions, ~$52
  Pass 3 (Opus):   ~20-30 flagged sessions, ~$10
  Pass 4 (Haiku):  162 sessions, ~$7
"""

import json
import os
import sys
import io
import time
import argparse
import threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout

# ── Path setup ────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import OUTPUT_DIR
from prompts import PASS_CONFIGS
from llm_pass_runner import (
    find_session_dir, load_enriched_session, run_pass
)
from merge_llm_results import merge_session

# ── Constants ─────────────────────────────────────────────────────────
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import SESSIONS_STORE_DIR as _SS, INDEXES_DIR as _IDX
    SESSIONS_DIR = _SS
    STATUS_FILE = _IDX / "batch_llm_status.json"
    MANIFEST_FILE = _IDX / "duplicate_manifest.json"
except ImportError:
    SESSIONS_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
    STATUS_FILE = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "batch_llm_status.json"
    MANIFEST_FILE = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "duplicate_manifest.json"

# Concurrency limits (proven from historical processing — Chapter 16)
HAIKU_CONCURRENCY = 50
OPUS_CONCURRENCY = 30

# Thread-safe print lock
_print_lock = threading.Lock()


def _safe_print(msg):
    """Thread-safe printing."""
    with _print_lock:
        print(msg, flush=True)


# ── Session discovery ─────────────────────────────────────────────────

def load_skip_ids():
    """Load duplicate session short IDs to skip from the manifest."""
    if not MANIFEST_FILE.exists():
        return set()
    with open(MANIFEST_FILE) as f:
        manifest = json.load(f)
    return set(manifest.get("skip_short_ids", []))


def get_unique_sessions():
    """Get list of unique session directories to process.

    Returns session dirs that:
      1. Have enriched_session.json (Phase 0 complete)
      2. Are NOT in the duplicate skip list
    """
    skip_ids = load_skip_ids()
    sessions = []
    for d in sorted(SESSIONS_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        if not (d / "enriched_session.json").exists():
            continue
        short_id = d.name.replace("session_", "")
        if short_id in skip_ids:
            continue
        sessions.append(d)
    return sessions


# ── Pass completion checks ────────────────────────────────────────────

def pass_output_exists(session_dir, pass_num):
    """Check if a pass output file already exists (for resume support)."""
    output_file = PASS_CONFIGS[pass_num]["output_file"]
    path = session_dir / output_file
    return path.exists()


def merge_output_exists(session_dir):
    """Check if the merged output already exists."""
    return (session_dir / "enriched_session_v2.json").exists()


# ── Worker functions ──────────────────────────────────────────────────

def _run_pass_worker(session_dir, pass_num, pass1_results=None, dry_run=False):
    """Run a single pass on a single session. Called from ThreadPoolExecutor.

    Suppresses stdout from run_pass() to avoid garbled concurrent output.
    Returns a result dict with session name, status, cost, and any error.
    """
    session_name = session_dir.name
    try:
        data = load_enriched_session(session_dir)

        # Suppress run_pass's print output in concurrent mode
        captured = io.StringIO()
        with redirect_stdout(captured):
            result = run_pass(
                pass_num, session_dir, data,
                pass1_results=pass1_results, dry_run=dry_run
            )

        cost = result.get("total_usage", {}).get("cost", 0.0)
        n_results = result.get("results_count", len(result.get("results", [])))

        return {
            "session": session_name,
            "status": "ok",
            "cost": cost,
            "results_count": n_results,
            "messages_analyzed": result.get("messages_analyzed", 0),
        }

    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        return {
            "session": session_name,
            "status": "error",
            "cost": 0.0,
            "error": str(e),
        }


# ── Batch pass execution ─────────────────────────────────────────────

def run_batch_pass(sessions, pass_num, status, dry_run=False):
    """Run a single pass across all sessions with concurrent processing.

    Args:
        sessions: List of session directory Paths
        pass_num: Which pass to run (1-4)
        status: Mutable status dict (updated in place)
        dry_run: If True, estimate costs without API calls
    """
    # Deduplicate sessions by name
    seen = set()
    deduped = []
    for s in sessions:
        if s.name not in seen:
            seen.add(s.name)
            deduped.append(s)
    sessions = deduped

    config = PASS_CONFIGS[pass_num]
    model = config["model"]
    is_opus = "opus" in model
    max_workers = OPUS_CONCURRENCY if is_opus else HAIKU_CONCURRENCY

    # ── Determine which sessions need this pass ──
    if pass_num == 3:
        # Pass 3: only sessions flagged by Pass 1 with assumption subtypes
        todo = []
        for s in sessions:
            if pass_output_exists(s, pass_num):
                continue
            p1_file = s / PASS_CONFIGS[1]["output_file"]
            if not p1_file.exists():
                continue
            with open(p1_file) as f:
                p1_data = json.load(f)
            has_assumptions = any(
                r.get("code_assumption") or r.get("format_assumption") or
                r.get("direction_assumption") or r.get("scope_assumption")
                for r in p1_data.get("results", [])
            )
            if has_assumptions:
                todo.append((s, p1_data))
        already_done = sum(1 for s in sessions if pass_output_exists(s, pass_num))
    else:
        todo_sessions = [s for s in sessions if not pass_output_exists(s, pass_num)]
        todo = [(s, None) for s in todo_sessions]
        already_done = len(sessions) - len(todo)

    # ── Initialize pass status ──
    pass_key = f"pass_{pass_num}"
    pass_status = status.setdefault(pass_key, {
        "name": config["name"],
        "model": model,
        "total_sessions": len(sessions),
        "already_done": already_done,
        "processed": 0,
        "errors": [],
        "total_cost": 0.0,
        "total_results": 0,
    })

    if pass_num == 3:
        pass_status["targeted_sessions"] = len(todo)
        print(f"\n  Pass {pass_num}: {config['name']}")
        print(f"    Model: {model}, Concurrency: {max_workers}")
        print(f"    Targeted (with assumptions): {len(todo)}, Already done: {already_done}")
    else:
        print(f"\n  Pass {pass_num}: {config['name']}")
        print(f"    Model: {model}, Concurrency: {max_workers}")
        print(f"    To process: {len(todo)}, Already done: {already_done}")

    if not todo:
        print(f"    Nothing to do — all sessions already processed")
        return

    # ── Execute with ThreadPoolExecutor ──
    completed = 0
    errors = 0
    pass_cost = 0.0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for session_dir, p1_data in todo:
            future = executor.submit(
                _run_pass_worker, session_dir, pass_num,
                pass1_results=p1_data, dry_run=dry_run
            )
            futures[future] = session_dir.name

        for future in as_completed(futures):
            session_name = futures[future]
            result = future.result()

            if result["status"] == "ok":
                completed += 1
                pass_cost += result["cost"]
                pass_status["total_results"] += result.get("results_count", 0)
            else:
                errors += 1
                pass_status["errors"].append({
                    "session": session_name,
                    "error": result.get("error", "unknown"),
                })

            total_done = completed + errors
            # Progress every 10 sessions or at the end
            if total_done % 10 == 0 or total_done == len(todo):
                elapsed = time.time() - t0
                rate = total_done / elapsed if elapsed > 0 else 0
                remaining = (len(todo) - total_done) / rate if rate > 0 else 0
                _safe_print(
                    f"    [{total_done}/{len(todo)}] "
                    f"{completed} ok, {errors} err, "
                    f"${pass_cost:.3f}, "
                    f"~{remaining/60:.0f}m remaining"
                )

    dt = time.time() - t0
    pass_status["processed"] += completed
    pass_status["total_cost"] += pass_cost
    pass_status["errors_count"] = len(pass_status["errors"])
    pass_status["duration_seconds"] = round(dt)

    print(f"    Pass {pass_num} done: {completed} ok, {errors} errors, "
          f"${pass_cost:.3f}, {dt/60:.1f}m")


# ── Batch merge ───────────────────────────────────────────────────────

def run_batch_merge(sessions, status):
    """Run merge on all sessions that have at least one pass output.

    Merges pass results into enriched_session_v2.json for each session.
    """
    todo = [s for s in sessions if not merge_output_exists(s)]
    # Only merge sessions that have at least one pass output
    todo = [
        s for s in todo
        if any(pass_output_exists(s, p) for p in [1, 2, 3, 4])
    ]

    print(f"\n  Merge: {len(todo)} sessions to merge")

    merged = 0
    merge_errors = 0

    for i, session_dir in enumerate(todo):
        try:
            captured = io.StringIO()
            with redirect_stdout(captured):
                merge_session(session_dir)
            merged += 1
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            merge_errors += 1
            _safe_print(f"    Merge error {session_dir.name}: {e}")

        if (i + 1) % 20 == 0 or (i + 1) == len(todo):
            print(f"    [{i+1}/{len(todo)}] Merged: {merged}, Errors: {merge_errors}")

    status["merge"] = {
        "total": len(todo),
        "merged": merged,
        "errors": merge_errors,
    }
    print(f"    Merge done: {merged} ok, {merge_errors} errors")


# ── Status display ────────────────────────────────────────────────────

def show_status():
    """Display current batch processing status."""
    if not STATUS_FILE.exists():
        print("No batch status file found. Run the orchestrator first.")
        return

    with open(STATUS_FILE) as f:
        status = json.load(f)

    print("=" * 60)
    print("Phase 0.5 LLM Batch Status")
    print("=" * 60)
    print(f"  Started: {status.get('started_at', '?')}")
    print(f"  Sessions: {status.get('total_sessions', '?')}")

    total_cost = 0.0
    for p in [1, 2, 3, 4]:
        key = f"pass_{p}"
        if key in status:
            ps = status[key]
            cost = ps.get("total_cost", 0.0)
            total_cost += cost
            done = ps.get("already_done", 0) + ps.get("processed", 0)
            total = ps.get("total_sessions", "?")
            errs = ps.get("errors_count", 0)
            print(f"  Pass {p} ({ps.get('name', '?')}): "
                  f"{done}/{total} done, ${cost:.3f}, {errs} errors")

    merge = status.get("merge", {})
    if merge:
        print(f"  Merge: {merge.get('merged', 0)}/{merge.get('total', 0)} done, "
              f"{merge.get('errors', 0)} errors")

    print(f"\n  Total cost: ${total_cost:.2f}")

    if status.get("completed_at"):
        print(f"  Completed: {status['completed_at']}")
        dur = status.get("total_duration_seconds", 0)
        print(f"  Duration: {dur/60:.1f} minutes")
    print("=" * 60)


# ── Status persistence ────────────────────────────────────────────────

def save_status(status):
    """Write batch status to disk for resume support."""
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2, default=str)


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Phase 0.5 LLM Batch Orchestrator — "
                    "Run behavioral analysis passes across all unique sessions"
    )
    parser.add_argument("--pass", dest="pass_num", type=int, default=None,
                        help="Run only this pass number (1-4)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Estimate costs without making API calls")
    parser.add_argument("--session", type=str, default=None,
                        help="Process a single session (e.g., session_0012ebed)")
    parser.add_argument("--merge-only", action="store_true",
                        help="Only run the merge step (skip LLM passes)")
    parser.add_argument("--status", action="store_true",
                        help="Show current batch processing status")
    args = parser.parse_args()

    # Status display mode
    if args.status:
        show_status()
        return

    # ── Get sessions ──
    if args.session:
        session_dir = find_session_dir(args.session)
        if not session_dir:
            print(f"ERROR: Session not found: {args.session}")
            sys.exit(1)
        sessions = [session_dir]
        print(f"Single session mode: {session_dir.name}")
    else:
        sessions = get_unique_sessions()

    # ── Header ──
    print("=" * 70)
    print("Phase 0.5 LLM Batch Orchestrator")
    print(f"  Sessions: {len(sessions)}")
    print(f"  Started:  {datetime.now(timezone.utc).isoformat()}")
    if args.dry_run:
        print("  MODE: DRY RUN (no API calls)")
    if args.pass_num:
        print(f"  Running: Pass {args.pass_num} only")
    print("=" * 70)

    # ── Initialize status ──
    status = {
        "operation": "Phase 0.5 LLM Batch",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_sessions": len(sessions),
        "dry_run": args.dry_run,
    }
    save_status(status)

    # ── Merge-only mode ──
    if args.merge_only:
        run_batch_merge(sessions, status)
        save_status(status)
        return

    # ── Run passes ──
    passes_to_run = [args.pass_num] if args.pass_num else [1, 2, 3, 4]
    start_time = time.time()

    for pass_num in passes_to_run:
        if pass_num not in PASS_CONFIGS:
            print(f"ERROR: Invalid pass number: {pass_num}")
            sys.exit(1)
        run_batch_pass(sessions, pass_num, status, dry_run=args.dry_run)
        save_status(status)

    # ── Post-pass merge ──
    if not args.pass_num and not args.dry_run:
        run_batch_merge(sessions, status)

    # ── Summary ──
    elapsed = time.time() - start_time
    status["completed_at"] = datetime.now(timezone.utc).isoformat()
    status["total_duration_seconds"] = round(elapsed)

    total_cost = sum(
        status.get(f"pass_{p}", {}).get("total_cost", 0.0) for p in [1, 2, 3, 4]
    )
    status["total_cost"] = total_cost
    save_status(status)

    print()
    print("=" * 70)
    print(f"Batch complete")
    print(f"  Sessions:  {len(sessions)}")
    print(f"  Duration:  {elapsed/60:.1f} minutes")
    print(f"  Total cost: ${total_cost:.2f}")
    for p in passes_to_run:
        ps = status.get(f"pass_{p}", {})
        done = ps.get("already_done", 0) + ps.get("processed", 0)
        print(f"  Pass {p}: {done}/{ps.get('total_sessions', 0)} done, "
              f"${ps.get('total_cost', 0):.3f}, "
              f"{ps.get('errors_count', 0)} errors")
    if "merge" in status:
        m = status["merge"]
        print(f"  Merge: {m.get('merged', 0)} ok, {m.get('errors', 0)} errors")
    print(f"  Status file: {STATUS_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
