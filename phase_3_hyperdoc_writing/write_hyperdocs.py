#!/usr/bin/env python3
"""
Agent 8: Hyperdoc Writer
Reads file_dossiers.json and grounded_markers.json to compose hyperdoc comment
blocks for the top 5 files. Writes each block to hyperdoc_blocks/{filename}_hyperdoc.txt.

No metaphors. No poetry. Maximum precision. Zero creativity.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "hyperdoc_blocks"

DOSSIERS_PATH = SCRIPT_DIR / "file_dossiers.json"
MARKERS_PATH = SCRIPT_DIR / "grounded_markers.json"
IDEA_GRAPH_PATH = SCRIPT_DIR / "idea_graph.json"
CLAUDE_MD_PATH = SCRIPT_DIR / "claude_md_analysis.json"

TOP_5_FILES = [
    "unified_orchestrator.py",
    "geological_reader.py",
    "hyperdoc_pipeline.py",
    "story_marker_generator.py",
    "six_thread_extractor.py",
]


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_dossier(dossiers: dict, filename: str) -> dict | None:
    for file_entry in dossiers.get("files", []):
        if file_entry.get("filename") == filename:
            return file_entry
    return None


def get_warnings_for_file(markers: dict, filename: str, dossier: dict) -> list[dict]:
    """Get warnings applicable to this file from grounded_markers."""
    result = []
    dossier_warning_ids = {w["id"] for w in dossier.get("warnings", [])}
    for w in markers.get("warnings", []):
        if w["id"] in dossier_warning_ids:
            result.append(w)
    return result


def get_recommendations_for_file(markers: dict, dossier: dict) -> list[dict]:
    """Get recommendations applicable to this file from grounded_markers."""
    result = []
    dossier_rec_ids = {r["id"] for r in dossier.get("recommendations", [])}
    for r in markers.get("recommendations", []):
        if r["id"] in dossier_rec_ids:
            result.append(r)
    return result


def get_patterns(markers: dict) -> list[dict]:
    return markers.get("patterns", [])


def get_iron_rules(markers: dict) -> list[dict]:
    return markers.get("iron_rules_registry", [])


def get_metrics_for_file(markers: dict, filename: str) -> list[dict]:
    result = []
    for m in markers.get("metrics", []):
        # Include metrics that reference this file or are globally relevant
        metric_text = m.get("metric", "") + " " + m.get("what_it_measures", "")
        if filename.replace(".py", "") in metric_text.lower() or m["id"] in (
            "M01", "M02", "M03", "M05", "M07", "M08", "M11"
        ):
            result.append(m)
    return result


def get_relevant_ideas(idea_graph: dict, dossier: dict) -> list[dict]:
    """Get idea graph nodes relevant to this file's subgraphs."""
    subgraph_names = [sg["name"] for sg in dossier.get("idea_graph_subgraphs", [])]
    subgraphs = idea_graph.get("subgraphs", [])
    relevant_node_ids = set()
    for sg in subgraphs:
        if sg["name"] in subgraph_names:
            relevant_node_ids.update(sg.get("node_ids", []))

    nodes = []
    for node in idea_graph.get("nodes", []):
        if node["id"] in relevant_node_ids:
            nodes.append(node)
    return nodes


def get_relevant_edges(idea_graph: dict, dossier: dict) -> list[dict]:
    """Get idea graph edges relevant to this file's subgraphs."""
    subgraph_names = [sg["name"] for sg in dossier.get("idea_graph_subgraphs", [])]
    subgraphs = idea_graph.get("subgraphs", [])
    relevant_node_ids = set()
    for sg in subgraphs:
        if sg["name"] in subgraph_names:
            relevant_node_ids.update(sg.get("node_ids", []))

    edges = []
    for edge in idea_graph.get("edges", []):
        if edge["from_id"] in relevant_node_ids or edge["to_id"] in relevant_node_ids:
            edges.append(edge)
    return edges


