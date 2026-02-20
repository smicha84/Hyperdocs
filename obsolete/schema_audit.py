#!/usr/bin/env python3
"""
Schema Audit — Run gap_checklist across ALL sessions at scale.

Imports analyze_session() directly and runs it on every session directory.
Produces schema_audit.json with:
- Per-session coverage scores
- Aggregate distribution of coverage
- Most common gap types across all sessions
- Schema variant detection (which sessions trigger unknown schemas)

Usage:
    python3 schema_audit.py              # Scan output/ directory
    python3 schema_audit.py --dir /path  # Scan custom directory

$0 cost — pure Python, no LLM calls.
"""
import json
import sys
import time
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gap_checklist import analyze_session


def find_session_dirs(base_dir: Path) -> list[Path]:
    """Find all session directories with at least session_metadata.json."""
    sessions = []
    for d in sorted(base_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        # Must have at least one output file
        if (d / "session_metadata.json").exists() or (d / "enriched_session.json").exists():
            sessions.append(d)
    return sessions


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Schema Audit — Gap Checklist at Scale")
    parser.add_argument("--dir", default="", help="Base directory to scan")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of sessions (0=all)")
    args = parser.parse_args()

    base = Path(args.dir) if args.dir else Path(__file__).resolve().parent / "output"
    # Also check PERMANENT_HYPERDOCS
    perm = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"

    print("=" * 60)
    print("Schema Audit — Gap Checklist at Scale")
    print("=" * 60)
    print(f"Scanning: {base}")
    if perm.exists():
        print(f"Also: {perm}")
    print()

    session_dirs = find_session_dirs(base)
    if perm.exists():
        perm_sessions = find_session_dirs(perm)
        # Deduplicate by session name
        existing_names = {d.name for d in session_dirs}
        for ps in perm_sessions:
            if ps.name not in existing_names:
                session_dirs.append(ps)

    if args.limit:
        session_dirs = session_dirs[:args.limit]

    print(f"Found {len(session_dirs)} sessions")
    print()

    # Run gap_checklist on each session
    results = []
    gap_counter = Counter()
    coverage_buckets = Counter()  # 0-10%, 10-20%, etc.
    adj_coverage_buckets = Counter()  # adjusted coverage distribution
    file_presence = Counter()
    schema_issues = []
    errors = []

    t0 = time.time()
    for i, sd in enumerate(session_dirs):
        session_id = sd.name.replace("session_", "")
        try:
            checklist = analyze_session(sd)

            coverage = checklist["summary"]["coverage_score"]
            adj_coverage = checklist["summary"].get("adjusted_coverage_score", coverage)
            total_gaps = checklist["convergence"]["total_gaps"]
            structural_gaps = checklist["convergence"].get("structural_gaps", 0)
            total_confirmed = checklist["convergence"]["total_confirmed"]
            total_missing = checklist["convergence"].get("total_missing_values", total_gaps)

            # Track coverage distribution (both raw and adjusted)
            bucket = min(int(coverage * 10), 9)  # 0-9 for 0%-100%
            coverage_buckets[bucket] += 1
            adj_bucket = min(int(adj_coverage * 10), 9)
            adj_coverage_buckets[adj_bucket] += 1

            # Track gap types
            for gap in checklist["gaps"]:
                gap_counter[gap["field"]] += 1

            # Track file presence
            for fname, status in checklist["file_status"].items():
                file_presence[f"{fname}:{status}"] += 1

            # Detect potential schema issues (very low coverage despite files present)
            files_present = checklist["summary"]["files_present"]
            if coverage < 0.5 and files_present >= 6:
                schema_issues.append({
                    "session": session_id,
                    "coverage": coverage,
                    "adjusted_coverage": adj_coverage,
                    "files_present": files_present,
                    "gaps": total_gaps,
                    "structural_gaps": structural_gaps,
                    "top_gaps": [g["field"] for g in checklist["gaps"][:3]],
                })

            results.append({
                "session_id": session_id,
                "coverage": coverage,
                "adjusted_coverage": adj_coverage,
                "confirmed": total_confirmed,
                "gaps": total_gaps,
                "structural_gaps": structural_gaps,
                "missing_values": total_missing,
                "files_present": files_present,
                "files_missing": checklist["summary"]["files_missing"],
                "gap_fields": [g["field"] for g in checklist["gaps"]],
            })

        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as e:
            errors.append({"session": session_id, "error": str(e)})

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(session_dirs)}] {elapsed:.1f}s ({(i+1)/elapsed:.0f}/s)")

    elapsed = time.time() - t0
    print(f"\nProcessed {len(results)} sessions in {elapsed:.1f}s")
    if errors:
        print(f"Errors: {len(errors)}")
    print()

    # Aggregate stats
    coverages = [r["coverage"] for r in results]
    adj_coverages = [r["adjusted_coverage"] for r in results]
    avg_coverage = sum(coverages) / len(coverages) if coverages else 0
    avg_adj_coverage = sum(adj_coverages) / len(adj_coverages) if adj_coverages else 0
    median_coverage = sorted(coverages)[len(coverages) // 2] if coverages else 0
    median_adj_coverage = sorted(adj_coverages)[len(adj_coverages) // 2] if adj_coverages else 0
    below_50 = sum(1 for c in coverages if c < 0.5)
    below_70 = sum(1 for c in coverages if c < 0.7)
    above_85 = sum(1 for c in coverages if c >= 0.85)
    above_90 = sum(1 for c in coverages if c >= 0.90)
    adj_above_85 = sum(1 for c in adj_coverages if c >= 0.85)
    adj_above_90 = sum(1 for c in adj_coverages if c >= 0.90)

    print("COVERAGE DISTRIBUTION (raw / adjusted)")
    print(f"  Average: {avg_coverage:.0%} / {avg_adj_coverage:.0%}")
    print(f"  Median:  {median_coverage:.0%} / {median_adj_coverage:.0%}")
    print(f"  <50%:    {below_50} sessions")
    print(f"  <70%:    {below_70} sessions")
    print(f"  >=85%:   {above_85} / {adj_above_85} sessions (raw / adjusted)")
    print(f"  >=90%:   {above_90} / {adj_above_90} sessions (raw / adjusted)")
    print()

    # Coverage histogram (adjusted)
    print("HISTOGRAM (adjusted coverage — excludes structural gaps)")
    for bucket in range(10):
        count = adj_coverage_buckets.get(bucket, 0)
        label = f"{bucket*10:>3}%-{(bucket+1)*10:>3}%"
        bar = "#" * (count // 2)
        print(f"  {label}: {count:>4} {bar}")
    print()

    # Most common gaps
    print("MOST COMMON GAPS (across all sessions)")
    for field, count in gap_counter.most_common(15):
        pct = count / len(results) * 100
        print(f"  {count:>4} ({pct:>5.1f}%) {field}")
    print()

    # Schema issues
    if schema_issues:
        print(f"POTENTIAL SCHEMA ISSUES ({len(schema_issues)} sessions)")
        print("  (Coverage <50% despite 6+ files present — likely unrecognized schema)")
        for si in schema_issues[:10]:
            print(f"  {si['session']}: {si['coverage']:.0%} coverage, {si['files_present']} files, gaps: {', '.join(si['top_gaps'][:3])}")
        if len(schema_issues) > 10:
            print(f"  ... and {len(schema_issues) - 10} more")
    print()

    # File presence stats
    print("FILE PRESENCE (across all sessions)")
    for key, count in sorted(file_presence.items(), key=lambda x: -x[1]):
        fname, status = key.rsplit(":", 1)
        if count > 10:
            print(f"  {count:>4} {status:>8} {fname}")
    print()

    # Build output
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "schema_audit.py",
        "sessions_scanned": len(results),
        "sessions_with_errors": len(errors),
        "aggregate": {
            "average_coverage": round(avg_coverage, 3),
            "median_coverage": round(median_coverage, 3),
            "below_50_pct": below_50,
            "below_70_pct": below_70,
            "above_85_pct": above_85,
            "above_90_pct": above_90,
            "coverage_histogram": {f"{b*10}-{(b+1)*10}": coverage_buckets.get(b, 0) for b in range(10)},
        },
        "gap_frequency": dict(gap_counter.most_common()),
        "schema_issues": schema_issues,
        "file_presence": dict(sorted(file_presence.items(), key=lambda x: -x[1])),
        "errors": errors,
        "per_session": sorted(results, key=lambda x: x["coverage"]),
    }

    out_path = Path(__file__).resolve().parent / "schema_audit.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"Written: {out_path}")
    print(f"Size: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
