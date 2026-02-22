#!/usr/bin/env python3
"""
Data Completeness Scanner — Scans every session directory and reports
field-level completeness for the entire Hyperdocs pipeline output.

Classifies each field as:
  POPULATED  — field exists with real data
  ZERO       — field is 0/false/[] but file exists (genuine or absent)
  MISSING    — field doesn't exist in the JSON
  FILE_MISSING — the entire file doesn't exist for this session

Output: ~/PERMANENT_HYPERDOCS/indexes/completeness_report.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# ── Expected files by phase ─────────────────────────────────────

PHASE_0_FILES = [
    "enriched_session.json",
    "session_metadata.json",
    "safe_condensed.json",
    "safe_tier4.json",
    "tier2plus_messages.json",
    "tier4_priority_messages.json",
    "user_messages_tier2plus.json",
    "conversation_condensed.json",
    "emergency_contexts.json",
]

PHASE_1_FILES = [
    "thread_extractions.json",
    "geological_notes.json",
    "semantic_primitives.json",
    "explorer_notes.json",
]

PHASE_2_FILES = [
    "idea_graph.json",
    "synthesis.json",
    "grounded_markers.json",
]

PHASE_3_FILES = [
    "file_dossiers.json",
    "claude_md_analysis.json",
]

LEGACY_FILES = [
    "ground_truth_verification.json",
    "file_genealogy.json",
]

ALL_EXPECTED = PHASE_0_FILES + PHASE_1_FILES + PHASE_2_FILES + PHASE_3_FILES

PHASE_MAP = {}
for f in PHASE_0_FILES:
    PHASE_MAP[f] = "phase_0"
for f in PHASE_1_FILES:
    PHASE_MAP[f] = "phase_1"
for f in PHASE_2_FILES:
    PHASE_MAP[f] = "phase_2"
for f in PHASE_3_FILES:
    PHASE_MAP[f] = "phase_3"
for f in LEGACY_FILES:
    PHASE_MAP[f] = "legacy"

STUB_THRESHOLD = 100  # bytes — files smaller than this are stubs

# Files that are legitimately tiny when empty (e.g., {"count": 0, "windows": []} = 33 bytes)
SMALL_WHEN_EMPTY = {
    "emergency_contexts.json": 10,    # Valid at 33 bytes with zero contexts
    "safe_tier4.json": 10,            # Valid as [] (2 bytes) when no tier 4 msgs
    "tier4_priority_messages.json": 10,
    "user_messages_tier2plus.json": 10,
}


# ── Field-level checks ──────────────────────────────────────────

def classify_value(value):
    """Classify a value as POPULATED, ZERO, or MISSING."""
    if value is None:
        return "MISSING"
    if isinstance(value, bool):
        return "POPULATED" if value else "ZERO"
    if isinstance(value, (int, float)):
        return "POPULATED" if value != 0 else "ZERO"
    if isinstance(value, str):
        return "POPULATED" if value.strip() else "ZERO"
    if isinstance(value, (list, tuple)):
        return "POPULATED" if len(value) > 0 else "ZERO"
    if isinstance(value, dict):
        return "POPULATED" if len(value) > 0 else "ZERO"
    return "POPULATED"


def check_enriched_session(data):
    """Check key fields in enriched_session.json."""
    results = {}
    msgs = data.get("messages", [])
    results["messages"] = classify_value(msgs)

    # Check session_stats
    stats = data.get("session_stats", None)
    results["session_stats"] = classify_value(stats)
    if isinstance(stats, dict):
        results["session_stats.total_messages"] = classify_value(stats.get("total_messages"))
        results["session_stats.tier_distribution"] = classify_value(stats.get("tier_distribution"))
        results["session_stats.frustration_peaks"] = classify_value(stats.get("frustration_peaks"))

    # Check message-level enrichment (sample first 5 messages)
    if msgs:
        has_metadata = any(isinstance(m.get("metadata"), dict) and m["metadata"] for m in msgs[:5])
        has_filter_tier = any("filter_tier" in m for m in msgs[:5])
        has_filter_signals = any("filter_signals" in m for m in msgs[:5])
        has_behavior_flags = any(m.get("behavior_flags") is not None for m in msgs[:5])
        results["messages.metadata"] = "POPULATED" if has_metadata else "ZERO"
        results["messages.filter_tier"] = "POPULATED" if has_filter_tier else "MISSING"
        results["messages.filter_signals"] = "POPULATED" if has_filter_signals else "MISSING"
        results["messages.behavior_flags"] = "POPULATED" if has_behavior_flags else "MISSING"

        # Check metadata subfields
        if has_metadata:
            m = next(m for m in msgs[:5] if isinstance(m.get("metadata"), dict) and m["metadata"])
            meta = m["metadata"]
            results["messages.metadata.files"] = classify_value(meta.get("files"))
            results["messages.metadata.caps_ratio"] = classify_value(meta.get("caps_ratio"))
            results["messages.metadata.code_block"] = classify_value(meta.get("code_block"))
    return results


def check_thread_extractions(data):
    """Check thread_extractions.json has content beyond headers."""
    results = {}
    threads = data.get("threads", {})
    results["threads"] = classify_value(threads)
    if isinstance(threads, dict):
        for thread_name in ["ideas", "reactions", "software", "code", "plans", "behavior"]:
            thread = threads.get(thread_name, None)
            if thread is None:
                results[f"threads.{thread_name}"] = "MISSING"
            elif isinstance(thread, dict):
                entries = thread.get("entries", [])
                results[f"threads.{thread_name}"] = classify_value(entries)
            elif isinstance(thread, list):
                results[f"threads.{thread_name}"] = classify_value(thread)
            else:
                results[f"threads.{thread_name}"] = "POPULATED"
    return results


def check_semantic_primitives(data):
    """Check semantic_primitives.json."""
    results = {}
    tagged = data.get("tagged_messages", [])
    results["tagged_messages"] = classify_value(tagged)
    stats = data.get("summary_statistics", None)
    results["summary_statistics"] = classify_value(stats)
    return results


def check_idea_graph(data):
    """Check idea_graph.json nodes and edges."""
    results = {}
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    results["nodes"] = classify_value(nodes)
    results["edges"] = classify_value(edges)
    if isinstance(nodes, list) and nodes:
        results["nodes.count"] = len(nodes)
    if isinstance(edges, list) and edges:
        results["edges.count"] = len(edges)
    meta = data.get("metadata", {})
    results["metadata"] = classify_value(meta)
    return results


def check_grounded_markers(data):
    """Check grounded_markers.json."""
    results = {}
    markers = data.get("markers", [])
    results["markers"] = classify_value(markers)
    results["total_markers"] = classify_value(data.get("total_markers"))
    if isinstance(markers, list) and markers:
        results["markers.count"] = len(markers)
        has_confidence = any(isinstance(m, dict) and "confidence" in m for m in markers[:5])
        results["markers.has_confidence"] = "POPULATED" if has_confidence else "MISSING"
    return results


def check_synthesis(data):
    """Check synthesis.json."""
    results = {}
    results["passes"] = classify_value(data.get("passes"))
    results["key_findings"] = classify_value(data.get("key_findings"))
    results["session_character"] = classify_value(data.get("session_character"))
    return results


def check_file_dossiers(data):
    """Check file_dossiers.json — dict or list format."""
    results = {}
    results["format"] = "dict" if isinstance(data, dict) else "list"
    dossiers = data.get("dossiers", {}) if isinstance(data, dict) else data
    results["dossiers"] = classify_value(dossiers)
    if isinstance(dossiers, dict):
        results["dossiers.count"] = len(dossiers)
    elif isinstance(dossiers, list):
        results["dossiers.count"] = len(dossiers)
    return results


def check_ground_truth(data):
    """Check ground_truth_verification.json."""
    results = {}
    claims = data.get("claims", {})
    verification = data.get("verification", {})
    gap = data.get("gap_report", {})
    results["claims"] = classify_value(claims)
    results["verification"] = classify_value(verification)
    results["gap_report"] = classify_value(gap)
    return results


# Map filenames to their checker functions
FILE_CHECKERS = {
    "enriched_session.json": check_enriched_session,
    "thread_extractions.json": check_thread_extractions,
    "semantic_primitives.json": check_semantic_primitives,
    "idea_graph.json": check_idea_graph,
    "grounded_markers.json": check_grounded_markers,
    "synthesis.json": check_synthesis,
    "file_dossiers.json": check_file_dossiers,
    "ground_truth_verification.json": check_ground_truth,
}


# ── Main scanner ────────────────────────────────────────────────

def scan_session(session_dir):
    """Scan a single session directory and return completeness data."""
    result = {
        "session_id": session_dir.name,
        "files": {},
        "field_details": {},
        "phase_status": {},
    }

    # Check each expected file
    for filename in ALL_EXPECTED + LEGACY_FILES:
        filepath = session_dir / filename
        if not filepath.exists():
            result["files"][filename] = "FILE_MISSING"
            continue

        size = filepath.stat().st_size
        threshold = SMALL_WHEN_EMPTY.get(filename, STUB_THRESHOLD)
        if size < threshold:
            result["files"][filename] = "STUB"
            continue

        result["files"][filename] = "PRESENT"

        # Run field-level checks if checker exists
        if filename in FILE_CHECKERS:
            try:
                with open(filepath) as f:
                    data = json.load(f)
                field_results = FILE_CHECKERS[filename](data)
                result["field_details"][filename] = field_results
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                result["field_details"][filename] = {"_error": str(e)}

    # Determine phase status
    for phase_name, phase_files in [
        ("phase_0", PHASE_0_FILES),
        ("phase_1", PHASE_1_FILES),
        ("phase_2", PHASE_2_FILES),
        ("phase_3", PHASE_3_FILES),
        ("legacy", LEGACY_FILES),
    ]:
        statuses = [result["files"].get(f, "FILE_MISSING") for f in phase_files]
        if all(s == "PRESENT" for s in statuses):
            result["phase_status"][phase_name] = "complete"
        elif all(s == "FILE_MISSING" for s in statuses):
            result["phase_status"][phase_name] = "missing"
        else:
            result["phase_status"][phase_name] = "partial"

    return result


def scan_all(sessions_dir):
    """Scan all session directories and produce aggregate report."""
    sessions_dir = Path(sessions_dir)
    session_dirs = sorted(d for d in sessions_dir.iterdir() if d.is_dir())

    all_results = []
    for sd in session_dirs:
        all_results.append(scan_session(sd))

    # Aggregate: file-level completeness
    completeness_by_file = {}
    for filename in ALL_EXPECTED + LEGACY_FILES:
        present = sum(1 for r in all_results if r["files"].get(filename) == "PRESENT")
        missing = sum(1 for r in all_results if r["files"].get(filename) == "FILE_MISSING")
        stub = sum(1 for r in all_results if r["files"].get(filename) == "STUB")
        completeness_by_file[filename] = {
            "present": present,
            "missing": missing,
            "stub": stub,
        }

    # Aggregate: phase-level completeness
    completeness_by_phase = {}
    for phase in ["phase_0", "phase_1", "phase_2", "phase_3", "legacy"]:
        complete = sum(1 for r in all_results if r["phase_status"].get(phase) == "complete")
        partial = sum(1 for r in all_results if r["phase_status"].get(phase) == "partial")
        missing = sum(1 for r in all_results if r["phase_status"].get(phase) == "missing")
        completeness_by_phase[phase] = {
            "complete": complete,
            "partial": partial,
            "missing": missing,
        }

    # Aggregate: field-level completeness across sessions
    # Only count fields for files that exist in each session (not FILE_MISSING)
    field_completeness = {}
    for filename in FILE_CHECKERS:
        for r in all_results:
            # Skip sessions where this file doesn't exist — don't count missing fields
            if r["files"].get(filename) in ("FILE_MISSING", "STUB"):
                continue
            fields = r.get("field_details", {}).get(filename, {})
            for field_name, status in fields.items():
                if field_name.startswith("_"):
                    continue
                # Skip count fields (they're numeric, not status)
                if field_name.endswith(".count"):
                    continue
                key = f"{filename}::{field_name}"
                if key not in field_completeness:
                    field_completeness[key] = {"POPULATED": 0, "ZERO": 0, "MISSING": 0, "FILE_MISSING": 0}
                if isinstance(status, str) and status in field_completeness[key]:
                    field_completeness[key][status] += 1

    # Add FILE_MISSING counts for fields where the whole file is missing
    for filename in FILE_CHECKERS:
        file_missing_count = sum(
            1 for r in all_results
            if r["files"].get(filename) in ("FILE_MISSING", "STUB")
        )
        if file_missing_count > 0:
            for key in field_completeness:
                if key.startswith(f"{filename}::"):
                    field_completeness[key]["FILE_MISSING"] += file_missing_count

    # Identify incomplete sessions
    incomplete_sessions = []
    for r in all_results:
        phases = r["phase_status"]
        if any(phases.get(p) != "complete" for p in ["phase_0", "phase_1", "phase_2", "phase_3"]):
            incomplete_sessions.append({
                "session_id": r["session_id"],
                "phase_status": phases,
                "missing_files": [f for f, s in r["files"].items() if s != "PRESENT"],
            })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions_scanned": len(all_results),
        "completeness_by_file": completeness_by_file,
        "completeness_by_phase": completeness_by_phase,
        "field_completeness": field_completeness,
        "incomplete_sessions": incomplete_sessions,
        "per_session": all_results,
    }

    return report


def main():
    sessions_dir = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
    if not sessions_dir.exists():
        print(f"Sessions directory not found: {sessions_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {sessions_dir}...")
    report = scan_all(sessions_dir)

    output_path = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "completeness_report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    n = report["sessions_scanned"]
    print(f"\nScanned {n} sessions")
    print(f"\nCompleteness by phase:")
    for phase, counts in report["completeness_by_phase"].items():
        print(f"  {phase}: {counts['complete']} complete, {counts['partial']} partial, {counts['missing']} missing")

    print(f"\nCompleteness by file:")
    for fname, counts in report["completeness_by_file"].items():
        if counts["missing"] > 0 or counts["stub"] > 0:
            print(f"  {fname}: {counts['present']} present, {counts['missing']} missing, {counts['stub']} stub")

    incomplete = report["incomplete_sessions"]
    print(f"\nIncomplete sessions: {len(incomplete)}")
    for s in incomplete[:5]:
        phases = s["phase_status"]
        missing_phases = [p for p, st in phases.items() if st != "complete"]
        print(f"  {s['session_id']}: missing {', '.join(missing_phases)}")
    if len(incomplete) > 5:
        print(f"  ... and {len(incomplete) - 5} more")

    print(f"\nReport written to: {output_path}")


if __name__ == "__main__":
    main()
