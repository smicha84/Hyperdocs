#!/usr/bin/env python3
"""
Verify data consistency between output/ and ~/PERMANENT_HYPERDOCS/sessions/.

Both locations should contain the same session directories with the same file counts.
Differences indicate sync issues (the hourly cron may have missed sessions).

Usage:
    python3 verify_data_locations.py
"""
from tools.log_config import get_logger

logger = get_logger("tools.verify_data_locations")

import json
import os
import sys
from pathlib import Path

# Use config if available, fall back to defaults
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import OUTPUT_DIR, SESSIONS_STORE_DIR
except ImportError:
    OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
    SESSIONS_STORE_DIR = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS"))) / "sessions"


def get_session_dirs(base: Path) -> dict:
    """Return {session_name: file_count} for all session directories."""
    sessions = {}
    if not base.exists():
        return sessions
    for d in sorted(base.iterdir()):
        if d.is_dir() and d.name.startswith("session_"):
            file_count = sum(1 for f in d.iterdir() if f.is_file() and f.suffix == ".json")
            sessions[d.name] = file_count
    return sessions


def main():
    logger.info("=" * 60)
    logger.info("Data Location Consistency Check")
    logger.info(f"  Local:     {OUTPUT_DIR}")
    logger.info(f"  Permanent: {SESSIONS_STORE_DIR}")
    logger.info("=" * 60)

    local = get_session_dirs(OUTPUT_DIR)
    permanent = get_session_dirs(SESSIONS_STORE_DIR)

    logger.info(f"\n  Local sessions:     {len(local)}")
    logger.info(f"  Permanent sessions: {len(permanent)}")

    # Sessions in local but not permanent
    only_local = set(local.keys()) - set(permanent.keys())
    if only_local:
        logger.info(f"\n  MISSING from permanent ({len(only_local)}):")
        for s in sorted(only_local):
            logger.info(f"    {s} ({local[s]} files)")

    # Sessions in permanent but not local
    only_permanent = set(permanent.keys()) - set(local.keys())
    if only_permanent:
        logger.info(f"\n  MISSING from local ({len(only_permanent)}):")
        for s in sorted(only_permanent):
            logger.info(f"    {s} ({permanent[s]} files)")

    # Sessions in both but with different file counts
    both = set(local.keys()) & set(permanent.keys())
    mismatches = []
    for s in sorted(both):
        if local[s] != permanent[s]:
            mismatches.append((s, local[s], permanent[s]))

    if mismatches:
        logger.info(f"\n  FILE COUNT MISMATCHES ({len(mismatches)}):")
        for s, lc, pc in mismatches:
            logger.info(f"    {s}: local={lc}, permanent={pc}")

    # Summary
    logger.info("\n" + "=" * 60)
    total_issues = len(only_local) + len(only_permanent) + len(mismatches)
    if total_issues == 0:
        logger.info(f"  CONSISTENT: {len(both)} sessions match across both locations")
    else:
        logger.info(f"  {total_issues} issues found:")
        if only_local:
            logger.info(f"    {len(only_local)} sessions only in local")
        if only_permanent:
            logger.info(f"    {len(only_permanent)} sessions only in permanent")
        if mismatches:
            logger.info(f"    {len(mismatches)} file count mismatches")
    logger.info("=" * 60)

    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
