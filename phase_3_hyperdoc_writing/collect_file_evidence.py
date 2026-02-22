#!/usr/bin/env python3
"""
Phase 3a: Per-Session File Evidence Collector

For each file mentioned in a session, collects 9 types of evidence from all
10 data sources using time-window correlation (±10 messages around each mention).

Reads per session:
  - session_metadata.json — file mention counts, top_files
  - geological_notes.json — micro/meso/macro observations
  - semantic_primitives.json — tagged messages, distributions
  - explorer_notes.json — observations, verification
  - file_genealogy.json — file families
  - thread_extractions.json — 6 thread categories
  - grounded_markers.json — markers referencing files
  - idea_graph.json — nodes, edges, subgraphs, statistics
  - synthesis.json — 6-pass multi-temperature analysis
  - claude_md_analysis.json — gate analysis, findings, recommendations

Writes per file:
  output/session_XXXX/file_evidence/{safe_filename}_evidence.json

Each evidence JSON has 9 sections:
  1. emotional_arc — primitives from the time window
  2. geological_character — geological observations by name + time overlap
  3. lineage — genealogy links from file_genealogy + idea_graph
  4. explorer_observations — explorer notes referencing the file
  5. chronological_timeline — thread entries + grounded markers
  6. code_similarity — placeholder (populated by Phase 4a aggregation)
  7. graph_context — connected edges, subgraphs, graph statistics (session-level)
  8. synthesis_context — multi-pass analysis passes 1-6 (session-level)
  9. claude_md_context — file analyses, findings, recommendations (session-level)

$0 cost — pure Python, no LLM calls.

Usage:
    python3 phase_3_hyperdoc_writing/collect_file_evidence.py --session 513d4807
    HYPERDOCS_SESSION_ID=513d4807 python3 phase_3_hyperdoc_writing/collect_file_evidence.py
"""
import argparse
import json
import os
import re
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(REPO_ROOT / "output")))
PERM_SESSIONS = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
WINDOW = 10  # Messages before/after a mention to include as context


def load_json(filename, search_dirs):
    """Load JSON from the first directory where the file exists."""
    for d in search_dirs:
        path = d / filename
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
    return {}


def mentions_file(text, filename):
    """Check if text mentions a file (by full name or stem)."""
    if not text or not isinstance(text, str):
        return False
    base = Path(filename).stem
    return filename in text or base in text


def in_window(msg_index, mention_indices, window=WINDOW):
    """Check if a message index is within the window of any mention."""
    for m in mention_indices:
        if m >= 0 and abs(msg_index - m) <= window:
            return True
    return False


def safe_filename(filepath):
    """Convert a filepath to a safe filename for evidence JSON."""
    return filepath.replace("/", "_").replace("\\", "_").replace(".", "_").replace(" ", "_")


def get_all_target_files(session_metadata):
    """Extract all file names from session_metadata."""
    files = set()
    stats = session_metadata.get("session_stats", session_metadata)

    # From top_files: list of [filename, count] pairs
    for item in stats.get("top_files", []):
        if isinstance(item, list) and len(item) >= 1:
            files.add(item[0])
        elif isinstance(item, str):
            files.add(item)

    # From file_mention_counts: dict of {filename: count}
    for fname in stats.get("file_mention_counts", {}):
        files.add(fname)

    # Filter out empty strings
    files.discard("")
    return sorted(files)