def get_applicable_iron_rules(markers: dict, filename: str, dossier: dict) -> list[dict]:
    """Determine which iron rules apply to this specific file."""
    rules = get_iron_rules(markers)
    applicable = []
    story = dossier.get("story_arc", "").lower()
    warnings = dossier.get("warnings", [])
    warning_ids = {w["id"] for w in warnings}

    for rule in rules:
        rule_text = rule.get("rule", "").lower()
        # Rule 1: import preservation - applies to all files
        if rule["rule_number"] == 1:
            applicable.append(rule)
        # Rule 2: working healthy system - applies to all
        elif rule["rule_number"] == 2:
            applicable.append(rule)
        # Rule 4: never truncate - applies to marker-related files
        elif rule["rule_number"] == 4 and (
            "marker" in filename.lower() or "truncat" in story
        ):
            applicable.append(rule)
        # Rule 5: Opus only - applies to files with LLM calls
        elif rule["rule_number"] == 5 and "W12" in warning_ids:
            applicable.append(rule)
        # Rule 7: No fallbacks - same as rule 5
        elif rule["rule_number"] == 7 and "W12" in warning_ids:
            applicable.append(rule)
        # Rule 8: Conditional Haiku - applies to tiered/LLM files
        elif rule["rule_number"] == 8 and "W12" in warning_ids:
            applicable.append(rule)
    return applicable


