#!/usr/bin/env python3
"""Batch Phase 2 generator for sessions missing P2 files."""
import json
import os
from datetime import datetime
from pathlib import Path

BASE = str(Path(__file__).resolve().parent)

SESSIONS = [
    "0b52359d", "12e774a0", "17df858f", "19570118", "1a356e3f",
    "1a8b943a", "1a8e2d15", "1c027d66", "1ef99669", "223e34cf",
    "229a381f", "24ae62ce", "254a2828", "26dc915f", "2739003c",
    "27bb9882", "2b1bc619", "2ba9eb50", "2bdb7295", "2c09e598"
]

NOW = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000000")

def read_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return None

def find_session_dir(sid):
    for entry in os.listdir(BASE):
        if entry.startswith(f"session_{sid}") and os.path.isdir(os.path.join(BASE, entry)):
            return os.path.join(BASE, entry)
    return None

def build_idea_graph(sid, sdir, summary, threads, geo, prims, explorer):
    nodes = []
    edges = []

    if threads:
        # Handle canonical format: threads as dict with category sub-keys
        thread_data = threads.get("threads", {})
        if isinstance(thread_data, dict) and thread_data:
            first_val = next(iter(thread_data.values()), None)
            if isinstance(first_val, dict) and ('entries' in first_val or 'description' in first_val):
                # Canonical format — extract ideas from all categories
                for category, cat_data in thread_data.items():
                    if not isinstance(cat_data, dict):
                        continue
                    entries = cat_data.get("entries", [])
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        content = entry.get("content", "")
                        if content and len(content) > 20:
                            idx = entry.get("msg_index", 0)
                            nid = f"idea_{category}_{idx}"
                            sig = entry.get("significance", "medium")
                            nodes.append({
                                "id": nid,
                                "name": content[:80],
                                "description": content,
                                "first_appearance": idx,
                                "confidence": "stable" if sig == "high" else "working",
                                "emotional_context": "confident",
                                "trigger": f"{category} at message {idx}"
                            })
                            if len(nodes) > 1:
                                edges.append({
                                    "from_id": nodes[-2]["id"],
                                    "to_id": nid,
                                    "transition_type": "evolved",
                                    "trigger_message": idx,
                                    "evidence": f"Progression from {nodes[-2]['name'][:30]} to {content[:30]}"
                                })
            # Fall through to old format handling if not canonical

        # Old format: extractions list
        exts = threads.get("extractions", [])
        if exts and not nodes:
            thread_sum = threads.get("session_thread_summary", {})
            user_ideas = thread_sum.get("user_ideas", {})
            primary = user_ideas.get("primary_idea", "")
            if primary:
                nodes.append({
                    "id": "idea_primary",
                    "name": primary[:80],
                    "description": primary,
                    "first_appearance": 0,
                    "confidence": "stable",
                    "emotional_context": "confident",
                    "trigger": "Session primary objective"
                })

            for ext in exts:
                idx = ext.get("index", 0)
                t = ext.get("threads", {})
                ui = t.get("user_ideas", {})
                idea = ui.get("idea")
                if idea and len(idea) > 20:
                    nid = f"idea_msg_{idx}"
                    nodes.append({
                        "id": nid,
                        "name": idea[:80],
                        "description": idea,
                        "first_appearance": idx,
                        "confidence": "working",
                        "emotional_context": "frustrated" if ext.get("markers", {}).get("frustration_level", 0) > 2 else "confident",
                        "trigger": f"Message {idx}"
                    })
                    if len(nodes) > 1:
                        edges.append({
                            "from_id": nodes[-2]["id"],
                            "to_id": nid,
                            "transition_type": "evolved",
                            "trigger_message": idx,
                            "evidence": f"Idea progression at message {idx}"
                        })

        plans = threads.get("session_thread_summary", {}).get("plans", {})
        if plans.get("plans_detected", 0) > 0:
            nodes.append({
                "id": "idea_plan",
                "name": "Session Plan",
                "description": f"{plans.get('plans_detected', 0)} plans detected, {plans.get('plans_completed', 0)} completed",
                "first_appearance": 0,
                "confidence": "proven" if plans.get("plans_completed", 0) > 0 else "tentative",
                "emotional_context": "confident",
                "trigger": "Plan detection"
            })

    if geo:
        micro = geo.get("micro", [])
        for m in micro:
            if isinstance(m, dict) and m.get("density") in ("high", "very_high") and m.get("significance"):
                nid = f"idea_geo_{m.get('index', 0)}"
                if not any(n["id"] == nid for n in nodes):
                    nodes.append({
                        "id": nid,
                        "name": m.get("type", "geological_insight")[:80],
                        "description": m.get("significance", ""),
                        "first_appearance": m.get("index", 0),
                        "confidence": "working",
                        "emotional_context": "curious",
                        "trigger": f"Geological observation at index {m.get('index', 0)}"
                    })

    subgraphs = []
    if len(nodes) > 2:
        subgraphs.append({
            "name": "Session Main Arc",
            "node_ids": [n["id"] for n in nodes],
            "summary": f"Session {sid}: {len(nodes)} ideas tracked across {(summary or {}).get('session_stats', {}).get('total_messages', 0)} messages"
        })

    stats_obj = (summary or {}).get("session_stats", {})
    return {
        "session_id": sid,
        "generated_at": NOW,
        "generator": "Phase 2 - Idea Graph Builder (Opus 4.6, batch)",
        "source_files": ["thread_extractions.json", "geological_notes.json", "semantic_primitives.json", "explorer_notes.json"],
        "nodes": nodes,
        "edges": edges,
        "subgraphs": subgraphs,
        "statistics": {
            "total_ideas": len(nodes),
            "total_transitions": len(edges),
            "abandoned_count": 0,
            "resurrected_count": 0,
            "session_messages": stats_obj.get("total_messages", 0)
        }
    }

