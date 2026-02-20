#!/usr/bin/env python3
"""
Batch LLM Orchestrator — Runs Phase 0 LLM passes across all sessions.

Executes the 4 LLM passes (content-ref, behaviors, intent, importance)
across all sessions with enriched_session.json. Manages concurrency,
checkpointing, cost tracking, and pass ordering.

Pass order: 1→2→3→4 (Pass 3 depends on Pass 1 results)
Concurrency: Passes 1,4 (Haiku) up to 50-60 concurrent. Passes 2,3 (Opus) up to 30.

Usage:
    # Dry run — estimate costs across all sessions
    python3 batch_llm_orchestrator.py --dry-run

    # Validate on 5 test sessions first
    python3 batch_llm_orchestrator.py --validate

    # Run specific pass across all sessions
    python3 batch_llm_orchestrator.py --pass 1

    # Run all passes across all sessions
    python3 batch_llm_orchestrator.py --all

    # Resume from checkpoint (skips already-complete sessions)
    python3 batch_llm_orchestrator.py --all --resume

    # Show status
    python3 batch_llm_orchestrator.py --status
"""

import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

# ── Configuration ─────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent
try:
    from config import SESSIONS_STORE_DIR, INDEXES_DIR
    OUTPUT_DIR = SESSIONS_STORE_DIR
    CHECKPOINT_DIR = INDEXES_DIR
except ImportError:
    OUTPUT_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
    CHECKPOINT_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "indexes"
CHECKPOINT_FILE = CHECKPOINT_DIR / "llm_pass_checkpoint.json"
COST_LOG_FILE = CHECKPOINT_DIR / "llm_pass_cost_log.json"

# Pass runner script
PASS_RUNNER = REPO / "phase_0_prep" / "llm_pass_runner.py"
MERGE_SCRIPT = REPO / "phase_0_prep" / "merge_llm_results.py"

# Concurrency limits (from Feb 8 testing: 50-60 Haiku stable, 30 Opus stable)
HAIKU_CONCURRENCY = 50
OPUS_CONCURRENCY = 30

# Cooldown between batches (seconds)
BATCH_COOLDOWN = 5

# Validation sessions (including the primary test session 0012ebed)
VALIDATION_SESSIONS = [
    "session_0012ebed",
    "session_d8367f49",
    "session_2146922a",
    "session_513d4807",
    "session_c7e7d342",
]

# Pass output filenames (must match prompts.py PASS_CONFIGS)
PASS_OUTPUT_FILES = {
    1: "llm_pass1_content_ref.json",
    2: "llm_pass2_behaviors.json",
    3: "llm_pass3_intent.json",
    4: "llm_pass4_importance.json",
}


# ── Session discovery ─────────────────────────────────────────────────