def find_mention_indices(target_file, threads_dict, geological_notes, perm_dossier):
    """Find all message indices where a file is mentioned across data sources."""
    mention_indices = set()

    # From thread extractions (handle both dict and list schemas)
    if isinstance(threads_dict, dict):
        for thread_key, thread_val in threads_dict.items():
            if not isinstance(thread_val, dict):
                continue
            for entry in thread_val.get("entries", []):
                content = entry.get("content", "") if isinstance(entry, dict) else ""
                if mentions_file(content, target_file):
                    mention_indices.add(entry.get("msg_index", -1))
    elif isinstance(threads_dict, list):
        for ext in threads_dict:
            if not isinstance(ext, dict):
                continue
            sw = ext.get("threads", {})
            if isinstance(sw, dict):
                for thread_key, entries in sw.items():
                    if isinstance(entries, list):
                        for entry_item in entries:
                            if isinstance(entry_item, dict):
                                if mentions_file(entry_item.get("content", ""), target_file):
                                    mention_indices.add(entry_item.get("msg_index", -1))
                            elif isinstance(entry_item, str) and mentions_file(entry_item, target_file):
                                mention_indices.add(ext.get("msg_index", -1))

    # From dossiers (has first/last mention index)
    for k, v in perm_dossier.get("dossiers", {}).items():
        if not isinstance(v, dict):
            continue
        if v.get("file_name") == target_file or target_file in k:
            for idx_key in ("first_mention_index", "last_mention_index"):
                idx_val = v.get(idx_key)
                if idx_val is not None and isinstance(idx_val, int):
                    mention_indices.add(idx_val)
            for mi in v.get("mentioned_in", []):
                if isinstance(mi, dict):
                    mention_indices.add(mi.get("msg_index", -1))
                elif isinstance(mi, int):
                    mention_indices.add(mi)
            break

    # From geological notes (check all zoom levels)
    for zoom in ["micro", "meso", "macro"]:
        for obs in geological_notes.get(zoom, []):
            text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
            if mentions_file(text, target_file):
                msg_range = obs.get("message_range", []) if isinstance(obs, dict) else []
                if isinstance(msg_range, list) and len(msg_range) == 2:
                    mention_indices.update(range(msg_range[0], msg_range[1] + 1))

    mention_indices.discard(-1)
    return mention_indices


def build_window_indices(mention_indices, window=WINDOW):
    """Build the set of all message indices within WINDOW of any mention."""
    window_indices = set()
    for m in mention_indices:
        for offset in range(-window, window + 1):
            window_indices.add(m + offset)
    return {i for i in window_indices if i >= 0}


def build_emotional_arc(target_file, mention_indices, window_indices, semantic_primitives):
    """Build emotional arc section from semantic primitives in the time window."""
    tagged = semantic_primitives.get("tagged_messages", [])
    distributions = semantic_primitives.get("distributions", {})
    summary_stats = semantic_primitives.get("summary_statistics", {})

    window_emotions = []
    for tm in tagged:
        idx = tm.get("msg_index", -1)
        if idx in window_indices:
            window_emotions.append({
                "msg_index": idx,
                "emotional_tenor": tm.get("emotional_tenor", "unknown"),
                "confidence_signal": tm.get("confidence_signal", "unknown"),
                "action_vector": tm.get("action_vector", "unknown"),
                "intent_marker": tm.get("intent_marker", "unknown"),
                "friction_log": tm.get("friction_log", ""),
                "decision_trace": tm.get("decision_trace", ""),
                "is_direct_mention": idx in mention_indices,
            })

    file_emotion_dist = defaultdict(int)
    for em in window_emotions:
        file_emotion_dist[em["emotional_tenor"]] += 1

    window_emotions.sort(key=lambda x: x["msg_index"])
    emotion_trajectory = [{"idx": e["msg_index"], "emotion": e["emotional_tenor"]}
                         for e in window_emotions]

    return {
        "session_distribution": distributions.get("emotional_tenor", {}),
        "file_window_distribution": dict(file_emotion_dist),
        "emotion_trajectory": emotion_trajectory,
        "session_arc": summary_stats.get("session_arc", ""),
        "dominant_emotion": summary_stats.get("dominant_emotion", ""),
        "friction_episodes": summary_stats.get("friction_episodes", 0),
        "file_nearby_emotions": window_emotions,
        "data_points": len(window_emotions),
    }


