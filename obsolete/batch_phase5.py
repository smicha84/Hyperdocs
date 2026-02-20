#!/usr/bin/env python3
"""
Batch Phase 5 Runner — Ground Truth Verification at Scale

Runs claim_extractor → ground_truth_verifier → gap_reporter on all sessions
that have file_dossiers.json. Re-runs sessions with old-format verification
(monolithic ground_truth_verification.json without per-claim status).

All three scripts are pure Python ($0, no LLM calls). Sequential execution.

Usage:
    python3 batch_phase5.py                          # Process all eligible sessions
    python3 batch_phase5.py --sessions-dir /path/to  # Custom sessions directory
    python3 batch_phase5.py --force                   # Re-run even if new-format exists
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

PHASE_5_DIR = Path(__file__).resolve().parent / "phase_5_ground_truth"
CLAIM_EXTRACTOR = PHASE_5_DIR / "claim_extractor.py"
GROUND_TRUTH_VERIFIER = PHASE_5_DIR / "ground_truth_verifier.py"
GAP_REPORTER = PHASE_5_DIR / "gap_reporter.py"

DEFAULT_SESSIONS_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"


def has_new_format_verification(session_dir):
    """Check if session has new-format ground_truth_verification.json."""
    gt = session_dir / "ground_truth_verification.json"
    if not gt.exists():
        return False
    try:
        data = json.loads(gt.read_text())
        # New format: {"claims": [{"verification_status": ...}, ...]}
        claims = data.get("claims", None)
        return isinstance(claims, list) and len(claims) > 0
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


def needs_processing(session_dir, force=False):
    """Determine if a session needs Phase 5 processing."""
    # Must have file_dossiers.json as prerequisite
    if not (session_dir / "file_dossiers.json").exists():
        return False, "no file_dossiers.json"

    if force:
        return True, "forced"

    # Check for new-format verification
    if has_new_format_verification(session_dir):
        return False, "already has new-format verification"

    return True, "needs processing"


def run_script(script_path, session_dir):
    """Run a Phase 5 script on a session directory."""
    result = subprocess.run(
        [sys.executable, str(script_path), "--dir", str(session_dir)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def process_session(session_dir):
    """Run the full Phase 5 pipeline on a single session."""
    session_name = session_dir.name
    errors = []

    # Step 1: Claim extraction
    code, stdout, stderr = run_script(CLAIM_EXTRACTOR, session_dir)
    if code != 0:
        errors.append(f"claim_extractor failed: {stderr[:200]}")
        return False, errors

    # Step 2: Ground truth verification
    code, stdout, stderr = run_script(GROUND_TRUTH_VERIFIER, session_dir)
    if code != 0:
        errors.append(f"ground_truth_verifier failed: {stderr[:200]}")
        return False, errors

    # Step 3: Gap reporter (produces ground_truth_verification.json + summary)
    code, stdout, stderr = run_script(GAP_REPORTER, session_dir)
    if code != 0:
        errors.append(f"gap_reporter failed: {stderr[:200]}")
        return False, errors

    return True, []


def main():
    parser = argparse.ArgumentParser(description="Batch Phase 5 — Ground Truth at Scale")
    parser.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS_DIR),
                        help="Path to sessions directory")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if new-format verification exists")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of sessions to process (0=all)")
    args = parser.parse_args()

    sessions_dir = Path(args.sessions_dir)
    if not sessions_dir.exists():
        print(f"ERROR: Sessions directory not found: {sessions_dir}")
        sys.exit(1)

    print("=" * 60)
    print("Batch Phase 5 — Ground Truth Verification at Scale")
    print("=" * 60)
    print(f"Sessions dir: {sessions_dir}")
    print(f"Force re-run: {args.force}")
    print(f"Started: {datetime.now().isoformat()}")
    print()

    # Discover sessions
    all_sessions = sorted(d for d in sessions_dir.iterdir() if d.is_dir() and d.name.startswith("session_"))
    print(f"Total session directories: {len(all_sessions)}")

    # Filter to those needing processing
    to_process = []
    skip_reasons = {}
    for session_dir in all_sessions:
        needs, reason = needs_processing(session_dir, args.force)
        if needs:
            to_process.append(session_dir)
        else:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    print(f"Need processing: {len(to_process)}")
    for reason, count in sorted(skip_reasons.items()):
        print(f"  Skipped ({reason}): {count}")
    print()

    if args.limit > 0:
        to_process = to_process[:args.limit]
        print(f"Limited to: {len(to_process)} sessions")

    # Process
    succeeded = 0
    failed = 0
    failed_sessions = []

    for i, session_dir in enumerate(to_process):
        session_name = session_dir.name
        print(f"  [{i+1}/{len(to_process)}] {session_name}...", end="", flush=True)

        try:
            ok, errors = process_session(session_dir)
            if ok:
                succeeded += 1
                print(" OK")
            else:
                failed += 1
                failed_sessions.append((session_name, errors))
                print(f" FAILED: {errors[0][:60]}")
        except subprocess.TimeoutExpired:
            failed += 1
            failed_sessions.append((session_name, ["timeout"]))
            print(" TIMEOUT")

    # Summary
    print()
    print("=" * 60)
    print(f"Finished: {datetime.now().isoformat()}")
    print(f"Processed: {succeeded + failed}")
    print(f"  Succeeded: {succeeded}")
    print(f"  Failed: {failed}")

    if failed_sessions:
        print()
        print("Failed sessions:")
        for name, errors in failed_sessions:
            print(f"  {name}: {'; '.join(errors)[:100]}")

    # Write batch log
    log = {
        "generated_at": datetime.now().isoformat(),
        "sessions_dir": str(sessions_dir),
        "total_sessions": len(all_sessions),
        "processed": succeeded + failed,
        "succeeded": succeeded,
        "failed": failed,
        "failed_sessions": [{"session": name, "errors": errs} for name, errs in failed_sessions],
    }
    log_path = Path(__file__).resolve().parent / "batch_phase5_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\nLog: {log_path}")


if __name__ == "__main__":
    main()
