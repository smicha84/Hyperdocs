#!/usr/bin/env python3
"""
Verify data consistency between output/ and ~/PERMANENT_HYPERDOCS/sessions/.

Both locations should contain the same session directories with the same file counts.
Differences indicate sync issues (the hourly cron may have missed sessions).

Usage:
    python3 verify_data_locations.py
"""
import json
import sys
from pathlib import Path

# Use config if available, fall back to defaults
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import OUTPUT_DIR, SESSIONS_STORE_DIR
except ImportError:
    OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
    SESSIONS_STORE_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"


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
    print("=" * 60)
    print("Data Location Consistency Check")
    print(f"  Local:     {OUTPUT_DIR}")
    print(f"  Permanent: {SESSIONS_STORE_DIR}")
    print("=" * 60)

    local = get_session_dirs(OUTPUT_DIR)
    permanent = get_session_dirs(SESSIONS_STORE_DIR)

    print(f"\n  Local sessions:     {len(local)}")
    print(f"  Permanent sessions: {len(permanent)}")

    # Sessions in local but not permanent
    only_local = set(local.keys()) - set(permanent.keys())
    if only_local:
        print(f"\n  MISSING from permanent ({len(only_local)}):")
        for s in sorted(only_local):
            print(f"    {s} ({local[s]} files)")

    # Sessions in permanent but not local
    only_permanent = set(permanent.keys()) - set(local.keys())
    if only_permanent:
        print(f"\n  MISSING from local ({len(only_permanent)}):")
        for s in sorted(only_permanent):
            print(f"    {s} ({permanent[s]} files)")

    # Sessions in both but with different file counts
    both = set(local.keys()) & set(permanent.keys())
    mismatches = []
    for s in sorted(both):
        if local[s] != permanent[s]:
            mismatches.append((s, local[s], permanent[s]))

    if mismatches:
        print(f"\n  FILE COUNT MISMATCHES ({len(mismatches)}):")
        for s, lc, pc in mismatches:
            print(f"    {s}: local={lc}, permanent={pc}")

    # Summary
    print("\n" + "=" * 60)
    total_issues = len(only_local) + len(only_permanent) + len(mismatches)
    if total_issues == 0:
        print(f"  CONSISTENT: {len(both)} sessions match across both locations")
    else:
        print(f"  {total_issues} issues found:")
        if only_local:
            print(f"    {len(only_local)} sessions only in local")
        if only_permanent:
            print(f"    {len(only_permanent)} sessions only in permanent")
        if mismatches:
            print(f"    {len(mismatches)} file count mismatches")
    print("=" * 60)

    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