def compose_hyperdoc_block(
    filename: str,
    dossier: dict,
    markers: dict,
    idea_graph: dict,
    claude_md: dict,
) -> str:
    """Compose the full hyperdoc comment block for a single file."""
    lines = []

    behavior = dossier.get("claude_behavior", {})
    warnings = get_warnings_for_file(markers, filename, dossier)
    recommendations = get_recommendations_for_file(markers, dossier)
    patterns = get_patterns(markers)
    iron_rules = get_applicable_iron_rules(markers, filename, dossier)
    metrics = get_metrics_for_file(markers, filename)
    ideas = get_relevant_ideas(idea_graph, dossier)
    edges = get_relevant_edges(idea_graph, dossier)
    subgraphs = dossier.get("idea_graph_subgraphs", [])

    # Determine state from confidence field
    confidence = dossier.get("confidence", "unknown")
    state = "fragile" if "fragile" in confidence else (
        "working" if "working" in confidence else (
            "proven" if "proven" in confidence else (
                "stable" if "stable" in confidence else "unknown"
            )
        )
    )

    # Determine emotion from behavior profile
    overconfidence = behavior.get("overconfidence", "")
    authority = behavior.get("authority_response", "")
    if "poor" in behavior.get("impulse_control", ""):
        emotion = "cautious"
    elif "severe" in behavior.get("context_damage", ""):
        emotion = "frustrated"
    elif "good" in authority:
        emotion = "relieved"
    else:
        emotion = "uncertain"

    # Determine intent
    story = dossier.get("story_arc", "")
    if "bug" in story.lower() or "fix" in story.lower():
        intent = "bugfix"
    elif "refactor" in story.lower() or "rewrite" in story.lower():
        intent = "correctness"
    elif "marker" in story.lower() or "generat" in story.lower():
        intent = "feature"
    else:
        intent = "correctness"

    # Edit count from thread_extraction_refs
    refs = dossier.get("thread_extraction_refs", {})
    edit_count = refs.get("times_modified", 0)
    total_mentions = dossier.get("total_mentions", 0)

    # Count failed approaches from idea graph edges (pivoted, abandoned, constrained)
    failed_count = 0
    for edge in edges:
        if edge.get("transition_type") in ("pivoted", "abandoned", "constrained"):
            failed_count += 1

    # Count breakthroughs (concretized, proven ideas)
    breakthrough_count = 0
    for idea in ideas:
        if idea.get("confidence") in ("proven", "working") and idea.get("first_appearance", 0) > 0:
            breakthrough_count += 1

    # =========================================================================
    # SECTION 1: @ctx HEADER
    # =========================================================================
    lines.append(f"# ===========================================================================")
    lines.append(f"# HYPERDOC BLOCK: {filename}")
    lines.append(f"# Session: {SESSION_ID} | Generated: {datetime.utcnow().strftime('%Y-%m-%d')}")
    lines.append(f"# ===========================================================================")
    lines.append(f"#")
    lines.append(f"# @ctx:state={state} @ctx:confidence={confidence} @ctx:emotion={emotion}")
    lines.append(f"# @ctx:intent={intent} @ctx:updated=2026-02-05")
    lines.append(f"# @ctx:edits={edit_count} @ctx:total_mentions={total_mentions} @ctx:failed_approaches={failed_count} @ctx:breakthroughs={breakthrough_count}")
    lines.append(f"#")

    # =========================================================================
    # SECTION: STORY ARC
    # =========================================================================
    lines.append(f"# --- STORY ARC ---")
    for story_line in _wrap_comment(story, 95):
        lines.append(story_line)
    lines.append(f"#")

    # =========================================================================
    # SECTION 2: FRICTION
    # =========================================================================
    lines.append(f"# --- FRICTION: WHAT WENT WRONG AND WHY ---")

    friction_items = _build_friction(filename, dossier, warnings, ideas, edges)
    for item in friction_items:
        lines.append(f"#")
        lines.append(f"# @ctx:friction=\"{item['summary']}\"")
        lines.append(f"# @ctx:trace={SESSION_ID}:msg{item['msg_ref']}")
        for detail_line in _wrap_comment(item["detail"], 95):
            lines.append(detail_line)
    lines.append(f"#")

    # =========================================================================
    # SECTION 3: DECISIONS
    # =========================================================================
    lines.append(f"# --- DECISIONS: WHAT WAS CHOSEN AND WHY ---")

    decisions = dossier.get("key_decisions", [])
    for i, decision in enumerate(decisions):
        lines.append(f"#")
        lines.append(f"# @ctx:decision=\"{decision}\"")
    lines.append(f"#")

    # Add relevant idea graph decisions (edges with decision traces)
    relevant_decision_edges = [
        e for e in edges
        if e.get("evidence") and ("chose" in e.get("evidence", "").lower() or "decision" in e.get("evidence", "").lower())
    ]
    if relevant_decision_edges:
        lines.append(f"# Idea graph decision traces:")
        for edge in relevant_decision_edges:
            lines.append(f"#   [{edge['from_id']} -> {edge['to_id']}] ({edge['transition_type']}, msg {edge.get('trigger_message', '?')})")
            for evidence_line in _wrap_comment(edge.get("evidence", ""), 91, prefix="#     "):
                lines.append(evidence_line)
        lines.append(f"#")

    # =========================================================================
    # SECTION 4: WARNINGS
    # =========================================================================
    lines.append(f"# --- WARNINGS: WHAT A FUTURE CLAUDE SHOULD WATCH FOR ---")

    for w in warnings:
        lines.append(f"#")
        lines.append(f"# @ctx:warning=\"[{w['id']}] [{w['severity'].upper()}] {w['warning']}\"")
        lines.append(f"# @ctx:trace={SESSION_ID}:msg{w.get('first_discovered', '?')}")
        if w.get("resolution_index"):
            lines.append(f"#   Resolution at: msg {w['resolution_index']}")
        else:
            lines.append(f"#   Resolution: UNRESOLVED -- this problem may still exist")
        lines.append(f"#   Evidence: {w.get('evidence', 'see dossier')}")
    lines.append(f"#")

    # Iron rules
    if iron_rules:
        lines.append(f"# --- IRON RULES APPLICABLE TO THIS FILE ---")
        for rule in iron_rules:
            status = rule.get("status", "active")
            lines.append(f"#")
            lines.append(f"# @ctx:iron_rule={rule['rule_number']} \"{rule['rule']}\"")
            lines.append(f"#   Established at: msg {rule.get('established_at', '?')} | Status: {status}")
            lines.append(f"#   Evidence: {rule.get('evidence', 'N/A')}")
        lines.append(f"#")

    # =========================================================================
    # SECTION 5: CLAUDE BEHAVIOR
    # =========================================================================
    lines.append(f"# --- CLAUDE BEHAVIOR: PATTERNS OBSERVED ON THIS FILE ---")
    lines.append(f"#")
    lines.append(f"# @ctx:claude_pattern=\"impulse_control: {behavior.get('impulse_control', 'unknown')}\"")
    lines.append(f"# @ctx:claude_pattern=\"authority_response: {behavior.get('authority_response', 'unknown')}\"")
    lines.append(f"# @ctx:claude_pattern=\"overconfidence: {behavior.get('overconfidence', 'unknown')}\"")
    lines.append(f"# @ctx:claude_pattern=\"context_damage: {behavior.get('context_damage', 'unknown')}\"")
    lines.append(f"#")

    # Add globally relevant behavioral patterns from grounded_markers
    relevant_patterns = _get_relevant_patterns(patterns, filename, dossier)
    if relevant_patterns:
        lines.append(f"# Session-wide behavioral patterns relevant to this file:")
        for p in relevant_patterns:
            lines.append(f"#")
            lines.append(f"# @ctx:claude_pattern=\"[{p['id']}] {p['pattern']}\"")
            lines.append(f"#   Frequency: {p.get('frequency', 'unknown')}")
            lines.append(f"#   Action: {p.get('action', 'N/A')}")
        lines.append(f"#")

    # =========================================================================
    # SECTION 6: EMOTIONAL CONTEXT
    # =========================================================================
    lines.append(f"# --- EMOTIONAL CONTEXT: USER REACTIONS AND FRUSTRATION PEAKS ---")
    lines.append(f"#")

    emotional_ideas = [
        idea for idea in ideas
        if idea.get("emotional_context") and (
            "frustrat" in idea.get("emotional_context", "").lower()
            or "volcanic" in idea.get("emotional_context", "").lower()
            or "eruption" in idea.get("emotional_context", "").lower()
            or "crisis" in idea.get("emotional_context", "").lower()
            or "anger" in idea.get("emotional_context", "").lower()
            or "devastat" in idea.get("emotional_context", "").lower()
            or "chastened" in idea.get("emotional_context", "").lower()
            or "premature" in idea.get("emotional_context", "").lower()
        )
    ]

    if emotional_ideas:
        for idea in emotional_ideas:
            lines.append(f"# [{idea['id']}] (msg {idea.get('first_appearance', '?')}): {idea.get('emotional_context', '')}")
        lines.append(f"#")

    # Add specific emotional peaks from iron rules
    emotional_rules = [r for r in iron_rules if r.get("caps_ratio", 0) > 0.3]
    if emotional_rules:
        lines.append(f"# Iron rules established through frustration (caps_ratio > 0.3 indicates shouting):")
        for rule in emotional_rules:
            lines.append(f"#   Rule {rule['rule_number']}: caps_ratio={rule.get('caps_ratio', 0)} | \"{rule.get('evidence', '')}\"")
        lines.append(f"#")

    # =========================================================================
    # SECTION 7: FAILED APPROACHES
    # =========================================================================
    lines.append(f"# --- FAILED APPROACHES: WHAT WAS TRIED AND DID NOT WORK ---")
    lines.append(f"#")

    failed_edges = [
        e for e in edges
        if e.get("transition_type") in ("pivoted", "abandoned", "constrained")
    ]

    if failed_edges:
        for edge in failed_edges:
            lines.append(f"# [{edge['transition_type'].upper()}] {edge['from_id']} -> {edge['to_id']} (msg {edge.get('trigger_message', '?')})")
            for ev_line in _wrap_comment(edge.get("evidence", ""), 91, prefix="#   "):
                lines.append(ev_line)
        lines.append(f"#")
    else:
        lines.append(f"# No failed approaches directly recorded in the idea graph for this file's subgraphs.")
        lines.append(f"#")

    # =========================================================================
    # SECTION 8: RECOMMENDATIONS
    # =========================================================================
    lines.append(f"# --- RECOMMENDATIONS FOR FUTURE SESSIONS ---")
    lines.append(f"#")

    for rec in recommendations:
        lines.append(f"# [{rec['id']}] (priority: {rec.get('priority', 'unknown')})")
        for rec_line in _wrap_comment(rec.get("recommendation", ""), 91, prefix="#   "):
            lines.append(rec_line)
        lines.append(f"#   Evidence: {rec.get('evidence', 'N/A')}")
        lines.append(f"#")

    # =========================================================================
    # SECTION 9: METRICS
    # =========================================================================
    if metrics:
        lines.append(f"# --- RELEVANT METRICS ---")
        lines.append(f"#")
        for m in metrics:
            lines.append(f"# [{m['id']}] {m.get('metric', '')}: {m.get('value', '')}")
            lines.append(f"#   Measures: {m.get('what_it_measures', '')}")
        lines.append(f"#")

    # =========================================================================
    # SECTION 10: RELATED FILES
    # =========================================================================
    related = dossier.get("related_files", [])
    if related:
        lines.append(f"# --- RELATED FILES ---")
        lines.append(f"#")
        for rf in related:
            lines.append(f"# - {rf}")
        lines.append(f"#")

    # =========================================================================
    # SECTION 11: IDEA GRAPH SUBGRAPHS
    # =========================================================================
    if subgraphs:
        lines.append(f"# --- IDEA GRAPH SUBGRAPHS THIS FILE PARTICIPATES IN ---")
        lines.append(f"#")
        for sg in subgraphs:
            lines.append(f"# [{sg['name']}] ({sg.get('node_count', '?')} nodes)")
            for sg_line in _wrap_comment(sg.get("summary", ""), 91, prefix="#   "):
                lines.append(sg_line)
            lines.append(f"#")

    lines.append(f"# ===========================================================================")
    lines.append(f"# END HYPERDOC BLOCK: {filename}")
    lines.append(f"# ===========================================================================")

    return "\n".join(lines) + "\n"