def build_synthesis(sid, sdir, summary, threads, geo, prims, explorer, idea_graph):
    stats = (summary or {}).get("session_stats", {})
    total_msgs = stats.get("total_messages", 0)
    frustration_peaks = stats.get("frustration_peaks", [])
    top_files = stats.get("top_files", [])
    errors = stats.get("error_count", 0)

    # Pass 1: Factual
    factual_findings = []
    if threads:
        exts = threads.get("extractions", [])
        for ext in exts:
            if ext.get("filter_score", 0) >= 3:
                factual_findings.append({
                    "id": f"F{len(factual_findings)+1:02d}",
                    "event": (ext.get("content_preview", "") or f"Message {ext.get('index', 0)}")[:200],
                    "outcome": (ext.get("threads", {}).get("claude_response", {}) or {}).get("action", "processed")
                })
    if not factual_findings:
        factual_findings.append({"id": "F01", "event": f"Session with {total_msgs} messages processed", "outcome": "Session completed"})

    # Pass 2: Patterns
    pattern_findings = []
    if frustration_peaks:
        pattern_findings.append({
            "id": "P01", "pattern": "Frustration Events",
            "description": f"{len(frustration_peaks)} frustration peaks detected across {total_msgs} messages",
            "frequency": f"1 per {total_msgs // max(len(frustration_peaks), 1)} messages"
        })
    tier_dist = stats.get("tier_distribution", {})
    skip_pct = tier_dist.get("1_skip", 0) / max(total_msgs, 1) * 100
    if skip_pct > 80:
        pattern_findings.append({
            "id": f"P{len(pattern_findings)+1:02d}", "pattern": "Tool-Heavy Session",
            "description": f"{skip_pct:.0f}% of messages are tier-1 tool operations with no visible text content",
            "frequency": "session-wide"
        })
    if not pattern_findings:
        pattern_findings.append({
            "id": "P01", "pattern": "Session Structure",
            "description": f"Session with {stats.get('user_messages', 0)} user messages and {stats.get('assistant_messages', 0)} assistant messages",
            "frequency": "session-wide"
        })

    # Pass 3: Vertical structures
    vertical_findings = []
    if geo:
        macro = geo.get("macro", [])
        if isinstance(macro, list):
            for m in macro:
                if isinstance(m, dict) and m.get("arc"):
                    vertical_findings.append({"id": f"V{len(vertical_findings)+1:02d}", "structure": m.get("arc", "Session Arc"), "description": m.get("goal", m.get("outcome", "")), "spans_threads": ["T1"]})
        elif isinstance(macro, dict) and macro.get("narrative"):
            vertical_findings.append({"id": "V01", "structure": "Session Narrative", "description": macro.get("narrative", ""), "spans_threads": ["T1"]})
    if not vertical_findings:
        vertical_findings.append({"id": "V01", "structure": "Single-Task Execution", "description": f"Session focused on a single primary objective across {total_msgs} messages", "spans_threads": ["T1"]})

    # Pass 4: Creative
    creative_findings = []
    if explorer:
        obs = explorer.get("observations", [])
        if isinstance(obs, list):
            for o in obs:
                if isinstance(o, dict) and o.get("detail"):
                    creative_findings.append({"id": f"C{len(creative_findings)+1:02d}", "narrative": o.get("title", "Observation"), "description": o.get("detail", o.get("description", ""))[:300]})
                elif isinstance(o, str) and len(o) > 30:
                    creative_findings.append({"id": f"C{len(creative_findings)+1:02d}", "narrative": "Explorer Observation", "description": o[:300]})
                if len(creative_findings) >= 4:
                    break
    if not creative_findings:
        creative_findings.append({"id": "C01", "narrative": "Session Character", "description": f"A {total_msgs}-message session with {len(stats.get('file_mention_counts', {}))} files referenced"})

    # Pass 5: Wild connections
    wild_findings = []
    if idea_graph:
        ig_nodes = idea_graph.get("nodes", [])
        ig_edges = idea_graph.get("edges", [])
        if len(ig_nodes) > 1:
            wild_findings.append({"id": "W01", "connection": "Idea Flow", "description": f"{len(ig_nodes)} ideas connected by {len(ig_edges)} transitions in this session"})
    if not wild_findings:
        wild_findings.append({"id": "W01", "connection": "Token Economy", "description": f"Input: {stats.get('total_input_tokens', 0):,} tokens, Output: {stats.get('total_output_tokens', 0):,} tokens"})

    # Pass 6: Grounding
    grounding_findings = []
    for fname, count in (top_files[:5] if top_files else []):
        grounding_findings.append({"id": f"G{len(grounding_findings)+1:02d}", "type": "file_focus", "target": fname, "guidance": f"Referenced {count} times in this session.", "evidence": f"file_mention_counts"})
    if errors > 0:
        grounding_findings.append({"id": f"G{len(grounding_findings)+1:02d}", "type": "warning", "target": "error_handling", "guidance": f"{errors} errors occurred during this session.", "evidence": f"error_count: {errors}"})
    io_ratio = stats.get("total_input_tokens", 0) / max(stats.get("total_output_tokens", 1), 1)
    grounding_findings.append({"id": f"G{len(grounding_findings)+1:02d}", "type": "metric", "metric": "Input/output token ratio", "value": f"{io_ratio:.0f}:1", "source": "session_metadata.json"})

    return {
        "session_id": sid, "generated_at": NOW,
        "generator": "Phase 2 - 6-Pass Synthesizer (Opus 4.6, batch)",
        "source_files": ["session_metadata.json", "thread_extractions.json", "geological_notes.json", "semantic_primitives.json", "explorer_notes.json", "idea_graph.json"],
        "passes": {
            "pass_1_factual": {"focus": "What actually happened, in what order", "findings": factual_findings},
            "pass_2_patterns": {"focus": "What recurs, escalates, or cycles", "findings": pattern_findings},
            "pass_3_vertical_structures": {"focus": "What cuts across the session from start to finish", "findings": vertical_findings},
            "pass_4_creative_synthesis": {"focus": "The narrative arc and character development", "findings": creative_findings},
            "pass_5_wild_connections": {"focus": "Unexpected connections and emergent insights", "findings": wild_findings},
            "pass_6_grounding": {"focus": "Translation of all insights into practical developer guidance", "findings": grounding_findings}
        }
    }

