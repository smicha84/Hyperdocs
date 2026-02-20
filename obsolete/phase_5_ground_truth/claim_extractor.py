#!/usr/bin/env python3
"""
Claim Extractor — Extract verifiable claims from pipeline outputs.

Reads grounded_markers.json, semantic_primitives.json, synthesis.json,
idea_graph.json and maps claims to specific files.

Portable: derives file list from file_dossiers.json instead of hardcoding.

Usage:
    python3 claim_extractor.py --session 0012ebed
    python3 claim_extractor.py --dir /path/to/session_output/

Output: ground_truth_claims.json in the session output directory
"""
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import get_session_output_dir, SESSION_ID
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    _out = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(Path(__file__).parent.parent / "output")))
    def get_session_output_dir():
        d = _out / f"session_{SESSION_ID[:8]}"
        d.mkdir(parents=True, exist_ok=True)
        return d


def load_json(session_dir, filename):
    """Load JSON file from session directory."""
    path = session_dir / filename
    if not path.exists():
        print(f"  WARN: {filename} not found")
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"  WARN: {filename} could not be parsed")
        return {}


def get_file_list(session_dir):
    """Derive target files from file_dossiers.json instead of hardcoding."""
    dossiers = load_json(session_dir, "file_dossiers.json")
    if not dossiers:
        # Fallback: extract from session_metadata file mentions
        summary = load_json(session_dir, "session_metadata.json")
        stats = summary.get("session_stats", summary)
        mentions = stats.get("file_mention_counts", {})
        return sorted(mentions.keys())

    d = dossiers.get("dossiers", dossiers)
    if isinstance(d, dict):
        return sorted(d.keys())
    elif isinstance(d, list):
        FILE_KEYS = ("file", "filename", "file_name", "file_path", "file_id")
        names = set()
        for item in d:
            if not isinstance(item, dict):
                continue
            for key in FILE_KEYS:
                val = item.get(key, "")
                if val:
                    # Extract just the filename from paths
                    name = val.rsplit("/", 1)[-1] if "/" in val else val
                    names.add(name)
                    break
        return sorted(names)
    return []


def file_matches_target(filename, target, all_files):
    """Check if a warning target applies to a specific file."""
    if not target:
        return False
    target_lower = target.lower()
    if filename.lower() in target_lower:
        return True
    if "all python files" in target_lower or "all files" in target_lower:
        return True
    if "v5 code" in target_lower:
        return filename.endswith(".py")
    if ".env" in target_lower:
        return filename.endswith(".py")
    return False


def extract_warning_claims(markers, all_files):
    """Extract resolution claims and unresolved warnings from grounded_markers."""
    per_file = {f: {"resolution_claims": [], "unresolved_warnings": []} for f in all_files}

    # Handle both schemas: {"warnings": [...]} and {"markers": [...]}
    warnings = markers.get("warnings", [])
    if not warnings:
        # Old schema: markers with category
        for m in markers.get("markers", []):
            cat = m.get("category", m.get("_source_type", ""))
            if cat in ("risk", "warning"):
                warnings.append(m)

    for w in warnings:
        target = w.get("target", w.get("actionable_guidance", ""))
        warning_id = w.get("id", w.get("marker_id", ""))
        warning_text = w.get("warning", w.get("claim", ""))
        severity = w.get("severity", w.get("confidence", "unknown"))
        first_discovered = w.get("first_discovered")
        resolution_index = w.get("resolution_index")
        evidence = w.get("evidence", "")

        for filename in all_files:
            if not file_matches_target(filename, target, all_files):
                # Also try matching on evidence and claim text
                search_text = f"{target} {evidence} {warning_text}".lower()
                stem = filename.replace(".py", "").replace("_", " ").lower()
                if stem not in search_text and filename.lower() not in search_text:
                    continue

            entry = {
                "warning_id": warning_id,
                "severity": severity,
                "warning": warning_text,
                "first_discovered": first_discovered,
                "evidence": evidence,
            }

            if resolution_index is not None:
                entry["claim"] = f"Fixed at msg {resolution_index}"
                entry["resolution_index"] = resolution_index
                per_file[filename]["resolution_claims"].append(entry)
            else:
                entry["claim"] = "UNRESOLVED — no fix recorded"
                per_file[filename]["unresolved_warnings"].append(entry)

    return per_file


def extract_confidence_claims(primitives, all_files):
    """Extract messages where confidence=proven/stable and map to files."""
    per_file = {f: [] for f in all_files}
    messages = primitives.get("tagged_messages", primitives.get("messages", []))

    for msg in messages:
        confidence = msg.get("confidence_signal", "")
        if confidence not in ("proven", "stable"):
            continue

        idx = msg.get("msg_index", msg.get("index", msg.get("message_index", None)))
        friction = msg.get("friction_log", "")
        decision = msg.get("decision_trace", "")
        action = msg.get("action_vector", "")

        text_to_search = f"{friction} {decision}".lower()

        for filename in all_files:
            stem = filename.replace(".py", "").replace("_", " ").lower()
            if stem in text_to_search or filename.lower() in text_to_search:
                per_file[filename].append({
                    "claim": f"Confidence={confidence} at msg {idx}",
                    "msg_index": idx,
                    "confidence": confidence,
                    "action": action,
                    "friction": friction,
                    "decision": decision,
                })

    return per_file


