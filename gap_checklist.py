#!/usr/bin/env python3
"""
Gap Checklist Generator — The Core Mechanism for Iterative Analysis

Takes the output of a pipeline pass and produces a structured gap_checklist.json
that tells the NEXT pass exactly what's missing, where to look, and what to
look for. This is the "thermometer" that checks if the steak is done.

Based on:
- FAIR-RAG's Structured Evidence Assessment (gap-driven sub-queries)
- ITERX's MDP termination (stop when no new info)
- RefineBench's hard cap (max 4-5 passes)

Usage:
    python3 gap_checklist.py                    # Check current session
    python3 gap_checklist.py --session 0012ebed # Check specific session
    python3 gap_checklist.py --compare prev.json # Compare to previous pass

Output: gap_checklist.json in the session output directory
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from config import get_session_output_dir, SESSION_ID
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    _out = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output"))
    def get_session_output_dir():
        d = _out / f"session_{SESSION_ID[:8]}"
        d.mkdir(parents=True, exist_ok=True)
        return d

# ── Expected Values ────────────────────────────────────────────────────────
# These define what "complete" looks like for each field.

ACTION_VECTORS = ["created", "modified", "debugged", "refactored", "discovered", "decided", "abandoned", "reverted"]
CONFIDENCE_SIGNALS = ["experimental", "tentative", "working", "stable", "proven", "fragile"]
EMOTIONAL_TENORS = ["frustrated", "uncertain", "curious", "cautious", "confident", "excited", "relieved"]
INTENT_MARKERS = ["correctness", "performance", "maintainability", "feature", "bugfix", "exploration", "cleanup"]
EDGE_TYPES = ["evolved", "pivoted", "split", "merged", "abandoned", "resurrected", "constrained", "expanded", "concretized", "abstracted"]
MARKER_CATEGORIES = ["architecture", "decision", "behavior", "risk", "opportunity"]

# Minimum thresholds for "sufficient" coverage
MIN_IDEA_NODES = 10
MIN_GROUNDED_MARKERS = 5
MIN_FILE_DOSSIERS = 3
MIN_EXPLORER_OBS = 6
MIN_GEOLOGICAL_MICRO = 5
MIN_GEOLOGICAL_MESO = 2


def load_json(path):
    """Load JSON file, return None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def check_enum_coverage(values_found, possible_values, field_name):
    """Check how many of the possible enum values were observed."""
    found = set(v for v in values_found if v)
    possible = set(possible_values)
    covered = found & possible
    missing = possible - found

    coverage = len(covered) / len(possible) if possible else 0
    confidence = min(coverage * 1.1, 1.0)  # Slight boost — 90% coverage ≈ high confidence

    confirmed = {
        "field": field_name,
        "coverage": f"{len(covered)}/{len(possible)} values observed",
        "values_found": sorted(covered),
        "confidence": round(confidence, 2),
        "evidence_count": len(values_found),
    }

    gap = None
    if missing:
        gap = {
            "field": field_name,
            "missing_values": sorted(missing),
            "reason": f"{len(missing)} of {len(possible)} values never observed in this pass",
            "priority": "high" if len(missing) > len(possible) / 2 else "medium" if missing else "low",
            "suggested_focus": f"Look for messages where {field_name} could be {' or '.join(sorted(missing)[:3])}",
        }

    return confirmed, gap


def check_count_threshold(actual, minimum, field_name, unit="entries"):
    """Check if a count meets the minimum threshold."""
    met = actual >= minimum
    confidence = min(actual / minimum, 1.0) if minimum > 0 else 1.0

    confirmed = {
        "field": field_name,
        "coverage": f"{actual} {unit}" + (f" (target: {minimum}+)" if not met else ""),
        "confidence": round(confidence, 2),
        "evidence_count": actual,
    }

    gap = None
    if not met:
        deficit = minimum - actual
        gap = {
            "field": field_name,
            "missing_values": [f"need {deficit} more {unit}"],
            "reason": f"Only {actual} {unit} found, target is {minimum}+",
            "priority": "high" if actual < minimum / 2 else "medium",
            "suggested_focus": f"Re-examine session for additional {field_name.replace('_', ' ')} not captured in this pass",
        }

    return confirmed, gap