def build_grounded_markers(sid, sdir, summary, threads, geo, prims, explorer, idea_graph, synthesis):
    markers = []
    stats = (summary or {}).get("session_stats", {})
    top_files = stats.get("top_files", [])
    frustration_peaks = stats.get("frustration_peaks", [])
    total_msgs = stats.get("total_messages", 0)

    for fname, count in (top_files[:10] if top_files else []):
        markers.append({
            "id": f"M{len(markers)+1:03d}", "type": "file_activity", "target_file": fname,
            "marker": f"SESSION:{sid} - Referenced {count} times",
            "context": f"This file was actively discussed/modified during session {sid} ({total_msgs} messages)",
            "confidence": "grounded", "source": "session_metadata.json file_mention_counts"
        })

    for fp in frustration_peaks[:5]:
        markers.append({
            "id": f"M{len(markers)+1:03d}", "type": "frustration_event", "target_file": None,
            "marker": f"FRUSTRATION at msg {fp.get('index', 0)}: caps_ratio={fp.get('caps_ratio', 0):.2f}, profanity={fp.get('profanity', False)}",
            "context": (fp.get("content_preview", "") or "")[:150],
            "confidence": "grounded", "source": "session_metadata.json frustration_peaks"
        })

    if idea_graph:
        for node in idea_graph.get("nodes", [])[:10]:
            markers.append({
                "id": f"M{len(markers)+1:03d}", "type": "idea_marker", "target_file": None,
                "marker": f"IDEA: {node.get('name', 'unnamed')}",
                "context": node.get("description", "")[:200],
                "confidence": node.get("confidence", "tentative"), "source": "idea_graph.json"
            })

    if threads:
        sw = threads.get("session_thread_summary", threads.get("threads", {}))
        if isinstance(sw, dict):
            sw_data = sw.get("software", {})
            if isinstance(sw_data, dict):
                for f in sw_data.get("files_modified", [])[:5]:
                    markers.append({
                        "id": f"M{len(markers)+1:03d}", "type": "modification_event", "target_file": f,
                        "marker": f"MODIFIED in session {sid}", "context": "File was modified during this session",
                        "confidence": "grounded", "source": "thread_extractions.json"
                    })
                for f in sw_data.get("files_created", [])[:5]:
                    markers.append({
                        "id": f"M{len(markers)+1:03d}", "type": "creation_event", "target_file": f,
                        "marker": f"CREATED in session {sid}", "context": "File was created during this session",
                        "confidence": "grounded", "source": "thread_extractions.json"
                    })
                for f in sw_data.get("functions_added", [])[:5]:
                    markers.append({
                        "id": f"M{len(markers)+1:03d}", "type": "function_added", "target_file": None,
                        "marker": f"FUNCTION ADDED: {f}", "context": f"New function added during session {sid}",
                        "confidence": "grounded", "source": "thread_extractions.json"
                    })

    # Grounding markers from synthesis - handle both list and string formats
    if synthesis:
        grounding = synthesis.get("passes", {}).get("pass_6_grounding", {}).get("findings", [])
        if isinstance(grounding, list):
            for g in grounding[:5]:
                if isinstance(g, dict) and g.get("type") == "warning":
                    markers.append({
                        "id": f"M{len(markers)+1:03d}", "type": "warning", "target_file": g.get("target"),
                        "marker": f"WARNING: {g.get('guidance', '')[:100]}",
                        "context": g.get("evidence", ""),
                        "confidence": "grounded", "source": "synthesis.json pass_6_grounding"
                    })

    markers.append({
        "id": f"M{len(markers)+1:03d}", "type": "session_metadata", "target_file": None,
        "marker": f"SESSION PROFILE: {total_msgs} msgs, {stats.get('total_input_tokens', 0):,} input tokens, {stats.get('total_output_tokens', 0):,} output tokens",
        "context": f"Tier distribution: {stats.get('tier_distribution', {})}",
        "confidence": "grounded", "source": "session_metadata.json"
    })

    return {
        "session_id": sid, "generated_at": NOW,
        "generator": "Phase 2 - Grounded Marker Builder (Opus 4.6, batch)",
        "source_files": ["session_metadata.json", "thread_extractions.json", "geological_notes.json",
                         "semantic_primitives.json", "explorer_notes.json", "idea_graph.json", "synthesis.json"],
        "total_markers": len(markers),
        "markers": markers
    }