def _build_friction(
    filename: str,
    dossier: dict,
    warnings: list[dict],
    ideas: list[dict],
    edges: list[dict],
) -> list[dict]:
    """Build friction items from warnings, ideas, and edges."""
    friction = []

    # Friction from critical/high warnings
    for w in warnings:
        if w.get("severity") in ("critical", "high"):
            friction.append({
                "summary": w.get("warning", "")[:200],
                "msg_ref": str(w.get("first_discovered", "?")),
                "detail": f"[{w['id']}] Full warning: {w.get('warning', '')} Evidence: {w.get('evidence', 'N/A')}",
            })

    # Friction from pivoted/abandoned/constrained edges
    for edge in edges:
        if edge.get("transition_type") in ("pivoted", "abandoned", "constrained"):
            friction.append({
                "summary": f"{edge['transition_type']}: {edge['from_id']} -> {edge['to_id']}",
                "msg_ref": str(edge.get("trigger_message", "?")),
                "detail": edge.get("evidence", ""),
            })

    # Friction from ideas with 'fragile' confidence
    for idea in ideas:
        if idea.get("confidence") == "fragile":
            friction.append({
                "summary": f"Fragile idea: {idea.get('name', '')}",
                "msg_ref": str(idea.get("first_appearance", "?")),
                "detail": f"{idea.get('description', '')} Emotional context: {idea.get('emotional_context', '')}",
            })

    return friction


