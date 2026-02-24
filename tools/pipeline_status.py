#!/usr/bin/env python3
"""Pipeline observability — aggregate status across all sessions and runs.

Reads pipeline_run.log files, checkpoint files, and session directories to
produce a comprehensive status report.

Usage:
    python3 tools/pipeline_status.py              # Full status report
    python3 tools/pipeline_status.py --errors      # Only errors
    python3 tools/pipeline_status.py --json        # Machine-readable output
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from config import SESSIONS_STORE_DIR, INDEXES_DIR, OUTPUT_DIR
from tools.log_config import get_logger

logger = get_logger("tools.pipeline_status")


def scan_sessions():
    """Scan all session directories and classify completeness."""
    phases = {
        0: ["enriched_session.json", "session_metadata.json"],
        1: ["thread_extractions.json", "geological_notes.json",
            "semantic_primitives.json", "explorer_notes.json"],
        2: ["idea_graph.json", "synthesis.json", "grounded_markers.json"],
        3: ["file_dossiers.json", "claude_md_analysis.json"],
    }

    sessions = {}
    for d in sorted(SESSIONS_STORE_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        existing = {f.name for f in d.glob("*.json")}
        phase_status = {}
        for phase, required in phases.items():
            present = sum(1 for f in required if f in existing)
            phase_status[phase] = "complete" if present == len(required) else \
                                  "partial" if present > 0 else "missing"
        sessions[d.name] = {
            "file_count": len(existing),
            "phases": phase_status,
            "has_schema_version": any(
                "_schema_version" in json.loads((d / f).read_text())
                for f in existing
                if (d / f).stat().st_size < 1_000_000  # skip huge files
            ) if existing else False,
        }

    return sessions


def scan_logs():
    """Scan pipeline_run.log files across all session output dirs."""
    log_entries = []
    for log_dir in [OUTPUT_DIR, SESSIONS_STORE_DIR]:
        if not log_dir.exists():
            continue
        for d in log_dir.iterdir():
            if not d.is_dir():
                continue
            log_file = d / "pipeline_run.log"
            if log_file.exists():
                for line in log_file.read_text().splitlines():
                    try:
                        entry = json.loads(line)
                        entry["_session_dir"] = d.name
                        log_entries.append(entry)
                    except json.JSONDecodeError:
                        continue
    return log_entries


def scan_checkpoints():
    """Load batch runner checkpoint."""
    cp_file = INDEXES_DIR / "batch_runner_checkpoint.json"
    if cp_file.exists():
        try:
            return json.loads(cp_file.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Pipeline observability dashboard")
    parser.add_argument("--errors", action="store_true", help="Only show errors")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    sessions = scan_sessions()
    logs = scan_logs()
    checkpoint = scan_checkpoints()

    # Aggregate
    phase_counts = {p: Counter() for p in range(4)}
    for s_data in sessions.values():
        for phase, status in s_data["phases"].items():
            phase_counts[phase][status] += 1

    error_logs = [e for e in logs if e.get("level") in ("ERROR", "WARNING")]
    ok_logs = [e for e in logs if "OK:" in e.get("message", "")]
    fail_logs = [e for e in logs if "FAILED:" in e.get("message", "")]

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_sessions": len(sessions),
        "phase_completeness": {
            f"phase_{p}": dict(phase_counts[p]) for p in range(4)
        },
        "fully_complete": sum(
            1 for s in sessions.values()
            if all(v == "complete" for v in s["phases"].values())
        ),
        "log_entries": len(logs),
        "errors": len(error_logs),
        "successes": len(ok_logs),
        "failures": len(fail_logs),
        "batch_checkpoint": checkpoint,
    }

    if args.json:
        logger.info(json.dumps(report, indent=2))
        return

    if args.errors:
        if not error_logs:
            logger.info("No errors found in pipeline logs.")
            return
        for e in error_logs:
            logger.info(f"  [{e.get('timestamp', '?')}] {e.get('_session_dir', '?')}: {e.get('message', '?')}")
        return

    # Full report
    logger.info("=" * 60)
    logger.info("  Hyperdocs Pipeline Status Report")
    logger.info("=" * 60)
    logger.info(f"  Sessions: {report['total_sessions']}")
    logger.info(f"  Fully complete: {report['fully_complete']}")
    logger.info()
    for phase in range(4):
        counts = report["phase_completeness"][f"phase_{phase}"]
        c = counts.get("complete", 0)
        p = counts.get("partial", 0)
        m = counts.get("missing", 0)
        logger.info(f"  Phase {phase}: {c} complete, {p} partial, {m} missing")
    logger.info()
    if logs:
        logger.error(f"  Log entries: {report['log_entries']} ({report['successes']} OK, {report['failures']} failed, {report['errors']} errors)")
    if checkpoint:
        print(f"  Batch checkpoint: {len(checkpoint.get('completed', []))} done, "
              f"{len(checkpoint.get('failed', []))} failed")
    logger.info()


if __name__ == "__main__":
    main()