def build_geological_character(target_file, mention_indices, geological_notes):
    """Build geological character section from observations matching by name or time window."""
    file_micro = []
    for obs in geological_notes.get("micro", []):
        text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
        msg_range = obs.get("message_range", []) if isinstance(obs, dict) else []
        if mentions_file(text, target_file):
            if isinstance(obs, dict):
                obs = {**obs, "match_reason": "filename"}
            file_micro.append(obs)
        elif isinstance(msg_range, list) and len(msg_range) == 2:
            obs_range = set(range(msg_range[0], msg_range[1] + 1))
            if obs_range & mention_indices:
                if isinstance(obs, dict):
                    obs = {**obs, "match_reason": "time_window"}
                file_micro.append(obs)

    file_meso = []
    for obs in geological_notes.get("meso", []):
        text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
        msg_range = obs.get("message_range", []) if isinstance(obs, dict) else []
        if mentions_file(text, target_file):
            if isinstance(obs, dict):
                obs = {**obs, "match_reason": "filename"}
            file_meso.append(obs)
        elif isinstance(msg_range, list) and len(msg_range) == 2:
            obs_range = set(range(msg_range[0], msg_range[1] + 1))
            if obs_range & mention_indices:
                if isinstance(obs, dict):
                    obs = {**obs, "match_reason": "time_window"}
                file_meso.append(obs)

    file_macro = []
    for obs in geological_notes.get("macro", []):
        text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
        if mentions_file(text, target_file):
            if isinstance(obs, dict):
                obs = {**obs, "match_reason": "filename"}
            file_macro.append(obs)

    file_observations = []
    for obs in geological_notes.get("observations", []):
        text = obs if isinstance(obs, str) else obs.get("observation", "") if isinstance(obs, dict) else str(obs)
        if mentions_file(text, target_file):
            file_observations.append(obs)

    return {
        "micro_observations": file_micro,
        "meso_observations": file_meso,
        "macro_observations": file_macro,
        "standalone_observations": file_observations,
        "geological_metaphor": geological_notes.get("geological_metaphor", ""),
        "data_points": len(file_micro) + len(file_meso) + len(file_macro) + len(file_observations),
    }


def build_lineage(target_file, file_genealogy, idea_graph):
    """Build lineage section from file genealogy and idea graph."""
    families = file_genealogy.get("file_families", [])
    session_family = None
    for fam in families:
        versions = fam.get("versions", fam.get("members", fam.get("files", [])))
        member_names = [v if isinstance(v, str) else v.get("file", "") for v in versions]
        if any(target_file in m for m in member_names):
            session_family = {
                "family_name": fam.get("concept", fam.get("name", "unnamed")),
                "members": member_names,
            }
            break

    lineage_nodes = []
    for node in idea_graph.get("nodes", []):
        if isinstance(node, dict):
            label = node.get("label", node.get("id", ""))
            if mentions_file(label, target_file) or Path(target_file).stem in str(node).lower():
                lineage_nodes.append({
                    "id": node.get("id", ""),
                    "label": label,
                    "state": node.get("state", ""),
                    "confidence": node.get("confidence", ""),
                })

    return {
        "session_family": session_family,
        "idea_graph_lineage_nodes": lineage_nodes,
        "data_points": (1 if session_family else 0) + len(lineage_nodes),
    }


def build_graph_context(target_file, idea_graph):
    """Build graph context section: connected edges, containing subgraphs, and session-level statistics.

    Unlike build_lineage() which extracts nodes for file-level lineage, this captures the
    *relational* structure — how ideas involving this file connect to other ideas, which
    named clusters they belong to, and the overall session graph topology.
    """
    # Step 1: Find nodes that mention this file (same logic as build_lineage)
    file_node_ids = set()
    for node in idea_graph.get("nodes", []):
        if not isinstance(node, dict):
            continue
        label = node.get("label", node.get("id", ""))
        desc = node.get("description", "")
        files_ref = node.get("files_referenced", [])
        searchable = f"{label} {desc} {' '.join(files_ref) if isinstance(files_ref, list) else str(files_ref)}"
        if mentions_file(searchable, target_file):
            file_node_ids.add(node.get("id", ""))

    # Step 2: Find edges connected to those nodes
    connected_edges = []
    for edge in idea_graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        src = edge.get("from", edge.get("from_node", ""))
        tgt = edge.get("to", edge.get("to_node", ""))
        if src in file_node_ids or tgt in file_node_ids:
            connected_edges.append({
                "id": edge.get("id", ""),
                "from": src,
                "to": tgt,
                "type": edge.get("type", edge.get("transition", edge.get("transition_type", ""))),
                "label": edge.get("label", ""),
                "evidence": edge.get("evidence", ""),
            })

    # Step 3: Find subgraphs containing those nodes
    containing_subgraphs = []
    for sg in idea_graph.get("subgraphs", []):
        if not isinstance(sg, dict):
            continue
        sg_node_ids = set(sg.get("node_ids", []))
        if sg_node_ids & file_node_ids:
            containing_subgraphs.append({
                "id": sg.get("id", ""),
                "label": sg.get("label", ""),
                "description": sg.get("description", ""),
                "node_ids": sg.get("node_ids", []),
            })

    # Step 4: Session-level graph statistics (same for all files in the session)
    stats = idea_graph.get("statistics", idea_graph.get("graph_stats", {}))

    return {
        "connected_edges": connected_edges,
        "containing_subgraphs": containing_subgraphs,
        "graph_statistics": stats,
        "file_node_ids": sorted(file_node_ids),
        "data_points": len(connected_edges) + len(containing_subgraphs),
    }