def extract_pattern_claims(markers, all_files):
    """Extract behavioral pattern claims (B02 premature victory, etc.)."""
    per_file = {f: [] for f in all_files}

    patterns = markers.get("patterns", [])
    for p in patterns:
        pid = p.get("id", p.get("marker_id", ""))
        description = p.get("description", p.get("claim", ""))
        frequency = p.get("frequency", "")

        # Session-wide patterns apply to all files
        for filename in all_files:
            per_file[filename].append({
                "pattern": pid,
                "claim": f"{pid}: {description[:100]}",
                "frequency": frequency,
                "session_wide": True,
            })

    return per_file


def extract_idea_confidence_claims(idea_graph, all_files):
    """Extract idea nodes with high confidence and map to files."""
    per_file = {f: [] for f in all_files}
    nodes = idea_graph.get("nodes", [])

    for node in nodes:
        confidence = node.get("confidence", "")
        if confidence not in ("proven", "stable", "working"):
            continue

        label = node.get("label", node.get("name", ""))
        description = node.get("description", "")

        text_to_search = f"{label} {description}".lower()
        for filename in all_files:
            stem = filename.replace(".py", "").replace("_", " ").lower()
            if stem in text_to_search or filename.lower() in text_to_search:
                per_file[filename].append({
                    "claim": f"Idea '{label}' confidence={confidence}",
                    "idea_label": label,
                    "confidence": confidence,
                    "description": description[:200],
                })

    return per_file


def merge_claims(all_files, warning_claims, confidence_claims, pattern_claims, idea_claims):
    """Merge all claim types into a single per-file structure."""
    result = {}
    for filename in all_files:
        result[filename] = {
            "resolution_claims": warning_claims.get(filename, {}).get("resolution_claims", []),
            "unresolved_warnings": warning_claims.get(filename, {}).get("unresolved_warnings", []),
            "confidence_claims": confidence_claims.get(filename, []),
            "pattern_claims": pattern_claims.get(filename, []),
            "idea_confidence_claims": idea_claims.get(filename, []),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description="Claim Extractor — Ground Truth Verification")
    parser.add_argument("--session", default="", help="Session ID")
    parser.add_argument("--dir", default="", help="Session output directory path")
    args = parser.parse_args()

    # Determine session directory
    if args.dir:
        session_dir = Path(args.dir)
    elif args.session:
        candidates = [
            Path(__file__).resolve().parent.parent / "output" / f"session_{args.session[:8]}",
            Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{args.session[:8]}",
        ]
        session_dir = next((c for c in candidates if c.exists()), candidates[0])
    else:
        session_dir = get_session_output_dir()

    print("=" * 60)
    print("Claim Extractor — Ground Truth Verification")
    print("=" * 60)
    print(f"Session dir: {session_dir}")
    print()

    if not session_dir.exists():
        print(f"ERROR: Session directory not found: {session_dir}")
        sys.exit(1)

    # Derive file list from session data
    all_files = get_file_list(session_dir)
    if not all_files:
        # Fallback: try session_metadata file mentions directly
        summary = load_json(session_dir, "session_metadata.json")
        stats = summary.get("session_stats", summary)
        mentions = stats.get("file_mention_counts", {})
        all_files = sorted(mentions.keys())
    if not all_files:
        print("WARNING: No target files found — writing empty claims")
        # Write empty claims file so Phase 5 pipeline doesn't re-attempt
        output = {
            "session_id": args.session or session_dir.name.replace("session_", ""),
            "generated_at": datetime.now().isoformat(),
            "total_files": 0,
            "total_claims": 0,
            "claims": {},
        }
        out_path = session_dir / "ground_truth_claims.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Output: {out_path}")
        return
    print(f"Target files: {len(all_files)}")

    markers = load_json(session_dir, "grounded_markers.json")
    primitives = load_json(session_dir, "semantic_primitives.json")
    idea_graph = load_json(session_dir, "idea_graph.json")

    print("Extracting claims...")
    warning_claims = extract_warning_claims(markers, all_files)
    confidence_claims = extract_confidence_claims(primitives, all_files)
    pattern_claims = extract_pattern_claims(markers, all_files)
    idea_claims = extract_idea_confidence_claims(idea_graph, all_files)

    all_claims = merge_claims(all_files, warning_claims, confidence_claims, pattern_claims, idea_claims)

    # Summary
    print()
    total_claims = 0
    for filename in all_files:
        fc = all_claims[filename]
        file_total = (len(fc["resolution_claims"]) + len(fc["unresolved_warnings"]) +
                      len(fc["confidence_claims"]) + len(fc["pattern_claims"]) +
                      len(fc["idea_confidence_claims"]))
        total_claims += file_total
        if file_total > 0:
            print(f"  {filename}: {file_total} claims")

    # Write output
    session_id = args.session or SESSION_ID or session_dir.name.replace("session_", "")
    output = {
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "total_files": len(all_files),
        "total_claims": total_claims,
        "claims": all_claims,
    }

    out_path = session_dir / "ground_truth_claims.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nTotal: {total_claims} claims across {len(all_files)} files")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