def check_populated_ratio(populated_count, total_count, field_name):
    """Check what fraction of messages have a field populated."""
    ratio = populated_count / total_count if total_count > 0 else 0

    confirmed = {
        "field": field_name,
        "coverage": f"{populated_count}/{total_count} messages ({ratio:.0%})",
        "confidence": round(min(ratio * 1.2, 1.0), 2),
        "evidence_count": populated_count,
    }

    gap = None
    if ratio < 0.1:  # Less than 10% populated
        gap = {
            "field": field_name,
            "missing_values": [f"{total_count - populated_count} messages without this field"],
            "reason": f"Only {ratio:.0%} of messages have {field_name} populated",
            "priority": "medium",
            "suggested_focus": f"Many messages may have implicit {field_name.replace('_', ' ')} not captured by this pass",
        }

    return confirmed, gap


def analyze_session(session_dir: Path, previous_checklist: dict = None):
    """Analyze a session output directory and produce a gap checklist."""

    confirmed = []
    gaps = []
    file_status = {}

    # ── Phase 0: Session Summary ──────────────────────────────────────
    summary = load_json(session_dir / "session_summary.json")
    if summary:
        stats = summary.get("session_stats", summary)
        file_status["session_summary.json"] = "present"
        total_msgs = stats.get("total_messages", 0)
        frustration = len(stats.get("frustration_peaks", []))
        files_mentioned = len(stats.get("file_mention_counts", {}))
        errors = stats.get("error_count", 0)

        c, g = check_count_threshold(total_msgs, 50, "total_messages", "messages")
        confirmed.append(c)
        if g: gaps.append(g)

        c, g = check_count_threshold(files_mentioned, 3, "files_mentioned", "unique files")
        confirmed.append(c)
        if g: gaps.append(g)
    else:
        file_status["session_summary.json"] = "MISSING"
        gaps.append({
            "field": "session_summary",
            "missing_values": ["entire file"],
            "reason": "Phase 0 output missing — session not preprocessed",
            "priority": "critical",
            "suggested_focus": "Run Phase 0 (deterministic_prep.py) first",
        })

    # ── Phase 1: Semantic Primitives ──────────────────────────────────
    primitives = load_json(session_dir / "semantic_primitives.json")
    if primitives:
        file_status["semantic_primitives.json"] = "present"
        msgs = primitives.get("tagged_messages", [])

        # Check coverage of each primitive enum
        for field, possible in [
            ("action_vector", ACTION_VECTORS),
            ("confidence_signal", CONFIDENCE_SIGNALS),
            ("emotional_tenor", EMOTIONAL_TENORS),
            ("intent_marker", INTENT_MARKERS),
        ]:
            values = [m.get(field, "") for m in msgs]
            c, g = check_enum_coverage(values, possible, field)
            confirmed.append(c)
            if g: gaps.append(g)

        # Check populated ratios for free-text fields
        friction_count = sum(1 for m in msgs if m.get("friction_log"))
        decision_count = sum(1 for m in msgs if m.get("decision_trace"))

        c, g = check_populated_ratio(friction_count, len(msgs), "friction_log")
        confirmed.append(c)
        if g: gaps.append(g)

        c, g = check_populated_ratio(decision_count, len(msgs), "decision_trace")
        confirmed.append(c)
        if g: gaps.append(g)
    else:
        file_status["semantic_primitives.json"] = "MISSING"
        gaps.append({
            "field": "semantic_primitives",
            "missing_values": ["entire file"],
            "reason": "Phase 1 Primitives Tagger output missing",
            "priority": "critical",
            "suggested_focus": "Run Phase 1 Primitives Tagger agent",
        })

    # ── Phase 1: Thread Extractions ───────────────────────────────────
    threads = load_json(session_dir / "thread_extractions.json")
    if threads:
        file_status["thread_extractions.json"] = "present"
        thread_data = threads.get("threads", {})

        for thread_name in ["ideas", "reactions", "software", "code"]:
            entries = []
            if isinstance(thread_data.get(thread_name), dict):
                entries = thread_data[thread_name].get("entries", [])
            elif isinstance(thread_data.get(thread_name), list):
                entries = thread_data[thread_name]

            c, g = check_count_threshold(len(entries), 3, f"threads.{thread_name}", "entries")
            confirmed.append(c)
            if g: gaps.append(g)
    else:
        file_status["thread_extractions.json"] = "MISSING"
        gaps.append({
            "field": "thread_extractions",
            "missing_values": ["entire file"],
            "reason": "Phase 1 Thread Analyst output missing",
            "priority": "critical",
            "suggested_focus": "Run Phase 1 Thread Analyst agent",
        })

    # ── Phase 1: Geological Notes ─────────────────────────────────────
    geological = load_json(session_dir / "geological_notes.json")
    if geological:
        file_status["geological_notes.json"] = "present"
        micro = geological.get("micro", [])
        meso = geological.get("meso", [])
        macro = geological.get("macro", [])

        c, g = check_count_threshold(len(micro), MIN_GEOLOGICAL_MICRO, "geological.micro", "observations")
        confirmed.append(c)
        if g: gaps.append(g)

        c, g = check_count_threshold(len(meso), MIN_GEOLOGICAL_MESO, "geological.meso", "phase observations")
        confirmed.append(c)
        if g: gaps.append(g)
    else:
        file_status["geological_notes.json"] = "MISSING"

    # ── Phase 1: Explorer Notes ───────────────────────────────────────
    explorer = load_json(session_dir / "explorer_notes.json")
    if explorer:
        file_status["explorer_notes.json"] = "present"
        obs = explorer.get("observations", [])
        c, g = check_count_threshold(len(obs), MIN_EXPLORER_OBS, "explorer.observations", "observations")
        confirmed.append(c)
        if g: gaps.append(g)
    else:
        file_status["explorer_notes.json"] = "MISSING"

    # ── Phase 2: Idea Graph (prefer Opus-filtered if available) ─────
    idea_graph = load_json(session_dir / "idea_graph_opus.json") or load_json(session_dir / "idea_graph.json")
    if idea_graph:
        file_status["idea_graph.json"] = "present"
        nodes = idea_graph.get("nodes", [])
        edges = idea_graph.get("edges", [])

        c, g = check_count_threshold(len(nodes), MIN_IDEA_NODES, "idea_graph.nodes", "nodes")
        confirmed.append(c)
        if g: gaps.append(g)

        # Check edge type coverage (handle schema variants: relation, type, transition_type, edge_type)
        edge_types_found = [
            e.get("relation", e.get("type", e.get("transition_type", e.get("edge_type", ""))))
            for e in edges
        ]
        c, g = check_enum_coverage(edge_types_found, EDGE_TYPES, "idea_graph.edge_types")
        confirmed.append(c)
        if g: gaps.append(g)
    else:
        file_status["idea_graph.json"] = "MISSING"
        gaps.append({
            "field": "idea_graph",
            "missing_values": ["entire file"],
            "reason": "Phase 2 Idea Graph Builder output missing",
            "priority": "high",
            "suggested_focus": "Run Phase 2 Idea Graph Builder agent",
        })

    # ── Phase 2: Grounded Markers ─────────────────────────────────────
    markers = load_json(session_dir / "grounded_markers_opus.json") or load_json(session_dir / "grounded_markers.json")
    if markers:
        file_status["grounded_markers.json"] = "present"

        # Handle two schemas:
        # Old: {"markers": [{category, claim, ...}]}
        # New: {"warnings": [...], "patterns": [...], "recommendations": [...], "metrics": [...]}
        marker_list = markers.get("markers", [])
        if not marker_list:
            # New schema — count all items across the 4 categories
            for key in ["warnings", "patterns", "recommendations", "metrics"]:
                marker_list.extend(markers.get(key, []))

        c, g = check_count_threshold(len(marker_list), MIN_GROUNDED_MARKERS, "grounded_markers", "markers")
        confirmed.append(c)
        if g: gaps.append(g)

        # Check category coverage
        # Old schema: category field per marker
        # New schema: the key itself IS the category (warnings=risk, patterns=behavior, etc.)
        categories_found = []
        if markers.get("markers"):
            categories_found = [
                m.get("category", m.get("_source_type", m.get("severity", "")))
                for m in markers["markers"]
            ]
        else:
            # Map new schema keys to standard categories
            schema_to_category = {
                "warnings": "risk",
                "patterns": "behavior",
                "recommendations": "decision",
                "metrics": "architecture",
            }
            for key, category in schema_to_category.items():
                if markers.get(key):
                    categories_found.extend([category] * len(markers[key]))
            # Also add "opportunity" if recommendations exist (they suggest improvements)
            if markers.get("recommendations"):
                categories_found.append("opportunity")

        c, g = check_enum_coverage(categories_found, MARKER_CATEGORIES, "grounded_markers.categories")
        confirmed.append(c)
        if g: gaps.append(g)
    else:
        file_status["grounded_markers.json"] = "MISSING"

    # ── Phase 3: File Dossiers ────────────────────────────────────────
    dossiers = load_json(session_dir / "file_dossiers.json")
    if dossiers:
        file_status["file_dossiers.json"] = "present"
        d = dossiers.get("dossiers", dossiers)
        count = len(d) if isinstance(d, (dict, list)) else 0

        c, g = check_count_threshold(count, MIN_FILE_DOSSIERS, "file_dossiers", "files")
        confirmed.append(c)
        if g: gaps.append(g)

        # Check dossier field completeness
        if isinstance(d, dict):
            items = list(d.values())
        elif isinstance(d, list):
            items = d
        else:
            items = []

        fields_to_check = ["story_arc", "warnings", "key_decisions", "confidence"]
        for field in fields_to_check:
            populated = sum(1 for item in items if item.get(field))
            c, g = check_populated_ratio(populated, len(items), f"dossier.{field}")
            confirmed.append(c)
            if g: gaps.append(g)
    else:
        file_status["file_dossiers.json"] = "MISSING"

    # ── Phase 5: Ground Truth ─────────────────────────────────────────
    ground_truth = load_json(session_dir / "ground_truth_verification.json")
    if ground_truth:
        file_status["ground_truth_verification.json"] = "present"
        claims = ground_truth.get("claims", {})
        if isinstance(claims, dict):
            cl = claims.get("claims", [])
        else:
            cl = claims

        verified = sum(1 for c in cl if c.get("verification_status") == "verified")
        failed = sum(1 for c in cl if c.get("verification_status") == "failed")
        unverified = len(cl) - verified - failed

        confirmed.append({
            "field": "ground_truth",
            "coverage": f"{verified} verified, {failed} failed, {unverified} unverified of {len(cl)} claims",
            "confidence": round(verified / len(cl), 2) if cl else 0,
            "evidence_count": len(cl),
        })

        if unverified > len(cl) / 2:
            gaps.append({
                "field": "ground_truth",
                "missing_values": [f"{unverified} unverified claims"],
                "reason": f"{unverified}/{len(cl)} claims could not be verified (file may not exist on disk)",
                "priority": "medium",
                "suggested_focus": "For deleted files, verify claims against session data instead of filesystem",
            })
    else:
        file_status["ground_truth_verification.json"] = "MISSING"

    # ── Convergence Metrics ───────────────────────────────────────────
    total_confirmed = len(confirmed)
    total_gaps = len(gaps)
    critical_gaps = sum(1 for g in gaps if g.get("priority") == "critical")
    high_gaps = sum(1 for g in gaps if g.get("priority") == "high")

    # Compare to previous pass if provided
    delta = None
    if previous_checklist:
        prev_confirmed = len(previous_checklist.get("confirmed", []))
        prev_gaps = len(previous_checklist.get("gaps", []))
        if prev_confirmed > 0:
            delta = round((total_confirmed - prev_confirmed) / prev_confirmed, 3)

    # Recommendation
    if critical_gaps > 0:
        recommendation = "critical_gaps_remain"
    elif high_gaps > 2:
        recommendation = "continue"
    elif delta is not None and abs(delta) < 0.02:
        recommendation = "converged"
    elif total_gaps == 0:
        recommendation = "converged"
    else:
        recommendation = "continue"

    pass_number = 1
    if previous_checklist:
        pass_number = previous_checklist.get("pass_number", 0) + 1

    return {
        "pass_number": pass_number,
        "session_id": SESSION_ID or session_dir.name.replace("session_", ""),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "gap_checklist.py",
        "file_status": file_status,
        "confirmed": confirmed,
        "gaps": gaps,
        "convergence": {
            "total_confirmed": total_confirmed,
            "total_gaps": total_gaps,
            "critical_gaps": critical_gaps,
            "high_gaps": high_gaps,
            "medium_gaps": sum(1 for g in gaps if g.get("priority") == "medium"),
            "delta_from_previous": delta,
            "recommendation": recommendation,
        },
        "summary": {
            "files_present": sum(1 for v in file_status.values() if v == "present"),
            "files_missing": sum(1 for v in file_status.values() if v == "MISSING"),
            "coverage_score": round(total_confirmed / (total_confirmed + total_gaps), 2) if (total_confirmed + total_gaps) > 0 else 0,
        },
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Gap Checklist Generator")
    parser.add_argument("--session", default="", help="Session ID (default: from env)")
    parser.add_argument("--dir", default="", help="Session output directory path")
    parser.add_argument("--compare", default="", help="Path to previous gap_checklist.json for convergence comparison")
    args = parser.parse_args()

    # Determine session directory
    if args.dir:
        session_dir = Path(args.dir)
    elif args.session:
        # Search in output/ and PERMANENT_HYPERDOCS/sessions/
        candidates = [
            Path(__file__).resolve().parent / "output" / f"session_{args.session[:8]}",
            Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{args.session[:8]}",
        ]
        session_dir = next((c for c in candidates if c.exists()), candidates[0])
    else:
        session_dir = get_session_output_dir()

    print("=" * 60)
    print("Gap Checklist Generator")
    print("=" * 60)
    print(f"Session dir: {session_dir}")
    print()

    if not session_dir.exists():
        print(f"ERROR: Session directory not found: {session_dir}")
        sys.exit(1)

    # Load previous checklist for comparison
    previous = None
    if args.compare:
        previous = load_json(Path(args.compare))
    else:
        # Check if a previous checklist exists in the session dir
        prev_path = session_dir / "gap_checklist.json"
        if prev_path.exists():
            previous = load_json(prev_path)

    # Analyze
    checklist = analyze_session(session_dir, previous)

    # Write output
    out_path = session_dir / "gap_checklist.json"
    with open(out_path, "w") as f:
        json.dump(checklist, f, indent=2, default=str)

    # Print summary
    conv = checklist["convergence"]
    summ = checklist["summary"]

    print(f"Pass: {checklist['pass_number']}")
    print(f"Files present: {summ['files_present']}, missing: {summ['files_missing']}")
    print(f"Confirmed: {conv['total_confirmed']}, Gaps: {conv['total_gaps']}")
    print(f"  Critical: {conv['critical_gaps']}, High: {conv['high_gaps']}, Medium: {conv['medium_gaps']}")
    print(f"Coverage score: {summ['coverage_score']:.0%}")

    if conv["delta_from_previous"] is not None:
        print(f"Delta from previous pass: {conv['delta_from_previous']:+.1%}")

    print(f"Recommendation: {conv['recommendation']}")
    print()

    if checklist["gaps"]:
        print("Top gaps:")
        for g in sorted(checklist["gaps"], key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.get("priority", "low"), 4))[:5]:
            print(f"  [{g['priority'].upper():8s}] {g['field']}: {g.get('reason', '')[:80]}")

    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
