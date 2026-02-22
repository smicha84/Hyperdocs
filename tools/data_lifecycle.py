#!/usr/bin/env python3
"""Data lifecycle manager — identify stale, orphan, and oversized data.

Reports what can be cleaned up. Does NOT auto-delete — reports only.

Usage:
    python3 tools/data_lifecycle.py                # Full scan
    python3 tools/data_lifecycle.py --backups      # Show backup dirs
    python3 tools/data_lifecycle.py --orphans      # Show orphan files
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from config import SESSIONS_STORE_DIR, INDEXES_DIR, STORE_DIR


KNOWN_SESSION_FILES = {
    # Phase 0
    "enriched_session.json", "session_metadata.json",
    "safe_condensed.json", "safe_summary.json",
    "safe_tier1.json", "safe_tier2.json", "safe_tier3.json", "safe_tier4.json",
    "conversation_condensed.json", "emergency_contexts.json",
    "tier2plus_messages.json", "tier4_priority_messages.json",
    "user_messages_tier2plus.json", "opus_classifications.json",
    "opus_filtered_summary.json", "opus_filtered_tier1.json",
    "opus_filtered_tier2.json",
    # Phase 1
    "thread_extractions.json", "geological_notes.json",
    "semantic_primitives.json", "explorer_notes.json",
    # Phase 2
    "idea_graph.json", "synthesis.json", "grounded_markers.json",
    "file_genealogy.json",
    # Phase 3
    "file_dossiers.json", "claude_md_analysis.json",
    # Metadata
    "session_summary.json",
}


def scan_backups():
    """Find backup directories created by schema normalizer."""
    backups = []
    for d in SESSIONS_STORE_DIR.iterdir():
        if not d.is_dir():
            continue
        backup_dir = d / "backups"
        if backup_dir.exists():
            size = sum(f.stat().st_size for f in backup_dir.rglob("*") if f.is_file())
            count = len(list(backup_dir.glob("*")))
            backups.append({"session": d.name, "files": count, "bytes": size})
    return backups


def scan_orphan_files():
    """Find files in session dirs that don't match known filenames."""
    orphans = []
    for d in SESSIONS_STORE_DIR.iterdir():
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        for f in d.glob("*.json"):
            if f.name not in KNOWN_SESSION_FILES and not f.name.startswith("_"):
                orphans.append({"session": d.name, "file": f.name,
                                "bytes": f.stat().st_size})
    return orphans


def scan_large_files():
    """Find JSON files larger than 10MB."""
    large = []
    for f in STORE_DIR.rglob("*.json"):
        if f.stat().st_size > 10_000_000:
            large.append({"path": str(f.relative_to(STORE_DIR)),
                          "bytes": f.stat().st_size})
    return large


def scan_empty_sessions():
    """Find session directories with 0 JSON files."""
    empty = []
    for d in SESSIONS_STORE_DIR.iterdir():
        if d.is_dir() and d.name.startswith("session_"):
            if not list(d.glob("*.json")):
                empty.append(d.name)
    return empty


def scan_lock_files():
    """Find stale .lock files."""
    locks = []
    for f in STORE_DIR.rglob("*.lock"):
        locks.append(str(f.relative_to(STORE_DIR)))
    return locks


def main():
    parser = argparse.ArgumentParser(description="Data lifecycle scanner")
    parser.add_argument("--backups", action="store_true", help="Show backup directories")
    parser.add_argument("--orphans", action="store_true", help="Show orphan files")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    report = {}

    if args.backups or not (args.backups or args.orphans):
        backups = scan_backups()
        total_backup_bytes = sum(b["bytes"] for b in backups)
        report["backups"] = {
            "count": len(backups),
            "total_bytes": total_backup_bytes,
            "sessions": backups,
        }
        if not args.json:
            print(f"Backup directories: {len(backups)} ({total_backup_bytes:,} bytes)")
            if backups:
                for b in backups[:10]:
                    print(f"  {b['session']}: {b['files']} files, {b['bytes']:,} bytes")
                if len(backups) > 10:
                    print(f"  ... and {len(backups) - 10} more")
            print()

    if args.orphans or not (args.backups or args.orphans):
        orphans = scan_orphan_files()
        report["orphans"] = {"count": len(orphans), "files": orphans}
        if not args.json:
            print(f"Orphan files (not in known schema): {len(orphans)}")
            for o in orphans[:20]:
                print(f"  {o['session']}/{o['file']} ({o['bytes']:,} bytes)")
            if len(orphans) > 20:
                print(f"  ... and {len(orphans) - 20} more")
            print()

    if not (args.backups or args.orphans):
        large = scan_large_files()
        report["large_files"] = large
        if not args.json:
            print(f"Large files (>10MB): {len(large)}")
            for l in large:
                print(f"  {l['path']} ({l['bytes']:,} bytes)")
            print()

        empty = scan_empty_sessions()
        report["empty_sessions"] = empty
        if not args.json:
            print(f"Empty session directories: {len(empty)}")
            for e in empty:
                print(f"  {e}")
            print()

        locks = scan_lock_files()
        report["lock_files"] = locks
        if not args.json:
            if locks:
                print(f"Stale lock files: {len(locks)}")
                for l in locks:
                    print(f"  {l}")
                print()

    if args.json:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