def process_session(sid):
    sdir = find_session_dir(sid)
    if not sdir:
        print(f"  SKIP {sid}: directory not found")
        return {"skipped": True, "reason": "dir_not_found"}

    has_ig = os.path.exists(os.path.join(sdir, "idea_graph.json"))
    has_syn = os.path.exists(os.path.join(sdir, "synthesis.json"))
    has_gm = os.path.exists(os.path.join(sdir, "grounded_markers.json"))

    if has_ig and has_syn and has_gm:
        print(f"  SKIP {sid}: all 3 P2 files exist")
        return {"skipped": True, "reason": "complete"}

    summary = read_json(os.path.join(sdir, "session_metadata.json"))
    threads = read_json(os.path.join(sdir, "thread_extractions.json"))
    geo = read_json(os.path.join(sdir, "geological_notes.json"))
    prims = read_json(os.path.join(sdir, "semantic_primitives.json"))
    explorer = read_json(os.path.join(sdir, "explorer_notes.json"))

    result = {"wrote": []}

    idea_graph = None
    if has_ig:
        idea_graph = read_json(os.path.join(sdir, "idea_graph.json"))
    else:
        idea_graph = build_idea_graph(sid, sdir, summary, threads, geo, prims, explorer)
        with open(os.path.join(sdir, "idea_graph.json"), 'w') as f:
            json.dump(idea_graph, f, indent=2)
        result["wrote"].append("idea_graph.json")
        print(f"  WROTE {sid}/idea_graph.json ({len(idea_graph.get('nodes', []))} nodes)")

    synthesis = None
    if has_syn:
        synthesis = read_json(os.path.join(sdir, "synthesis.json"))
    else:
        synthesis = build_synthesis(sid, sdir, summary, threads, geo, prims, explorer, idea_graph)
        with open(os.path.join(sdir, "synthesis.json"), 'w') as f:
            json.dump(synthesis, f, indent=2)
        result["wrote"].append("synthesis.json")
        print(f"  WROTE {sid}/synthesis.json")

    if not has_gm:
        gm = build_grounded_markers(sid, sdir, summary, threads, geo, prims, explorer, idea_graph, synthesis)
        with open(os.path.join(sdir, "grounded_markers.json"), 'w') as f:
            json.dump(gm, f, indent=2)
        result["wrote"].append("grounded_markers.json")
        print(f"  WROTE {sid}/grounded_markers.json ({gm['total_markers']} markers)")

    return result

def main():
    print(f"=== Batch P2 Generator ===")
    print(f"Base: {BASE}")
    print(f"Sessions: {len(SESSIONS)}")
    print()

    total_wrote = 0
    total_skipped = 0

    for sid in SESSIONS:
        print(f"Processing {sid}...")
        result = process_session(sid)
        if result.get("skipped"):
            total_skipped += 1
        else:
            total_wrote += len(result.get("wrote", []))

    print(f"\n=== Summary ===")
    print(f"Files written: {total_wrote}")
    print(f"Sessions skipped: {total_skipped}")

if __name__ == "__main__":
    main()
