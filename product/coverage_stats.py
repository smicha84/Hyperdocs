#!/usr/bin/env python3
"""
Coverage Stats Generator — Produces coverage.json for the wrecktangle.com landing page.

Counts total sessions in chat history, processed sessions in PERMANENT_HYPERDOCS,
breaks down by pipeline phase, and writes a static JSON file that the Next.js
frontend reads at build/runtime.

Usage:
    python3 product/coverage_stats.py                      # Default output
    python3 product/coverage_stats.py --output /path.json  # Custom output path
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from config import CHAT_HISTORY_DIR, SESSIONS_STORE_DIR, OUTPUT_DIR
from tools.log_config import get_logger

logger = get_logger("product.coverage_stats")

# Default output location — wrecktangle-site public data directory
DEFAULT_OUTPUT = Path.home() / "wrecktangle-site" / "public" / "data" / "coverage.json"

# Phase file requirements (same logic as tools/pipeline_status.py:scan_sessions)
PHASE_FILES = {
    0: ["enriched_session.json", "session_metadata.json"],
    1: ["thread_extractions.json", "geological_notes.json",
        "semantic_primitives.json", "explorer_notes.json"],
    2: ["idea_graph.json", "synthesis.json", "grounded_markers.json"],
    3: ["file_dossiers.json", "claude_md_analysis.json"],
}


def count_total_sessions():
    """Count JSONL files in the canonical chat history directory."""
    if not CHAT_HISTORY_DIR.exists():
        logger.warning(f"  WARNING: Chat history dir not found: {CHAT_HISTORY_DIR}")
        return 0
    return len(list(CHAT_HISTORY_DIR.glob("*.jsonl")))


def scan_processed_sessions():
    """Scan processed session directories and classify by phase completeness.

    Returns a dict of session_name -> {phases: {0: status, 1: status, ...}}
    where status is 'complete', 'partial', or 'missing'.
    """
    if not SESSIONS_STORE_DIR.exists():
        logger.warning(f"  WARNING: Sessions store not found: {SESSIONS_STORE_DIR}")
        return {}

    sessions = {}
    for d in sorted(SESSIONS_STORE_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        existing = {f.name for f in d.glob("*.json")}
        phase_status = {}
        for phase, required in PHASE_FILES.items():
            present = sum(1 for f in required if f in existing)
            if present == len(required):
                phase_status[phase] = "complete"
            elif present > 0:
                phase_status[phase] = "partial"
            else:
                phase_status[phase] = "missing"
        sessions[d.name] = {"phases": phase_status}
    return sessions


def detect_realtime_sessions():
    """Check for sessions being processed by the realtime hook.

    The realtime hook writes to OUTPUT_DIR/realtime_buffer.jsonl.
    If the buffer exists and has content, there's active realtime processing.
    """
    buffer_file = OUTPUT_DIR / "realtime_buffer.jsonl"
    if not buffer_file.exists():
        return 0
    # Count unique session IDs in the buffer
    session_ids = set()
    try:
        with open(buffer_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    sid = entry.get("session_id", "")
                    if sid:
                        session_ids.add(sid)
                except json.JSONDecodeError:
                    continue
    except (OSError, UnicodeDecodeError):
        pass
    return len(session_ids)


def generate_coverage(output_path):
    """Generate the coverage.json file."""
    logger.info("Counting total sessions...")
    total = count_total_sessions()
    logger.info(f"  Total JSONL files: {total}")

    logger.info("Scanning processed sessions...")
    sessions = scan_processed_sessions()
    logger.info(f"  Processed directories: {len(sessions)}")

    # Phase breakdown
    phase_counts = {}
    for phase_num in range(4):
        counter = Counter()
        for s_data in sessions.values():
            status = s_data["phases"].get(phase_num, "missing")
            counter[status] += 1
        phase_entry = {}
        if counter["complete"] > 0:
            phase_entry["complete"] = counter["complete"]
        if counter["partial"] > 0:
            phase_entry["partial"] = counter["partial"]
        if counter["missing"] > 0:
            phase_entry["missing"] = counter["missing"]
        phase_counts[f"phase_{phase_num}"] = phase_entry

    # Fully complete = all 4 phases are "complete"
    fully_complete = sum(
        1 for s in sessions.values()
        if all(v == "complete" for v in s["phases"].values())
    )

    # In progress = processed but not fully complete
    in_progress = len(sessions) - fully_complete

    # Realtime detection
    realtime_count = detect_realtime_sessions()

    # Unprocessed
    unprocessed = total - len(sessions)

    coverage = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_sessions": total,
        "processed": len(sessions),
        "fully_complete": fully_complete,
        "phases": phase_counts,
        "processing_type": {
            "historical_batch": fully_complete,
            "realtime": realtime_count,
            "in_progress": in_progress,
        },
        "unprocessed": max(0, unprocessed),
    }

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(coverage, f, indent=2)

    logger.info(f"\nCoverage JSON written to: {output_path}")
    logger.info(f"  Total: {total}")
    logger.info(f"  Processed: {len(sessions)} ({len(sessions)/total*100:.1f}%)" if total > 0 else "  Processed: 0")
    logger.info(f"  Fully complete: {fully_complete}")
    logger.info(f"  In progress: {in_progress}")
    logger.info(f"  Realtime: {realtime_count}")
    logger.info(f"  Unprocessed: {coverage['unprocessed']}")

    return coverage


def main():
    parser = argparse.ArgumentParser(description="Generate coverage.json for wrecktangle.com")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Output path (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  Hyperdocs Coverage Stats Generator")
    logger.info("=" * 60)

    output_path = Path(args.output)
    generate_coverage(output_path)


if __name__ == "__main__":
    main()