def get_all_sessions() -> List[Path]:
    """Get all session directories with enriched_session.json."""
    sessions = []
    if not OUTPUT_DIR.exists():
        return sessions
    for d in sorted(OUTPUT_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        if not (d / "enriched_session.json").exists():
            continue
        # Skip tiny sessions
        summary_f = d / "session_summary.json"
        if summary_f.exists():
            try:
                summary = json.load(open(summary_f))
                stats = summary.get("session_stats", summary)
                if stats.get("total_messages", 0) < 20:
                    continue
            except (json.JSONDecodeError, KeyError):
                pass
        sessions.append(d)
    return sessions


def get_sessions_needing_pass(sessions: List[Path], pass_num: int) -> List[Path]:
    """Filter to sessions that haven't completed a specific pass."""
    output_file = PASS_OUTPUT_FILES[pass_num]
    return [s for s in sessions if not (s / output_file).exists()]


# ── Checkpoint management ─────────────────────────────────────────────

def load_checkpoint() -> Dict:
    """Load the checkpoint file."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"passes": {}, "completed_sessions": {}, "total_cost": 0.0}


def save_checkpoint(checkpoint: Dict):
    """Save the checkpoint file."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoint, f, indent=2)


def update_cost_log(pass_num: int, session_name: str, cost: float, model: str):
    """Append to the cost log."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    log = []
    if COST_LOG_FILE.exists():
        with open(COST_LOG_FILE) as f:
            log = json.load(f)
    log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pass": pass_num,
        "session": session_name,
        "cost": cost,
        "model": model,
    })
    with open(COST_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


# ── Single session processing ─────────────────────────────────────────

def run_pass_on_session(session_dir: Path, pass_num: int,
                        dry_run: bool = False, timeout: int = 300) -> Dict:
    """Run a single LLM pass on a single session via subprocess.

    Returns dict with status, cost, and timing info.
    """
    session_name = session_dir.name
    start = time.time()

    cmd = [
        sys.executable, str(PASS_RUNNER),
        "--pass", str(pass_num),
        "--session", session_name,
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.time() - start

        # Parse cost from output (look for $ amount)
        cost = 0.0
        for line in result.stdout.split('\n'):
            if '$' in line and ('Total' in line or 'cost' in line.lower()):
                import re
                match = re.search(r'\$([0-9]+\.?[0-9]*)', line)
                if match:
                    cost = float(match.group(1))

        success = result.returncode == 0
        return {
            "session": session_name,
            "pass": pass_num,
            "success": success,
            "cost": cost,
            "elapsed": round(elapsed, 1),
            "error": result.stderr[:200] if not success else None,
            "dry_run": dry_run,
        }

    except subprocess.TimeoutExpired:
        return {
            "session": session_name,
            "pass": pass_num,
            "success": False,
            "cost": 0.0,
            "elapsed": timeout,
            "error": f"timeout after {timeout}s",
            "dry_run": dry_run,
        }
    except Exception as e:
        return {
            "session": session_name,
            "pass": pass_num,
            "success": False,
            "cost": 0.0,
            "elapsed": time.time() - start,
            "error": str(e)[:200],
            "dry_run": dry_run,
        }


def merge_session(session_dir: Path, timeout: int = 120) -> Dict:
    """Run the merge script on a session."""
    session_name = session_dir.name
    cmd = [
        sys.executable, str(MERGE_SCRIPT),
        "--session", session_name,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"session": session_name, "success": result.returncode == 0,
                "error": result.stderr[:200] if result.returncode != 0 else None}
    except Exception as e:
        return {"session": session_name, "success": False, "error": str(e)[:200]}


# ── Batch processing ──────────────────────────────────────────────────

def run_pass_batch(sessions: List[Path], pass_num: int,
                   dry_run: bool = False, resume: bool = False) -> Dict:
    """Run a single pass across multiple sessions with concurrency control.

    Returns aggregate statistics.
    """
    # Determine concurrency
    is_opus = pass_num in [2, 3]
    max_workers = OPUS_CONCURRENCY if is_opus else HAIKU_CONCURRENCY
    model_name = "Opus" if is_opus else "Haiku"

    # Filter to sessions needing this pass (if resuming)
    if resume:
        sessions = get_sessions_needing_pass(sessions, pass_num)

    if not sessions:
        print(f"  Pass {pass_num}: No sessions need processing")
        return {"pass": pass_num, "processed": 0, "success": 0, "failed": 0, "cost": 0.0}

    print(f"\n{'=' * 60}")
    print(f"Pass {pass_num} — {model_name} — {len(sessions)} sessions")
    print(f"Concurrency: {max_workers} | {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'=' * 60}")

    checkpoint = load_checkpoint()
    results = []
    total_cost = 0.0
    success_count = 0
    fail_count = 0

    # Process in batches to manage memory and provide progress
    batch_size = max_workers
    for batch_start in range(0, len(sessions), batch_size):
        batch = sessions[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_pass_on_session, s, pass_num, dry_run): s
                for s in batch
            }

            for future in as_completed(futures):
                result = future.result()
                results.append(result)

                if result["success"]:
                    success_count += 1
                    total_cost += result["cost"]

                    # Update checkpoint
                    key = f"pass{pass_num}"
                    if key not in checkpoint.get("completed_sessions", {}):
                        checkpoint.setdefault("completed_sessions", {})[key] = []
                    checkpoint["completed_sessions"][key].append(result["session"])
                    checkpoint["total_cost"] = checkpoint.get("total_cost", 0) + result["cost"]

                    if not dry_run:
                        update_cost_log(pass_num, result["session"], result["cost"], model_name)
                else:
                    fail_count += 1

        # Progress report
        processed = batch_start + len(batch)
        print(f"  [{processed}/{len(sessions)}] success={success_count} "
              f"failed={fail_count} cost=${total_cost:.4f}")

        # Save checkpoint between batches
        save_checkpoint(checkpoint)

        # Cooldown between batches
        if batch_start + batch_size < len(sessions):
            time.sleep(BATCH_COOLDOWN)

    return {
        "pass": pass_num,
        "processed": len(results),
        "success": success_count,
        "failed": fail_count,
        "cost": total_cost,
        "model": model_name,
    }


# ── High-level commands ───────────────────────────────────────────────

def show_status():
    """Show overall progress of LLM passes."""
    sessions = get_all_sessions()
    print(f"\n{'=' * 60}")
    print(f"Phase 0 LLM Pass Status")
    print(f"{'=' * 60}")
    print(f"Total sessions with enriched_session.json: {len(sessions)}")
    print()

    for pass_num in [1, 2, 3, 4]:
        output_file = PASS_OUTPUT_FILES[pass_num]
        complete = sum(1 for s in sessions if (s / output_file).exists())
        remaining = len(sessions) - complete
        config_name = {1: "Content-Ref (Haiku)", 2: "Behaviors (Opus)",
                       3: "Intent (Opus)", 4: "Importance (Haiku)"}
        print(f"  Pass {pass_num} [{config_name[pass_num]}]: "
              f"{complete}/{len(sessions)} ({remaining} remaining)")

    # Check for merged files
    merged = sum(1 for s in sessions if (s / "enriched_session_v2.json").exists())
    print(f"\n  Merged (v2): {merged}/{len(sessions)}")

    # Cost log
    if COST_LOG_FILE.exists():
        with open(COST_LOG_FILE) as f:
            log = json.load(f)
        total = sum(e["cost"] for e in log)
        print(f"\n  Total cost logged: ${total:.4f}")
        by_pass = {}
        for e in log:
            p = e["pass"]
            by_pass[p] = by_pass.get(p, 0) + e["cost"]
        for p in sorted(by_pass):
            print(f"    Pass {p}: ${by_pass[p]:.4f}")
    print()


def run_validation(dry_run: bool = False):
    """Run all passes on 5 validation sessions."""
    sessions = get_all_sessions()
    val_sessions = [s for s in sessions if s.name in VALIDATION_SESSIONS]

    if not val_sessions:
        # Try to find sessions that match partial names
        for vs_name in VALIDATION_SESSIONS:
            for s in sessions:
                if vs_name in s.name or s.name in vs_name:
                    if s not in val_sessions:
                        val_sessions.append(s)

    if not val_sessions:
        print(f"ERROR: No validation sessions found. Checked: {VALIDATION_SESSIONS}")
        print(f"Available sessions: {[s.name for s in sessions[:10]]}...")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"VALIDATION RUN — {len(val_sessions)} sessions")
    print(f"{'=' * 60}")
    for s in val_sessions:
        print(f"  {s.name}")
    print()

    total_cost = 0.0
    for pass_num in [1, 2, 3, 4]:
        result = run_pass_batch(val_sessions, pass_num, dry_run=dry_run)
        total_cost += result["cost"]

    # Merge after all passes
    if not dry_run:
        print(f"\nMerging results...")
        for s in val_sessions:
            merge_result = merge_session(s)
            status = "OK" if merge_result["success"] else f"FAIL: {merge_result['error']}"
            print(f"  {s.name}: {status}")

    print(f"\n{'=' * 60}")
    print(f"VALIDATION {'DRY RUN ' if dry_run else ''}COMPLETE — Cost: ${total_cost:.4f}")
    print(f"{'=' * 60}")


def run_all_passes(dry_run: bool = False, resume: bool = False):
    """Run all 4 passes across all sessions, then merge."""
    sessions = get_all_sessions()

    print(f"\n{'=' * 60}")
    print(f"FULL BATCH RUN — {len(sessions)} sessions, 4 passes")
    print(f"{'=' * 60}")

    total_cost = 0.0
    start_time = time.time()

    # Pass order: 1→2→3→4
    for pass_num in [1, 2, 3, 4]:
        result = run_pass_batch(sessions, pass_num, dry_run=dry_run, resume=resume)
        total_cost += result["cost"]
        print(f"\n  Pass {pass_num} complete: {result['success']}/{result['processed']} "
              f"success, ${result['cost']:.4f}")

    # Merge all sessions
    if not dry_run:
        print(f"\nMerging all sessions...")
        merge_success = 0
        merge_fail = 0
        for i, s in enumerate(sessions):
            result = merge_session(s)
            if result["success"]:
                merge_success += 1
            else:
                merge_fail += 1
            if (i + 1) % 50 == 0:
                print(f"  Merged {i+1}/{len(sessions)}...")
        print(f"  Merge complete: {merge_success} success, {merge_fail} failed")

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"BATCH {'DRY RUN ' if dry_run else ''}COMPLETE")
    print(f"  Sessions: {len(sessions)}")
    print(f"  Total cost: ${total_cost:.4f}")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"{'=' * 60}")


def run_single_pass(pass_num: int, dry_run: bool = False, resume: bool = False):
    """Run a single pass across all sessions."""
    sessions = get_all_sessions()
    result = run_pass_batch(sessions, pass_num, dry_run=dry_run, resume=resume)
    print(f"\nPass {pass_num}: {result['success']}/{result['processed']} success, "
          f"${result['cost']:.4f}")


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Batch LLM Orchestrator — Run Phase 0 LLM passes across sessions"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="Show progress")
    group.add_argument("--validate", action="store_true",
                      help="Run on 5 validation sessions")
    group.add_argument("--pass", dest="pass_num", type=int,
                      help="Run specific pass (1-4)")
    group.add_argument("--all", action="store_true", help="Run all passes")
    group.add_argument("--dry-run", action="store_true",
                      help="Estimate costs without calling API")
    group.add_argument("--merge-all", action="store_true",
                      help="Merge all sessions (after passes complete)")

    parser.add_argument("--resume", action="store_true",
                       help="Skip already-complete sessions")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.validate:
        run_validation(dry_run=False)
    elif args.dry_run:
        run_validation(dry_run=True)
    elif args.pass_num:
        if args.pass_num not in [1, 2, 3, 4]:
            print(f"ERROR: Invalid pass number {args.pass_num}. Must be 1-4.")
            sys.exit(1)
        run_single_pass(args.pass_num, resume=args.resume)
    elif args.all:
        run_all_passes(resume=args.resume)
    elif args.merge_all:
        sessions = get_all_sessions()
        print(f"Merging {len(sessions)} sessions...")
        for i, s in enumerate(sessions):
            result = merge_session(s)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(sessions)}...")
        print("Merge complete.")


if __name__ == "__main__":
    main()
