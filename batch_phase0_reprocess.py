#!/usr/bin/env python3
"""
Batch Phase 0 Reprocessor — Re-runs deterministic_prep.py + prepare_agent_data.py
on ALL sessions with the 9 data quality fixes applied.

$0 cost. Pure Python. Updates enriched_session.json and all derivative files
(safe_*, tier*, conversation_condensed, emergency_contexts, batches).

Then re-runs schema_normalizer and completeness_scanner for a fresh quality report.

Usage:
    python3 batch_phase0_reprocess.py
"""

import os
import sys
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parent
try:
    from config import CHAT_ARCHIVE_DIR, SESSIONS_STORE_DIR
    CHAT_DIR = CHAT_ARCHIVE_DIR / "sessions"
    OUTPUT_DIR = SESSIONS_STORE_DIR
except ImportError:
    CHAT_DIR = Path.home() / "PERMANENT_CHAT_HISTORY" / "sessions"
    OUTPUT_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"

def _build_duplicate_set():
    """Identify duplicate session directories that process the same conversation.

    The chat history archive often has two JSONL files for the same conversation:
      - ce1dc2b6-ac7a-4d7e-95b7-69a63213b440.jsonl  (UUID only)
      - 59d386aa_ce1dc2b6-ac7a-4d7e-95b7-69a63213b440.jsonl  (prefix_UUID)

    Both contain the same conversation. Phase 0 processes both because they have
    different first-8-char IDs (ce1dc2b6 vs 59d386aa), creating two session
    directories for the same data.

    We keep the session directory whose short ID matches the UUID (the canonical one)
    and skip the one whose short ID is just the prefix.

    Returns a set of short IDs (first 8 chars of session dir name) to skip.
    """
    # Map UUID -> list of JSONL files that contain it
    uuid_files = {}
    for f in CHAT_DIR.iterdir():
        if f.suffix != ".jsonl":
            continue
        stem = f.stem
        if '_' in stem and not stem.startswith('agent-'):
            prefix, uuid_part = stem.split('_', 1)
        else:
            prefix = None
            uuid_part = stem

        if uuid_part not in uuid_files:
            uuid_files[uuid_part] = []
        uuid_files[uuid_part].append({'prefix': prefix, 'short': f.stem[:8], 'file': f.name})

    # For UUIDs with 2+ files, skip the prefixed version
    # (keep the one whose short ID matches the UUID start)
    skip_ids = set()
    for uuid_part, files in uuid_files.items():
        if len(files) < 2:
            continue
        uuid_short = uuid_part[:8]
        for fi in files:
            if fi['prefix'] is not None and fi['short'] != uuid_short:
                # This is the prefixed copy — skip it
                skip_ids.add(fi['short'])

    return skip_ids

DUPLICATE_SKIP_IDS = _build_duplicate_set()


def find_jsonl_for_session(session_dir_name):
    """Find the source JSONL file for a session directory."""
    short_id = session_dir_name.replace("session_", "")
    for f in CHAT_DIR.iterdir():
        if f.suffix == ".jsonl" and f.stem.startswith(short_id):
            return f
    return None


def run_phase0(session_id, jsonl_path, output_dir):
    """Run deterministic_prep.py + prepare_agent_data.py for one session."""
    env = os.environ.copy()
    env["HYPERDOCS_SESSION_ID"] = session_id
    env["HYPERDOCS_CHAT_HISTORY"] = str(jsonl_path)
    env["HYPERDOCS_OUTPUT_DIR"] = str(output_dir.parent)

    # Run deterministic_prep.py
    result = subprocess.run(
        [sys.executable, str(REPO / "phase_0_prep" / "deterministic_prep.py")],
        env=env, capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return False, f"deterministic_prep failed: {result.stderr[:200]}"

    # Run prepare_agent_data.py
    result2 = subprocess.run(
        [sys.executable, str(REPO / "phase_0_prep" / "prepare_agent_data.py")],
        env=env, capture_output=True, text=True, timeout=120
    )
    if result2.returncode != 0:
        return False, f"prepare_agent_data failed: {result2.stderr[:200]}"

    return True, "ok"


def main():
    start_time = time.time()
    print("=" * 70)
    print("Batch Phase 0 Reprocessor — All Sessions")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    # Get all session directories that have enriched_session.json
    session_dirs = sorted(
        d for d in OUTPUT_DIR.iterdir()
        if d.is_dir() and d.name.startswith("session_") and (d / "enriched_session.json").exists()
    )

    print(f"Sessions to reprocess: {len(session_dirs)}")
    print()

    success = 0
    failed = 0
    skipped = 0
    errors = []

    for i, sd in enumerate(session_dirs):
        session_name = sd.name
        short_id = session_name.replace("session_", "")

        # Skip duplicate sessions (same conversation stored under two filenames)
        if short_id in DUPLICATE_SKIP_IDS:
            skipped += 1
            continue

        # Find source JSONL
        jsonl = find_jsonl_for_session(session_name)
        if not jsonl:
            skipped += 1
            continue

        try:
            ok, msg = run_phase0(short_id, jsonl, sd)
            if ok:
                success += 1
            else:
                failed += 1
                errors.append((session_name, msg))
        except subprocess.TimeoutExpired:
            failed += 1
            errors.append((session_name, "timeout"))
        except Exception as e:
            failed += 1
            errors.append((session_name, str(e)))

        # Progress every 25 sessions
        if (i + 1) % 25 == 0 or (i + 1) == len(session_dirs):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(session_dirs) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{len(session_dirs)}] success={success} failed={failed} skipped={skipped} "
                  f"({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")

    # ── Run schema normalizer ──
    print("\nRunning schema normalizer...")
    subprocess.run(
        [sys.executable, str(REPO / "phase_5_ground_truth" / "schema_normalizer.py")],
        capture_output=True, text=True, timeout=600
    )

    # ── Run completeness scanner ──
    print("Running completeness scanner...")
    result = subprocess.run(
        [sys.executable, str(REPO / "phase_5_ground_truth" / "completeness_scanner.py")],
        capture_output=True, text=True, timeout=300
    )
    print(result.stdout[-500:] if result.stdout else "")

    elapsed = time.time() - start_time

    # ── Write log ──
    log = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(elapsed),
        "sessions_processed": success,
        "sessions_failed": failed,
        "sessions_skipped": skipped,
        "errors": [{"session": s, "error": e} for s, e in errors],
    }
    try:
        from config import INDEXES_DIR as _IDX
        log_path = _IDX / "phase0_reprocess_log.json"
    except ImportError:
        log_path = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "phase0_reprocess_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)

    print()
    print("=" * 70)
    print(f"Batch Phase 0 Reprocessor — Complete")
    print(f"  Success: {success}/{len(session_dirs)}")
    print(f"  Failed:  {failed}")
    print(f"  Skipped: {skipped} (no source JSONL found)")
    print(f"  Time:    {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Log:     {log_path}")
    print("=" * 70)

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for s, e in errors[:10]:
            print(f"  {s}: {e}")


if __name__ == "__main__":
    main()
