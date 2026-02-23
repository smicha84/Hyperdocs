#!/usr/bin/env python3
"""
Version A Experiment: Core 4 fields + evidence directives.

Per-file brief contains:
  - confidence_history — array of {session, confidence} from cross_session_file_index
  - merged_warnings — deduplicated warning strings across sessions
  - genealogy_family — name + version count from cross_session_genealogy
  - code_similarity_top3 — top 3 matches from code_similarity_index
  - evidence_blocks — 1-3 @evidence directive strings referencing highest-impact sessions

$0 cost — pure Python, no LLM calls.

Usage:
    python3 experiment/feedback_loop/version_a.py
    python3 experiment/feedback_loop/version_a.py --files p01_plan_enforcer.py CLAUDE.md llm_client.py
"""
import json
import os
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────
H3 = Path(__file__).resolve().parent.parent.parent
_STORE = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS")))
INDEXES_DIR = _STORE / "indexes"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Default target files (richest cross-session data)
DEFAULT_TARGETS = ["p01_plan_enforcer.py", "CLAUDE.md", "llm_client.py"]


def load_index(filename):
    """Load a JSON index file from PERMANENT_HYPERDOCS/indexes/ or output/."""
    for d in [INDEXES_DIR, H3 / "output"]:
        path = d / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    print(f"  WARNING: {filename} not found in {INDEXES_DIR} or {H3 / 'output'}")
    return {}


def load_store_file(filename):
    """Load a JSON file from PERMANENT_HYPERDOCS root."""
    path = _STORE / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    print(f"  WARNING: {filename} not found at {path}")
    return {}


def find_file_entry(files_dict, target_file):
    """Find a file entry by bare filename first, then by path suffix.

    The index uses both bare filenames ('p01_plan_enforcer.py') and
    full paths ('.claude/hooks/p01_plan_enforcer.py'). Bare filenames
    have far more session data, so we prefer them.
    """
    # Direct lookup
    if target_file in files_dict:
        return files_dict[target_file]

    # Basename lookup (for targets given as paths)
    basename = Path(target_file).name
    if basename in files_dict:
        return files_dict[basename]

    # Suffix match (for targets like 'p01_plan_enforcer.py' that might be stored with paths)
    for key, entry in files_dict.items():
        if key.endswith("/" + target_file) or key.endswith("\\" + target_file):
            return entry

    return {}


def find_genealogy_family(genealogy_data, target_file):
    """Find the genealogy family containing the target file."""
    families = genealogy_data.get("cross_session_families", [])
    basename = Path(target_file).stem  # e.g., 'p01_plan_enforcer'

    for family in families:
        versions = family.get("versions", [])
        for v in versions:
            vfile = v.get("file", "") if isinstance(v, dict) else str(v)
            if target_file in vfile or basename in vfile:
                return {
                    "concept": family.get("concept", "unnamed"),
                    "version_count": len(versions),
                    "members": [
                        {
                            "file": ver.get("file", "") if isinstance(ver, dict) else str(ver),
                            "status": ver.get("status", "unknown") if isinstance(ver, dict) else "unknown",
                            "session_count": ver.get("session_count", 0) if isinstance(ver, dict) else 0,
                        }
                        for ver in versions
                    ],
                }
    return None


def find_code_similarity(sim_data, target_file):
    """Find top 3 code similarity matches for the target file."""
    by_file = {}
    matches = sim_data.get("matches", sim_data.get("pairs", []))

    for m in matches:
        if not isinstance(m, dict):
            continue
        f1 = m.get("file_a", m.get("file1", ""))
        f2 = m.get("file_b", m.get("file2", ""))
        signals = m.get("signals", {})
        score = m.get("score", signals.get("signal_score",
                 signals.get("text_similarity",
                 signals.get("func_overlap", 0))))
        ptype = m.get("pattern_type", m.get("type", "unknown"))

        basename = Path(target_file).name
        if basename in f1 or target_file in f1:
            by_file.setdefault(target_file, []).append({
                "similar_to": f2, "score": round(score, 3), "pattern": ptype
            })
        elif basename in f2 or target_file in f2:
            by_file.setdefault(target_file, []).append({
                "similar_to": f1, "score": round(score, 3), "pattern": ptype
            })

    results = by_file.get(target_file, [])
    results.sort(key=lambda x: -x["score"])
    return results[:3]