def build_synthesis_context(synthesis):
    """Build synthesis context section from synthesis.json.

    Handles two schema variants:
      Schema A: top-level pass_1_factual, pass_2_patterns, ... keys
      Schema B: nested under a 'passes' dict with same keys inside

    Collects all 6 passes with their sub-keys. Session-level — same for all files.
    Returns empty if all passes have no content.
    """
    pass_keys = [
        ("pass_1_factual", 1, 0.3, "FACTUAL"),
        ("pass_2_patterns", 2, 0.5, "PATTERNS"),
        ("pass_3_vertical_structures", 3, 0.7, "VERTICAL STRUCTURES"),
        ("pass_4_creative_synthesis", 4, 0.9, "CREATIVE SYNTHESIS"),
        ("pass_5_wild_connections", 5, 1.0, "WILD CONNECTIONS"),
        ("pass_6_grounding", 6, 0.0, "GROUNDING"),
    ]

    # Schema B: passes nested inside a 'passes' dict
    passes_container = synthesis.get("passes", {})
    if isinstance(passes_container, dict) and any(k.startswith("pass_") for k in passes_container):
        source = passes_container
    else:
        source = synthesis  # Schema A: top-level keys

    passes = []
    metadata_keys = {"temperature", "label", "description", "focus"}
    for key, num, temp, label in pass_keys:
        pass_data = source.get(key, {})
        if not pass_data or not isinstance(pass_data, dict):
            continue
        # Collect all content sub-keys (facts, patterns, structures, findings, etc.)
        content = {}
        for sub_key, sub_val in pass_data.items():
            if sub_key in metadata_keys:
                continue
            if sub_val:  # skip empty lists/strings/dicts
                content[sub_key] = sub_val
        if content:
            passes.append({
                "pass_number": num,
                "temperature": pass_data.get("temperature", temp),
                "label": pass_data.get("label", pass_data.get("focus", label)),
                "content": content,
            })

    cross_pass = synthesis.get("cross_pass_summary", {})
    key_findings = synthesis.get("key_findings", [])

    return {
        "passes": passes,
        "cross_pass_summary": cross_pass,
        "key_findings": key_findings,
        "session_character": synthesis.get("session_character", ""),
        "data_points": len(passes),
    }


def build_claude_md_context(claude_md_analysis):
    """Build claude_md_context section from claude_md_analysis.json.

    Handles two schema variants:
      Schema A: file_analyses, key_findings_ranked, aggregate_statistics, session_overview
      Schema B: gate_analysis, framing_analysis, claude_md_improvement_recommendations
      Schema C: gate_activations, gates_not_triggered, overall_assessment, behavior_profile

    Collects whatever is available. Session-level context.
    """
    if not claude_md_analysis:
        return {"data_points": 0}

    result = {}

    # Schema A keys
    for key in ("file_analyses", "key_findings_ranked", "aggregate_statistics", "session_overview"):
        val = claude_md_analysis.get(key)
        if val:
            result[key] = val

    # Schema B keys
    for key in ("gate_analysis", "framing_analysis", "claude_md_improvement_recommendations"):
        val = claude_md_analysis.get(key)
        if val:
            result[key] = val

    # Schema C keys
    for key in ("gate_activations", "gates_not_triggered", "overall_assessment", "behavior_profile"):
        val = claude_md_analysis.get(key)
        if val:
            result[key] = val

    # Count meaningful data points
    dp = 0
    dp += len(result.get("file_analyses", {}))
    dp += len(result.get("key_findings_ranked", []))
    dp += len(result.get("gate_analysis", {}))
    dp += len(result.get("gate_activations", []))
    dp += len(result.get("claude_md_improvement_recommendations", []))
    result["data_points"] = dp

    return result