def _get_relevant_patterns(
    patterns: list[dict], filename: str, dossier: dict
) -> list[dict]:
    """Filter behavioral patterns relevant to this specific file."""
    relevant = []
    behavior = dossier.get("claude_behavior", {})
    story = dossier.get("story_arc", "").lower()

    for p in patterns:
        pid = p.get("id", "")
        # B01 (agreement without change) - relevant to all high-churn files
        if pid == "B01" and dossier.get("total_mentions", 0) >= 15:
            relevant.append(p)
        # B02 (premature victory) - relevant to files with overconfidence
        elif pid == "B02" and "high" in behavior.get("overconfidence", ""):
            relevant.append(p)
        # B04 (cost optimization) - relevant to geological_reader (cost bug)
        elif pid == "B04" and "expensive" in story:
            relevant.append(p)
        # B05 (context reset violations) - relevant to files with severe context damage
        elif pid == "B05" and "severe" in behavior.get("context_damage", ""):
            relevant.append(p)
        # B06 (create new instead of check existing) - relevant to pipeline files
        elif pid == "B06" and "pipeline" in filename.lower():
            relevant.append(p)
        # B07 (frustration to improvement) - relevant to all top-5 files
        elif pid == "B07":
            relevant.append(p)
        # B08 (exploration ratio) - relevant to orchestrator
        elif pid == "B08" and "orchestrator" in filename.lower():
            relevant.append(p)
    return relevant


