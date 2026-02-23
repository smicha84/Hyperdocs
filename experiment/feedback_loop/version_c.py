#!/usr/bin/env python3
"""
Version C Experiment: Full 8 cross-session types + everything from Version B.

Includes ALL 8 cross-session data types from aggregate_dossiers.py:
  1. cross_session_emotional_arc — per-session emotions + cross-emotion distribution
  2. cross_session_geological — observations tagged by session
  3. cross_session_explorer — explorer notes across sessions
  4. cross_session_timeline — events with session tags
  5. cross_session_graph_context — connectivity across sessions
  6. cross_session_synthesis — per-session synthesis data
  7. cross_session_geological_metaphors — session-level metaphors
  8. cross_session_claude_md — session-level Claude.md context

Plus all of Version B's fields (core 4 + rendered evidence + emotional_trend + decisions).

$0 cost — pure Python, no LLM calls.

Usage:
    python3 experiment/feedback_loop/version_c.py
    python3 experiment/feedback_loop/version_c.py --files p01_plan_enforcer.py CLAUDE.md llm_client.py
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────
H3 = Path(__file__).resolve().parent.parent.parent
_STORE = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS")))
INDEXES_DIR = _STORE / "indexes"
SESSIONS_DIR = _STORE / "sessions"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LOCAL_OUTPUT = H3 / "output"

if str(H3) not in sys.path:
    sys.path.insert(0, str(H3))

DEFAULT_TARGETS = ["p01_plan_enforcer.py", "CLAUDE.md", "llm_client.py"]

# The 8 cross-session data type keys from aggregate_dossiers.py
CROSS_SESSION_KEYS = [
    "cross_session_emotional_arc",
    "cross_session_geological",
    "cross_session_explorer",
    "cross_session_timeline",
    "cross_session_graph_context",
    "cross_session_synthesis",
    "cross_session_geological_metaphors",
    "cross_session_claude_md",
]


def load_index(filename):
    """Load a JSON index file from PERMANENT_HYPERDOCS/indexes/ or output/."""
    for d in [INDEXES_DIR, LOCAL_OUTPUT]:
        path = d / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    print(f"  WARNING: {filename} not found")
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
    """Find a file entry by bare filename first, then by path suffix."""
    if target_file in files_dict:
        return files_dict[target_file]
    basename = Path(target_file).name
    if basename in files_dict:
        return files_dict[basename]
    for key in files_dict:
        if key.endswith("/" + target_file) or key.endswith("\\" + target_file):
            return files_dict[key]
    return {}


def find_genealogy_family(genealogy_data, target_file):
    """Find the genealogy family containing the target file."""
    families = genealogy_data.get("cross_session_families", [])
    basename = Path(target_file).stem

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
    results = []
    matches = sim_data.get("matches", sim_data.get("pairs", []))
    basename = Path(target_file).name

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

        if basename in f1 or target_file in f1:
            results.append({"similar_to": f2, "score": round(score, 3), "pattern": ptype})
        elif basename in f2 or target_file in f2:
            results.append({"similar_to": f1, "score": round(score, 3), "pattern": ptype})

    results.sort(key=lambda x: -x["score"])
    return results[:3]


def find_session_dir(session_id):
    """Find the session output directory (PERM first, then local)."""
    short = session_id[:8]
    for base in [SESSIONS_DIR, LOCAL_OUTPUT]:
        candidate = base / f"session_{short}"
        if candidate.exists():
            return candidate
    return None


def render_evidence_for_session(session_id, target_file, directive_type="file_timeline"):
    """Render an evidence block from a specific session."""
    session_dir = find_session_dir(session_id)
    if not session_dir:
        return None

    try:
        from phase_3_hyperdoc_writing.evidence import RENDERER_REGISTRY
        renderer_cls = RENDERER_REGISTRY.get(directive_type)
        if not renderer_cls:
            return None
        renderer = renderer_cls(session_dir, session_id[:8])

        if directive_type == "file_timeline":
            return renderer.render({"file": target_file})
        elif directive_type == "idea_transition":
            nodes = renderer.idea_graph.get("nodes", [])
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                label = node.get("label", node.get("name", ""))
                if target_file.replace(".py", "") in label.lower() or target_file in label:
                    return renderer.render({"node": node.get("id", "")})
            return None
    except Exception as e:
        return f"[render error: {e}]"

    return None


def generate_rendered_evidence(file_entry, target_file):
    """Generate pre-resolved evidence blocks (same as Version B)."""
    blocks = []
    conf_hist = file_entry.get("confidence_history", [])
    sessions_seen = set()

    for entry in conf_hist:
        sid = entry.get("session", "")
        if sid and sid not in sessions_seen:
            rendered = render_evidence_for_session(sid, target_file, "file_timeline")
            if rendered and "[evidence unavailable" not in rendered and "[render error" not in rendered:
                sessions_seen.add(sid)
                blocks.append({
                    "type": "file_timeline",
                    "session": sid,
                    "confidence_at_session": entry.get("confidence", "unknown"),
                    "rendered": rendered,
                })
            if len(blocks) >= 2:
                break

    for entry in conf_hist:
        sid = entry.get("session", "")
        if sid and sid not in sessions_seen:
            rendered = render_evidence_for_session(sid, target_file, "idea_transition")
            if rendered and "[evidence unavailable" not in rendered and "[render error" not in rendered:
                sessions_seen.add(sid)
                blocks.append({
                    "type": "idea_transition",
                    "session": sid,
                    "confidence_at_session": entry.get("confidence", "unknown"),
                    "rendered": rendered,
                })
                break

    frust = file_entry.get("frustration_associations", [])
    if frust:
        frust_sorted = sorted(frust, key=lambda x: x.get("caps_ratio", 0), reverse=True)
        for peak in frust_sorted:
            sid = peak.get("session", "")
            if sid and sid not in sessions_seen:
                rendered = render_evidence_for_session(sid, target_file, "file_timeline")
                if rendered and "[evidence unavailable" not in rendered:
                    sessions_seen.add(sid)
                    blocks.append({
                        "type": "file_timeline",
                        "session": sid,
                        "trigger": "frustration_peak",
                        "rendered": rendered,
                    })
                    break

    return blocks[:3]


def build_emotional_trend(file_entry):
    """Build per-session dominant emotion trend."""
    trend = []
    emo_arc = file_entry.get("cross_session_emotional_arc", {})
    per_session = emo_arc.get("per_session_emotions", {})
    if per_session:
        for sid, emo_data in sorted(per_session.items()):
            trend.append({
                "session": sid,
                "dominant_emotion": emo_data.get("dominant_emotion", "unknown"),
                "session_arc": emo_data.get("session_arc", ""),
                "friction_episodes": emo_data.get("friction_episodes", 0),
            })

    for arc in file_entry.get("story_arcs", []):
        sid = arc.get("session", "")
        arc_text = arc.get("arc", "")
        if sid and not any(t["session"] == sid for t in trend):
            trend.append({
                "session": sid,
                "dominant_emotion": "inferred_from_arc",
                "session_arc": arc_text[:200],
                "friction_episodes": 0,
            })

    return trend


def build_decision_trajectory(file_entry):
    """Build chronological decision trajectory across sessions."""
    trajectory = []
    for d in file_entry.get("merged_decisions", []):
        if isinstance(d, dict):
            trajectory.append(d)
        elif isinstance(d, str):
            trajectory.append({"decision": d})

    patterns = file_entry.get("behavioral_patterns", {})
    for pattern_key, pattern_entries in patterns.items():
        if "decision" in pattern_key.lower():
            for pe in pattern_entries:
                if isinstance(pe, dict):
                    trajectory.append({
                        "session": pe.get("session", ""),
                        "decision": pe.get("value", str(pe)),
                        "pattern_type": pattern_key,
                    })

    return trajectory


def extract_cross_session_data(file_entry):
    """Extract all 8 cross-session data types from the file index entry."""
    cross_session = {}
    for key in CROSS_SESSION_KEYS:
        value = file_entry.get(key, {} if "arc" in key or "context" in key or "synthesis" in key or "claude_md" in key or "metaphors" in key else [])
        cross_session[key] = value
    return cross_session


def count_cross_session_data_points(cross_session):
    """Count data points across all 8 cross-session types."""
    counts = {}

    # 1. emotional_arc
    emo = cross_session.get("cross_session_emotional_arc", {})
    counts["emotional_arc"] = len(emo.get("per_session_emotions", {}))

    # 2. geological
    counts["geological"] = len(cross_session.get("cross_session_geological", []))

    # 3. explorer
    counts["explorer"] = len(cross_session.get("cross_session_explorer", []))

    # 4. timeline
    counts["timeline"] = len(cross_session.get("cross_session_timeline", []))

    # 5. graph_context
    gc = cross_session.get("cross_session_graph_context", {})
    counts["graph_context"] = len(gc.get("all_connected_edges", [])) + len(gc.get("all_subgraphs", []))

    # 6. synthesis
    synth = cross_session.get("cross_session_synthesis", {})
    counts["synthesis"] = len(synth.get("per_session", {}))

    # 7. geological_metaphors
    counts["geological_metaphors"] = len(cross_session.get("cross_session_geological_metaphors", {}))

    # 8. claude_md
    cmd = cross_session.get("cross_session_claude_md", {})
    counts["claude_md"] = len(cmd.get("per_session", {}))

    return counts


def build_file_brief(target_file, file_entry, genealogy_data, sim_data):
    """Build the Version C brief for a single file — full 8 types + Version B fields."""
    cross_session = extract_cross_session_data(file_entry)
    cs_counts = count_cross_session_data_points(cross_session)

    return {
        "file": target_file,
        "version": "C",
        # Core 4 (same as A and B)
        "confidence_history": file_entry.get("confidence_history", []),
        "merged_warnings": file_entry.get("merged_warnings", []),
        "genealogy_family": find_genealogy_family(genealogy_data, target_file),
        "code_similarity_top3": find_code_similarity(sim_data, target_file),
        # Version B additions
        "evidence_blocks": generate_rendered_evidence(file_entry, target_file),
        "emotional_trend": build_emotional_trend(file_entry),
        "decision_trajectory": build_decision_trajectory(file_entry),
        # Version C: full 8 cross-session types
        **cross_session,
        "cross_session_data_points": cs_counts,
        # Metadata
        "session_count": file_entry.get("session_count", 0),
        "total_mentions": file_entry.get("total_mentions", 0),
        "sessions_with_data": len(set(
            list(cross_session.get("cross_session_emotional_arc", {}).get("per_session_emotions", {}).keys()) +
            list(cross_session.get("cross_session_synthesis", {}).get("per_session", {}).keys()) +
            list(cross_session.get("cross_session_graph_context", {}).get("per_session", {}).keys())
        )),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Version C: Full 8 cross-session types + Version B fields")
    parser.add_argument("--files", nargs="+", default=DEFAULT_TARGETS,
                       help="Target files to generate briefs for")
    args = parser.parse_args()

    print("=" * 60)
    print("Version C: Full 8 cross-session types + evidence")
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
                "file": target_file, "version": "C",
                "confidence_history": [], "merged_warnings": [],
                "genealogy_family": find_genealogy_family(genealogy_data, target_file),
                "code_similarity_top3": find_code_similarity(sim_data, target_file),
                "evidence_blocks": [], "emotional_trend": [],
                "decision_trajectory": [], "session_count": 0, "total_mentions": 0,
                "sessions_with_data": 0,
                **{k: {} if "arc" in k or "context" in k or "synthesis" in k or "claude_md" in k or "metaphors" in k else [] for k in CROSS_SESSION_KEYS},
                "cross_session_data_points": {k.replace("cross_session_", ""): 0 for k in CROSS_SESSION_KEYS},
            }
            continue

        brief = build_file_brief(target_file, entry, genealogy_data, sim_data)
        briefs[target_file] = brief

        print(f"  sessions: {brief['session_count']} (with data: {brief['sessions_with_data']})")
        print(f"  confidence_history: {len(brief['confidence_history'])} entries")
        print(f"  merged_warnings: {len(brief['merged_warnings'])} warnings")
        print(f"  genealogy: {brief['genealogy_family']['concept'] if brief['genealogy_family'] else 'none'}")
        print(f"  code_similarity: {len(brief['code_similarity_top3'])} matches")
        print(f"  evidence_blocks: {len(brief['evidence_blocks'])} RENDERED blocks")
        print(f"  emotional_trend: {len(brief['emotional_trend'])} entries")
        print(f"  decision_trajectory: {len(brief['decision_trajectory'])} decisions")
        print(f"  Cross-session data points:")
        for k, v in brief['cross_session_data_points'].items():
            if v > 0:
                print(f"    {k}: {v}")
        print()

    # Assemble output
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "feedback_loop/version_c — Full 8 cross-session types + evidence",
        "version": "C",
        "target_files": list(briefs.keys()),
        "briefs": briefs,
    }

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "version_c_briefs.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    size = out_path.stat().st_size
    print(f"Output: {out_path}")
    print(f"Size: {size:,} bytes")


if __name__ == "__main__":
    main()