def build_explorer_observations(target_file, explorer_notes):
    """Build explorer observations section."""
    file_explorer_obs = []
    for obs in explorer_notes.get("observations", []):
        text = obs if isinstance(obs, str) else obs.get("observation", "") if isinstance(obs, dict) else str(obs)
        if mentions_file(text, target_file):
            file_explorer_obs.append(obs)

    verification = explorer_notes.get("verification", {})
    file_verification = {}
    for section_key, section_val in verification.items():
        if isinstance(section_val, str) and mentions_file(section_val, target_file):
            file_verification[section_key] = section_val
        elif isinstance(section_val, list):
            matching = [item for item in section_val
                       if mentions_file(str(item), target_file)]
            if matching:
                file_verification[section_key] = matching
        elif isinstance(section_val, dict):
            for sub_key, sub_val in section_val.items():
                if mentions_file(str(sub_val), target_file):
                    file_verification[f"{section_key}.{sub_key}"] = sub_val

    anomalies = []
    for obs in explorer_notes.get("observations", []):
        if isinstance(obs, dict) and obs.get("id", "").startswith("anomaly"):
            if mentions_file(obs.get("observation", ""), target_file):
                anomalies.append(obs)

    explorer_summary = explorer_notes.get("explorer_summary", "")

    return {
        "observations": file_explorer_obs,
        "verification_issues": file_verification,
        "anomalies": anomalies,
        "session_explorer_summary": explorer_summary if mentions_file(explorer_summary, target_file) else "",
        "data_points": len(file_explorer_obs) + len(file_verification) + len(anomalies),
    }


def build_chronological_timeline(target_file, threads_dict, grounded_markers):
    """Build chronological timeline from thread entries and grounded markers."""
    timeline = []

    # From thread extractions (handle both dict and list schemas)
    if isinstance(threads_dict, dict):
        for thread_key, thread_val in threads_dict.items():
            if not isinstance(thread_val, dict):
                continue
            for entry in thread_val.get("entries", []):
                content = entry.get("content", "") if isinstance(entry, dict) else ""
                if mentions_file(content, target_file):
                    timeline.append({
                        "msg_index": entry.get("msg_index", -1),
                        "thread": thread_key,
                        "content": content,
                        "significance": entry.get("significance", ""),
                    })
    elif isinstance(threads_dict, list):
        for ext in threads_dict:
            if not isinstance(ext, dict):
                continue
            sw = ext.get("threads", {})
            if isinstance(sw, dict):
                for thread_key, entries in sw.items():
                    if isinstance(entries, list):
                        for entry_item in entries:
                            if isinstance(entry_item, dict):
                                content = entry_item.get("content", "")
                                if mentions_file(content, target_file):
                                    timeline.append({
                                        "msg_index": entry_item.get("msg_index", ext.get("msg_index", -1)),
                                        "thread": thread_key,
                                        "content": content,
                                        "significance": entry_item.get("significance", ""),
                                    })
                            elif isinstance(entry_item, str) and mentions_file(entry_item, target_file):
                                timeline.append({
                                    "msg_index": ext.get("msg_index", -1),
                                    "thread": thread_key,
                                    "content": entry_item,
                                    "significance": "",
                                })

    # From grounded markers
    markers = grounded_markers.get("markers", [])
    for m in markers:
        if not isinstance(m, dict):
            continue
        marker_text = json.dumps(m)
        if mentions_file(marker_text, target_file):
            timeline.append({
                "msg_index": m.get("msg_index", m.get("first_discovered", -1)),
                "thread": "grounded_marker",
                "content": m.get("claim", m.get("warning", m.get("title", "")))[:500],
                "significance": m.get("severity", m.get("priority", "")),
            })

    timeline.sort(key=lambda x: x.get("msg_index", 0) if isinstance(x.get("msg_index"), int) else 0)

    # Deduplicate by (msg_index, thread) pair
    seen = set()
    deduped = []
    for t in timeline:
        key = (t.get("msg_index"), t.get("thread"))
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    return {
        "events": deduped,
        "data_points": len(deduped),
    }


def collect_evidence_for_file(target_file, session_id, mention_indices, window_indices,
                               semantic_primitives, geological_notes, file_genealogy,
                               idea_graph, explorer_notes, threads_dict, grounded_markers,
                               synthesis, claude_md_analysis):
    """Collect all 9 evidence sections for a single file.

    Sections 1-6: file-level (filtered by name/time window)
    Sections 7-9: session-level context (same for all files in session)
    """
    return {
        "file": target_file,
        "session": session_id,
        "mention_indices": sorted(mention_indices),
        "window_size": WINDOW,
        "emotional_arc": build_emotional_arc(
            target_file, mention_indices, window_indices, semantic_primitives),
        "geological_character": build_geological_character(
            target_file, mention_indices, geological_notes),
        "lineage": build_lineage(target_file, file_genealogy, idea_graph),
        "explorer_observations": build_explorer_observations(target_file, explorer_notes),
        "chronological_timeline": build_chronological_timeline(
            target_file, threads_dict, grounded_markers),
        "code_similarity": {"matches": [], "data_points": 0},
        "graph_context": build_graph_context(target_file, idea_graph),
        "synthesis_context": build_synthesis_context(synthesis),
        "claude_md_context": build_claude_md_context(claude_md_analysis),
    }