def _wrap_comment(text: str, max_width: int = 95, prefix: str = "#   ") -> list[str]:
    """Wrap text into comment lines with given prefix."""
    if not text:
        return [prefix.rstrip()]

    words = text.split()
    lines = []
    current_line = prefix

    for word in words:
        test = current_line + (" " if current_line != prefix else "") + word
        if len(test) > max_width and current_line != prefix:
            lines.append(current_line)
            current_line = prefix + word
        else:
            if current_line == prefix:
                current_line = prefix + word
            else:
                current_line += " " + word

    if current_line.strip():
        lines.append(current_line)

    return lines


def main():
    print(f"[write_hyperdocs] Loading input files...")

    dossiers = load_json(DOSSIERS_PATH)
    markers = load_json(MARKERS_PATH)
    idea_graph = load_json(IDEA_GRAPH_PATH)
    claude_md = load_json(CLAUDE_MD_PATH)

    print(f"[write_hyperdocs] Loaded {len(dossiers.get('files', []))} file dossiers")
    print(f"[write_hyperdocs] Loaded {len(markers.get('warnings', []))} warnings, {len(markers.get('patterns', []))} patterns")
    print(f"[write_hyperdocs] Loaded {len(idea_graph.get('nodes', []))} idea nodes, {len(idea_graph.get('edges', []))} edges")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[write_hyperdocs] Output directory: {OUTPUT_DIR}")

    files_written = 0

    for filename in TOP_5_FILES:
        print(f"\n[write_hyperdocs] Processing: {filename}")

        dossier = get_dossier(dossiers, filename)
        if dossier is None:
            print(f"  WARNING: No dossier found for {filename}, skipping.")
            continue

        block = compose_hyperdoc_block(filename, dossier, markers, idea_graph, claude_md)

        output_path = OUTPUT_DIR / f"{filename.replace('.py', '')}_hyperdoc.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(block)

        line_count = block.count("\n")
        print(f"  Written: {output_path.name} ({line_count} lines)")
        files_written += 1

    print(f"\n[write_hyperdocs] Done. {files_written} hyperdoc blocks written to {OUTPUT_DIR}")

    # Verification
    print(f"\n[write_hyperdocs] Verification:")
    for filename in TOP_5_FILES:
        out_name = f"{filename.replace('.py', '')}_hyperdoc.txt"
        out_path = OUTPUT_DIR / out_name
        if out_path.exists():
            size = out_path.stat().st_size
            with open(out_path, "r") as f:
                lines = f.readlines()
            print(f"  OK: {out_name} ({len(lines)} lines, {size} bytes)")
        else:
            print(f"  MISSING: {out_name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