def generate_evidence_directives(file_entry, target_file):
    """Generate 1-3 @evidence directive strings for the highest-impact sessions.

    Selects sessions from confidence_history (explicit confidence ratings),
    frustration_associations (user friction), and story_arcs (narrative context).
    """
    directives = []

    # Pick sessions from confidence history (most informative for cross-session context)
    conf_hist = file_entry.get("confidence_history", [])
    sessions_seen = set()

    # Find sessions with interesting confidence values
    for entry in conf_hist:
        sid = entry.get("session", "")
        if sid and sid not in sessions_seen:
            sessions_seen.add(sid)
            directives.append(
                f'@evidence:file_timeline(file="{target_file}") [session:{sid}]'
            )
            if len(directives) >= 2:
                break

    # If we have frustration associations, pick the most intense one
    frust = file_entry.get("frustration_associations", [])
    if frust:
        # Sort by caps_ratio descending (highest frustration first)
        frust_sorted = sorted(frust, key=lambda x: x.get("caps_ratio", 0), reverse=True)
        top_frust = frust_sorted[0]
        sid = top_frust.get("session", "")
        msg_idx = top_frust.get("message_index", 0)
        if sid and sid not in sessions_seen:
            sessions_seen.add(sid)
            start = max(0, msg_idx - 10)
            end = msg_idx + 10
            directives.append(
                f'@evidence:reaction_log(range=[{start},{end}]) [session:{sid}]'
            )

    # Cap at 3
    return directives[:3]


def build_file_brief(target_file, file_entry, genealogy_data, sim_data):
    """Build the Version A brief for a single file."""
    return {
        "file": target_file,
        "version": "A",
        "confidence_history": file_entry.get("confidence_history", []),
        "merged_warnings": file_entry.get("merged_warnings", []),
        "genealogy_family": find_genealogy_family(genealogy_data, target_file),
        "code_similarity_top3": find_code_similarity(sim_data, target_file),
        "evidence_blocks": generate_evidence_directives(file_entry, target_file),
        "session_count": file_entry.get("session_count", 0),
        "total_mentions": file_entry.get("total_mentions", 0),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Version A: Core 4 fields + evidence directives")
    parser.add_argument("--files", nargs="+", default=DEFAULT_TARGETS,
                       help="Target files to generate briefs for")
    args = parser.parse_args()

    print("=" * 60)
    print("Version A: Core 4 fields + evidence directives")
    print("=" * 60)

    # Load indexes
    print("Loading cross_session_file_index.json...")
    file_index = load_index("cross_session_file_index.json")
    files_dict = file_index.get("files", {})
    print(f"  {len(files_dict)} files indexed")

    print("Loading cross_session_genealogy.json...")
    genealogy_data = load_store_file("cross_session_genealogy.json")
    families_count = len(genealogy_data.get("cross_session_families", []))
    print(f"  {families_count} genealogy families")

    print("Loading code_similarity_index.json...")
    sim_data = load_index("code_similarity_index.json")
    sim_count = len(sim_data.get("matches", sim_data.get("pairs", [])))
    print(f"  {sim_count} similarity pairs")
    print()

    # Build briefs
    briefs = {}
    for target_file in args.files:
        print(f"Processing {target_file}...")
        entry = find_file_entry(files_dict, target_file)
        if not entry:
            print(f"  WARNING: {target_file} not found in cross-session index")
            briefs[target_file] = {
                "file": target_file,
                "version": "A",
                "confidence_history": [],
                "merged_warnings": [],
                "genealogy_family": find_genealogy_family(genealogy_data, target_file),
                "code_similarity_top3": find_code_similarity(sim_data, target_file),
                "evidence_blocks": [],
                "session_count": 0,
                "total_mentions": 0,
            }
            continue

        brief = build_file_brief(target_file, entry, genealogy_data, sim_data)
        briefs[target_file] = brief

        print(f"  sessions: {brief['session_count']}")
        print(f"  confidence_history: {len(brief['confidence_history'])} entries")
        print(f"  merged_warnings: {len(brief['merged_warnings'])} warnings")
        print(f"  genealogy: {brief['genealogy_family']['concept'] if brief['genealogy_family'] else 'none'}")
        print(f"  code_similarity: {len(brief['code_similarity_top3'])} matches")
        print(f"  evidence_blocks: {len(brief['evidence_blocks'])} directives")
        print()

    # Assemble output
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "feedback_loop/version_a — Core 4 fields + evidence directives",
        "version": "A",
        "target_files": list(briefs.keys()),
        "briefs": briefs,
    }

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "version_a_briefs.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    size = out_path.stat().st_size
    print(f"Output: {out_path}")
    print(f"Size: {size:,} bytes")


if __name__ == "__main__":
    main()