def main():
    parser = argparse.ArgumentParser(description="Collect per-file evidence from a session's pipeline outputs.")
    parser.add_argument("--session", default=os.getenv("HYPERDOCS_SESSION_ID", ""),
                       help="Session ID (first 8 chars or full UUID)")
    args = parser.parse_args()

    session_id = args.session[:8] if args.session else ""
    if not session_id:
        print("ERROR: No session ID provided. Use --session or set HYPERDOCS_SESSION_ID.")
        return

    session_dir = OUTPUT_DIR / f"session_{session_id}"
    perm_session_dir = PERM_SESSIONS / f"session_{session_id}"
    search_dirs = [session_dir, perm_session_dir]

    print("=" * 60)
    print(f"Phase 3a: Per-Session File Evidence Collector")
    print(f"  Session: {session_id}")
    print(f"  Output dir: {session_dir}")
    print("=" * 60)

    # Load all data sources
    print("Loading data sources...")
    session_metadata = load_json("session_metadata.json", search_dirs)
    geological_notes = load_json("geological_notes.json", search_dirs)
    semantic_primitives = load_json("semantic_primitives.json", search_dirs)
    explorer_notes = load_json("explorer_notes.json", search_dirs)
    file_genealogy = load_json("file_genealogy.json", search_dirs)
    thread_extractions = load_json("thread_extractions.json", search_dirs)
    idea_graph = load_json("idea_graph.json", search_dirs)
    grounded_markers = load_json("grounded_markers.json", search_dirs)
    synthesis = load_json("synthesis.json", search_dirs)
    claude_md_analysis = load_json("claude_md_analysis.json", search_dirs)
    perm_dossier = load_json("file_dossiers.json", [perm_session_dir, session_dir])

    # Get thread data (handle both dict and list schemas)
    threads_dict = thread_extractions.get("threads", {})

    # Get all target files
    target_files = get_all_target_files(session_metadata)
    if not target_files:
        print("  No files found in session_metadata. Nothing to collect.")
        return

    print(f"  Found {len(target_files)} files to process: {target_files}")

    # Create output directory
    evidence_dir = session_dir / "file_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Process each file
    total_data_points = 0
    files_written = 0

    for target_file in target_files:
        # Step 1: Find mention indices
        mention_indices = find_mention_indices(
            target_file, threads_dict, geological_notes, perm_dossier)

        if not mention_indices:
            # Even without explicit mention indices, collect what we can by name matching
            # Use a synthetic mention at index 0 so the window captures session start
            mention_indices = set()

        # Step 2: Build time window
        window_indices = build_window_indices(mention_indices)

        # Step 3: Collect all 9 evidence sections
        evidence = collect_evidence_for_file(
            target_file, session_id, mention_indices, window_indices,
            semantic_primitives, geological_notes, file_genealogy,
            idea_graph, explorer_notes, threads_dict, grounded_markers,
            synthesis, claude_md_analysis)

        # Count data points
        sections = ["emotional_arc", "geological_character", "lineage",
                    "explorer_observations", "chronological_timeline", "code_similarity",
                    "graph_context", "synthesis_context", "claude_md_context"]
        file_dp = sum(evidence[s].get("data_points", 0) for s in sections)
        total_data_points += file_dp

        # Write evidence JSON
        out_name = f"{safe_filename(target_file)}_evidence.json"
        out_path = evidence_dir / out_name
        with open(out_path, "w") as f:
            json.dump(evidence, f, indent=2, ensure_ascii=False)

        files_written += 1
        print(f"  {target_file}: {file_dp} data points, {len(mention_indices)} mentions → {out_name}")

    print()
    print(f"Evidence collected for {files_written} files")
    print(f"Total data points: {total_data_points}")
    print(f"Output: {evidence_dir}")


if __name__ == "__main__":
    main()
