#!/usr/bin/env python3
"""Generate a comprehensive HTML viewer for all pipeline outputs."""
import argparse
import json
import os
import html
import sys
from pathlib import Path

# ── Resolve session directory ─────────────────────────────────
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--session", default=None, help="Session ID to process")
_args, _ = _parser.parse_known_args()

if _args.session:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from config import OUTPUT_DIR
    except ImportError:
        OUTPUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(Path(__file__).resolve().parent.parent / "output")))
    BASE = OUTPUT_DIR / f"session_{_args.session[:8]}"
    if not BASE.exists():
        print(f"ERROR: Session directory not found: {BASE}")
        sys.exit(1)
else:
    BASE = Path(__file__).parent

def load(name):
    p = BASE / name
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)

def esc(s):
    return html.escape(str(s)) if s else ""

def load_text(name):
    p = BASE / "hyperdoc_blocks" / name
    if p.exists():
        return p.read_text()
    return "(not found)"

# Load all data
summary = load("session_metadata.json")
threads_raw = load("thread_extractions.json")
geo = load("geological_notes.json")
prims = load("semantic_primitives.json")
explorer = load("explorer_notes.json")
graph = load("idea_graph.json")
synthesis = load("synthesis.json")
markers_raw = load("grounded_markers.json")
dossiers = load("file_dossiers.json")
claude_md = load("claude_md_analysis.json")

stats = summary.get("session_stats", {})

# ---------------------------------------------------------------------------
# Normalize thread_extractions.json
# Canonical: {"threads": {category: {"description": ..., "entries": [...]}}}
# Old reference: {"total_analyzed": N, "narrative_arc": {...}, "extractions": [...], ...}
# ---------------------------------------------------------------------------
threads_dict = threads_raw.get("threads", {})
if isinstance(threads_dict, dict):
    # Canonical format — threads is a dict of categories
    # Compute total_analyzed from entry counts
    threads_total_analyzed = sum(
        len(cat_data.get("entries", []))
        for cat_data in threads_dict.values()
        if isinstance(cat_data, dict)
    )
    # Collect all entries across categories for marker counting
    threads_all_entries = []
    for cat_data in threads_dict.values():
        if isinstance(cat_data, dict):
            threads_all_entries.extend(cat_data.get("entries", []))
else:
    # Unknown structure — fall back to empty
    threads_total_analyzed = 0
    threads_all_entries = []

# Old-format fields (may exist in reference sessions, absent in canonical)
threads_narrative_arc = threads_raw.get("narrative_arc", {})
threads_behavior_patterns = threads_raw.get("claude_behavior_patterns", [])
threads_crisis_moments = threads_raw.get("key_crisis_moments", [])
threads_extractions = threads_raw.get("extractions", [])
# Use total_analyzed from old format if present, otherwise computed value
threads_total_analyzed = threads_raw.get("total_analyzed", threads_total_analyzed)

# ---------------------------------------------------------------------------
# Normalize geological_notes.json
# Canonical meso: {"observation": ..., "message_range": ..., "pattern": ...}
# Old reference meso: {"window": [...], "description": ..., "pattern": ...}
# Canonical macro: {"observation": ..., "scope": ..., "significance": ...}
# Old reference macro: {"arc_name": ..., "window": [...], "goal": ..., "outcome": ..., "fault_lines": [...]}
# ---------------------------------------------------------------------------
geo_micro = geo.get("micro", [])
geo_meso = geo.get("meso", [])
geo_macro = geo.get("macro", [])
geo_recurring = geo.get("recurring_patterns", {})

# ---------------------------------------------------------------------------
# Normalize semantic_primitives.json
# Canonical: {"tagged_messages": [...], "distributions": {...}}
# Old reference: {"total_tagged": N, "distributions": {...}}
# ---------------------------------------------------------------------------
prims_tagged = prims.get("tagged_messages", [])
prims_total_tagged = prims.get("total_tagged", len(prims_tagged))
prims_distributions = prims.get("distributions", {})

# ---------------------------------------------------------------------------
# Normalize explorer_notes.json
# Canonical: {"observations": [...], "verification": {...}, "explorer_summary": "..."}
# Old reference: {"what_matters_most": ..., "observations": [...], "warnings": [...],
#   "patterns": [...], "abandoned_ideas": [...], "emotional_dynamics": [...],
#   "surprises": [...], "free_notes": "..."}
# ---------------------------------------------------------------------------
explorer_observations = explorer.get("observations", [])
explorer_verification = explorer.get("verification", {})
explorer_summary_text = explorer.get("explorer_summary", "")
# Old format fields — absent in canonical, empty fallbacks
explorer_what_matters = explorer.get("what_matters_most", "")
explorer_warnings = explorer.get("warnings", [])
explorer_patterns = explorer.get("patterns", [])
explorer_abandoned = explorer.get("abandoned_ideas", [])
explorer_emotional = explorer.get("emotional_dynamics", [])
explorer_surprises = explorer.get("surprises", [])
explorer_free_notes = explorer.get("free_notes", "")

# ---------------------------------------------------------------------------
# Normalize idea_graph.json
# Canonical: {"nodes": [...], "edges": [...], "metadata": {...}}
#   node: {id, label, description, message_index, confidence, maturity, source}
# Old reference: {"nodes": [...], "edges": [...], "statistics": {...}, "subgraphs": [...]}
#   node: {name, description, confidence, first_appearance, ...}
# ---------------------------------------------------------------------------
graph_nodes = graph.get("nodes", [])
graph_edges = graph.get("edges", [])
# "metadata" is canonical, "statistics" is old reference
graph_meta = graph.get("metadata", graph.get("statistics", {}))
graph_subgraphs = graph.get("subgraphs", [])

# ---------------------------------------------------------------------------
# Normalize synthesis.json
# Canonical: {"passes": {"pass_1_analytical": {"temperature": ..., "label": ..., "content": ...}, ...}}
# Old reference: {"passes": [{"pass_number": N, "focus": ..., "temperature": ..., "findings": {...}}, ...]}
# ---------------------------------------------------------------------------
synthesis_passes_raw = synthesis.get("passes", {})
synthesis_passes_list = []  # Normalized to a list for rendering
if isinstance(synthesis_passes_raw, dict):
    # Canonical dict format — convert to ordered list
    for pass_key in sorted(synthesis_passes_raw.keys()):
        pass_data = synthesis_passes_raw[pass_key]
        if isinstance(pass_data, dict):
            synthesis_passes_list.append({
                "pass_key": pass_key,
                "label": pass_data.get("label", pass_key),
                "temperature": pass_data.get("temperature", "?"),
                "content": pass_data.get("content", ""),
                # Old fields (may be absent)
                "findings": pass_data.get("findings", {}),
            })
elif isinstance(synthesis_passes_raw, list):
    # Old reference list format
    for p in synthesis_passes_raw:
        if isinstance(p, dict):
            synthesis_passes_list.append({
                "pass_key": f"pass_{p.get('pass_number', '?')}",
                "label": p.get("focus", f"Pass {p.get('pass_number', '?')}"),
                "temperature": p.get("temperature", "?"),
                "content": p.get("content", ""),
                "findings": p.get("findings", {}),
            })
synthesis_key_findings = synthesis.get("key_findings", [])
synthesis_session_char = synthesis.get("session_character", "")

# ---------------------------------------------------------------------------
# Normalize grounded_markers.json
# Canonical: {"markers": [{"marker_id": ..., "category": ..., "claim": ...,
#   "evidence": ..., "confidence": ..., "actionable_guidance": ...}]}
# Old reference: {"iron_rules_registry": [...], "warnings": [...], "patterns": [...],
#   "recommendations": [...], "metrics": [...]}
# ---------------------------------------------------------------------------
markers_flat = markers_raw.get("markers", [])
# Old format fields — absent in canonical, empty fallbacks
markers_iron_rules = markers_raw.get("iron_rules_registry", [])
markers_warnings = markers_raw.get("warnings", [])
markers_patterns = markers_raw.get("patterns", [])
markers_recommendations = markers_raw.get("recommendations", [])
markers_metrics = markers_raw.get("metrics", [])

# Hyperdoc blocks
hyperdoc_files = [
    "unified_orchestrator_hyperdoc.txt",
    "geological_reader_hyperdoc.txt",
    "hyperdoc_pipeline_hyperdoc.txt",
    "story_marker_generator_hyperdoc.txt",
    "six_thread_extractor_hyperdoc.txt",
]

# Build HTML
parts = []
parts.append("""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Hyperdocs Pipeline Output</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'SF Mono','Menlo',monospace;background:#0a0a0f;color:#c8c8d0;line-height:1.5}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:24px 32px;border-bottom:2px solid #e94560}
.header h1{font-size:22px;color:#e94560;margin-bottom:8px}
.header .sub{color:#888;font-size:13px}
.stats-bar{display:flex;gap:16px;margin-top:12px;flex-wrap:wrap}
.stat{background:#0f3460;padding:8px 16px;border-radius:6px;font-size:12px}
.stat b{color:#e94560;font-size:16px;display:block}
.tabs{display:flex;background:#111;border-bottom:1px solid #333;overflow-x:auto;flex-wrap:nowrap}
.tab{padding:10px 18px;cursor:pointer;color:#888;font-size:12px;white-space:nowrap;border-bottom:2px solid transparent;transition:all .2s}
.tab:hover{color:#ccc;background:#1a1a2e}
.tab.active{color:#e94560;border-bottom-color:#e94560;background:#1a1a2e}
.panel{display:none;padding:24px 32px;max-width:1200px}
.panel.active{display:block}
h2{color:#e94560;font-size:18px;margin:16px 0 8px;border-bottom:1px solid #333;padding-bottom:4px}
h3{color:#53a8b6;font-size:14px;margin:12px 0 4px}
.card{background:#111;border:1px solid #222;border-radius:8px;padding:16px;margin:8px 0}
.card.warn{border-left:3px solid #e94560}
.card.info{border-left:3px solid #53a8b6}
.card.success{border-left:3px solid #4ecca3}
.card.metric{border-left:3px solid #ffd369}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px}
.tag-high{background:#e94560;color:#fff}
.tag-medium{background:#ffd369;color:#000}
.tag-low{background:#4ecca3;color:#000}
.tag-critical{background:#ff0040;color:#fff}
.tag-parked{background:#555;color:#ccc}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:13px}
th{text-align:left;padding:6px 10px;background:#1a1a2e;color:#e94560;border-bottom:2px solid #333}
td{padding:6px 10px;border-bottom:1px solid #222}
tr:hover td{background:#111}
pre{background:#0a0a0f;border:1px solid #333;padding:12px;overflow-x:auto;font-size:12px;line-height:1.6;border-radius:4px;max-height:600px;overflow-y:auto;white-space:pre-wrap;word-wrap:break-word}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.node{background:#111;border:1px solid #333;padding:10px;border-radius:6px;font-size:12px}
.node .name{color:#53a8b6;font-weight:bold}
.edge{font-size:11px;color:#888;padding:2px 0}
.iron{background:#1a0a0a;border:1px solid #e94560;padding:10px;border-radius:6px;margin:6px 0}
.iron b{color:#e94560}
.iron .caps{color:#ffd369;font-size:11px}
.search{padding:8px 12px;background:#111;border:1px solid #333;color:#c8c8d0;width:100%;margin:8px 0;border-radius:4px;font-family:inherit}
</style></head><body>
""")

# Header
total_msgs = stats.get('total_messages', 0)
user_msgs = stats.get('user_messages', 0)
assistant_msgs = stats.get('assistant_messages', 0)
frustration_count = len(stats.get('frustration_peaks', []))
emergency_count = len(stats.get('emergency_interventions', []))
unique_files_count = len(stats.get('file_mention_counts', {}))
input_tokens = stats.get('total_input_tokens', 0)
parts.append(f"""<div class="header">
<h1>Hyperdocs Multi-Agent Extraction Pipeline</h1>
<div class="sub">{total_msgs} messages | {user_msgs} user / {assistant_msgs} assistant</div>
<div class="stats-bar">
<div class="stat"><b>{total_msgs}</b>Messages</div>
<div class="stat"><b>{frustration_count}</b>Frustration Peaks</div>
<div class="stat"><b>{emergency_count}</b>Emergency Interventions</div>
<div class="stat"><b>{unique_files_count}</b>Unique Files</div>
<div class="stat"><b>{input_tokens:,}</b>Input Tokens</div>
<div class="stat"><b>{threads_total_analyzed}</b>Extractions</div>
<div class="stat"><b>{len(graph_nodes)}</b>Idea Nodes</div>
<div class="stat"><b>{len(graph_edges)}</b>Transitions</div>
</div></div>
""")

# Tabs
tab_names = ["Overview","Threads","Geological","Primitives","Explorer","Idea Graph","Synthesis","Grounded Markers","File Dossiers","CLAUDE.md","Hyperdoc Blocks"]
parts.append('<div class="tabs">')
for i, t in enumerate(tab_names):
    cls = "tab active" if i == 0 else "tab"
    parts.append(f'<div class="{cls}" onclick="showTab({i})">{t}</div>')
parts.append('</div>')

# Panel 0: Overview
parts.append('<div class="panel active" id="p0">')
parts.append("<h2>Pipeline Overview</h2>")
parts.append(f"""<table><tr><th>Phase</th><th>Agent</th><th>Output</th><th>Size</th></tr>
<tr><td>0</td><td>Deterministic Prep</td><td>enriched_session.json</td><td>8.5 MB</td></tr>
<tr><td>1</td><td>Thread Analyst</td><td>thread_extractions.json</td><td>479 KB</td></tr>
<tr><td>1</td><td>Geological Reader</td><td>geological_notes.json</td><td>37 KB</td></tr>
<tr><td>1</td><td>Primitives Tagger</td><td>semantic_primitives.json</td><td>185 KB</td></tr>
<tr><td>1</td><td>Free Explorer</td><td>explorer_notes.json</td><td>22 KB</td></tr>
<tr><td>2</td><td>Idea Graph Builder</td><td>idea_graph.json</td><td>58 KB</td></tr>
<tr><td>2</td><td>6-Pass Synthesizer</td><td>synthesis.json + grounded_markers.json</td><td>77 KB</td></tr>
<tr><td>3</td><td>File Mapper</td><td>file_dossiers.json + claude_md_analysis.json</td><td>69 KB</td></tr>
<tr><td>3</td><td>Hyperdoc Writer</td><td>5 hyperdoc blocks</td><td>74 KB</td></tr>
</table>""")
parts.append("<h2>Tier Distribution</h2>")
td = stats.get("tier_distribution", {})
if td and total_msgs > 0:
    parts.append("<table><tr><th>Tier</th><th>Count</th><th>%</th></tr>")
    for tier_key, tier_label in [("1_skip", "1 (Skip)"), ("2_basic", "2 (Basic)"), ("3_standard", "3 (Standard)"), ("4_priority", "4 (Priority)")]:
        count = td.get(tier_key, 0)
        pct = count / total_msgs * 100 if total_msgs else 0
        parts.append(f"<tr><td>{tier_label}</td><td>{count}</td><td>{pct:.0f}%</td></tr>")
    parts.append("</table>")
else:
    parts.append('<div class="card info">No tier distribution data available</div>')
parts.append("<h2>Top Files by Mention Count</h2><table><tr><th>#</th><th>File</th><th>Mentions</th></tr>")
for i, (f, c) in enumerate(stats.get("top_files", [])[:15], 1):
    parts.append(f"<tr><td>{i}</td><td>{esc(f)}</td><td>{c}</td></tr>")
parts.append("</table></div>")

# Panel 1: Threads
parts.append('<div class="panel" id="p1">')
parts.append("<h2>Thread Extractions</h2>")
parts.append(f"<p>Analyzed {threads_total_analyzed} entries</p>")

# Canonical format: render thread categories with their entries
if isinstance(threads_dict, dict) and threads_dict:
    for cat_name, cat_data in threads_dict.items():
        if not isinstance(cat_data, dict):
            continue
        desc = cat_data.get("description", "")
        entries = cat_data.get("entries", [])
        parts.append(f'<h3>{esc(cat_name.replace("_", " ").title())} ({len(entries)} entries)</h3>')
        if desc:
            parts.append(f'<p>{esc(desc)}</p>')
        for entry in entries:
            if isinstance(entry, dict):
                idx = entry.get("msg_index", "?")
                content = entry.get("content", "")
                sig = entry.get("significance", "medium")
                tag_cls = {"high": "tag-high", "medium": "tag-medium", "low": "tag-low"}.get(sig, "tag-medium")
                parts.append(f'<div class="card info"><span class="tag {tag_cls}">{sig}</span> <b>msg {idx}</b>: {esc(content)}</div>')

# Old reference format: narrative arc, behavior patterns, crisis moments
if threads_narrative_arc:
    parts.append("<h3>Narrative Arc</h3>")
    parts.append("<table><tr><th>#</th><th>Chapter</th></tr>")
    for k, v in threads_narrative_arc.items():
        parts.append(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>")
    parts.append("</table>")

if threads_behavior_patterns:
    parts.append("<h3>Claude Behavior Patterns</h3>")
    for p in threads_behavior_patterns:
        parts.append(f'<div class="card warn">{esc(p)}</div>')

if threads_crisis_moments:
    parts.append("<h3>Key Crisis Moments</h3>")
    for c in threads_crisis_moments:
        if isinstance(c, dict):
            parts.append(f'<div class="card warn"><b>idx {c.get("index","?")}</b>: {esc(c.get("description",""))}</div>')
        else:
            parts.append(f'<div class="card warn">{esc(c)}</div>')

# Old reference format: marker summary from "extractions" list
if threads_extractions:
    parts.append("<h3>Marker Summary (from extractions)</h3>")
    pivots = sum(1 for e in threads_extractions if isinstance(e, dict) and e.get("markers",{}).get("is_pivot"))
    failures = sum(1 for e in threads_extractions if isinstance(e, dict) and e.get("markers",{}).get("is_failure"))
    breakthroughs = sum(1 for e in threads_extractions if isinstance(e, dict) and e.get("markers",{}).get("is_breakthrough"))
    deceptions = sum(1 for e in threads_extractions if isinstance(e, dict) and e.get("markers",{}).get("deception_detected"))
    gems = sum(1 for e in threads_extractions if isinstance(e, dict) and e.get("markers",{}).get("is_ignored_gem"))
    parts.append(f"""<table><tr><th>Marker</th><th>Count</th></tr>
<tr><td>Pivots</td><td>{pivots}</td></tr>
<tr><td>Failures</td><td>{failures}</td></tr>
<tr><td>Breakthroughs</td><td>{breakthroughs}</td></tr>
<tr><td>Deception Detected</td><td>{deceptions}</td></tr>
<tr><td>Ignored Gems</td><td>{gems}</td></tr></table>""")

parts.append("</div>")

# Panel 2: Geological
parts.append('<div class="panel" id="p2">')
parts.append("<h2>Geological Notes</h2>")

# Geological metaphor (canonical)
geo_metaphor = geo.get("geological_metaphor", "")
if geo_metaphor:
    parts.append(f'<div class="card success"><b>Geological Metaphor</b><br>{esc(geo_metaphor)}</div>')

# Micro entries
parts.append(f"<h3>Micro ({len(geo_micro)} entries)</h3>")
for m in geo_micro:
    if not isinstance(m, dict):
        continue
    parts.append(f'<div class="card info"><b>idx {m.get("index","?")}</b> [{m.get("type","")}] {esc(m.get("significance",""))}</div>')

# Meso entries — canonical has {observation, message_range, pattern}, old has {window, description, pattern}
parts.append(f"<h3>Meso ({len(geo_meso)} patterns)</h3>")
for m in geo_meso:
    if not isinstance(m, dict):
        continue
    # Canonical: "observation" + "message_range"
    observation = m.get("observation", "")
    message_range = m.get("message_range", "")
    pattern = m.get("pattern", "")
    # Old reference: "window" + "description"
    window = m.get("window", [])
    description = m.get("description", "")
    # Use canonical fields if present, fall back to old
    display_text = observation if observation else description
    display_range = message_range if message_range else str(window) if window else ""
    parts.append(f'<div class="card info"><b>{esc(display_range)}</b> [{esc(pattern)}] {esc(display_text)}</div>')

# Macro entries — canonical has {observation, scope, significance}, old has {arc_name, window, goal, outcome, fault_lines}
parts.append(f"<h3>Macro ({len(geo_macro)} arcs)</h3>")
for m in geo_macro:
    if not isinstance(m, dict):
        continue
    # Canonical format
    observation = m.get("observation", "")
    scope = m.get("scope", "")
    significance = m.get("significance", "")
    # Old reference format
    arc_name = m.get("arc_name", "")
    window = m.get("window", [])
    goal = m.get("goal", "")
    outcome = m.get("outcome", "")
    fault_lines = m.get("fault_lines", [])

    if observation:
        # Canonical format rendering
        parts.append(f'<div class="card"><b>{esc(scope)}</b><br>{esc(observation)}<br><i>Significance:</i> {esc(significance)}</div>')
    elif arc_name:
        # Old reference format rendering
        w0 = window[0] if len(window) > 0 else "?"
        w1 = window[1] if len(window) > 1 else "?"
        parts.append(f'<div class="card"><b>{esc(arc_name)}</b> [{w0}-{w1}]<br>{esc(goal)}<br><i>Outcome:</i> {esc(outcome)}<br><i>Fault lines:</i> {len(fault_lines)}</div>')
    else:
        # Unknown format — dump as JSON
        parts.append(f'<div class="card"><pre>{esc(json.dumps(m, indent=2))}</pre></div>')

# Observations (canonical)
geo_observations = geo.get("observations", [])
if geo_observations:
    parts.append(f"<h3>Observations ({len(geo_observations)})</h3>")
    for obs in geo_observations:
        if isinstance(obs, dict):
            parts.append(f'<div class="card info">{esc(obs.get("observation", str(obs)))}</div>')
        else:
            parts.append(f'<div class="card info">{esc(obs)}</div>')

# Recurring patterns (old reference format)
if geo_recurring:
    parts.append("<h3>Recurring Patterns</h3>")
    for k, v in geo_recurring.items():
        parts.append(f'<div class="card warn"><b>{esc(k)}</b><br>{esc(v.get("description","") if isinstance(v,dict) else v)}</div>')

parts.append("</div>")

# Panel 3: Primitives
parts.append('<div class="panel" id="p3">')
parts.append("<h2>Semantic Primitives</h2>")
parts.append(f"<p>Tagged {prims_total_tagged} messages</p>")

# Distributions (present in both canonical and old formats)
if prims_distributions:
    for dim, vals in prims_distributions.items():
        if isinstance(vals, dict):
            parts.append(f"<h3>{esc(dim.replace('_', ' ').title())}</h3><table><tr><th>Value</th><th>Count</th></tr>")
            for k2, v2 in sorted(vals.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0):
                parts.append(f"<tr><td>{esc(k2)}</td><td>{v2}</td></tr>")
            parts.append("</table>")
        elif isinstance(vals, list):
            parts.append(f"<h3>{esc(dim.replace('_', ' ').title())} ({len(vals)} items)</h3>")
            for item in vals[:20]:
                parts.append(f'<div class="card info">{esc(str(item))}</div>')
        else:
            parts.append(f'<div class="card info"><b>{esc(dim)}</b>: {esc(str(vals))}</div>')

# Tagged messages detail (canonical)
if prims_tagged:
    parts.append(f"<h3>Tagged Messages ({len(prims_tagged)})</h3>")
    for tm in prims_tagged[:30]:
        if not isinstance(tm, dict):
            continue
        idx = tm.get("index", tm.get("msg_index", "?"))
        role = tm.get("role", "?")
        primitives = tm.get("primitives", {})
        if isinstance(primitives, dict):
            prim_strs = [f"{pk}: {pv}" for pk, pv in primitives.items() if pv]
            parts.append(f'<div class="card"><b>msg {idx}</b> [{role}] {esc(", ".join(prim_strs))}</div>')
        else:
            parts.append(f'<div class="card"><b>msg {idx}</b> [{role}] {esc(str(primitives))}</div>')

parts.append("</div>")

# Panel 4: Explorer
parts.append('<div class="panel" id="p4">')
parts.append("<h2>Free Explorer Notes</h2>")

# Explorer summary (canonical)
if explorer_summary_text:
    parts.append(f'<div class="card success"><b>Explorer Summary</b><br>{esc(explorer_summary_text)}</div>')

# What matters most (old reference format)
if explorer_what_matters:
    parts.append(f'<div class="card success"><b>What Matters Most</b><br>{esc(explorer_what_matters)}</div>')

# Observations (canonical: list of dicts with id/observation/evidence/significance)
if explorer_observations:
    parts.append(f"<h3>Observations ({len(explorer_observations)})</h3>")
    for obs in explorer_observations:
        if isinstance(obs, dict):
            obs_id = obs.get("id", "")
            obs_text = obs.get("observation", "")
            obs_evidence = obs.get("evidence", "")
            obs_sig = obs.get("significance", "medium")
            tag_cls = {"high": "tag-high", "medium": "tag-medium", "low": "tag-low"}.get(obs_sig, "tag-medium")
            parts.append(f'<div class="card info">')
            if obs_id:
                parts.append(f'<span class="tag {tag_cls}">{esc(obs_sig)}</span> <b>[{esc(obs_id)}]</b> ')
            parts.append(f'{esc(obs_text)}')
            if obs_evidence:
                parts.append(f'<br><i>Evidence: {esc(obs_evidence)}</i>')
            parts.append('</div>')
        else:
            parts.append(f'<div class="card info">{esc(obs)}</div>')

# Verification (canonical)
if explorer_verification:
    parts.append(f"<h3>Verification</h3>")
    for vk, vv in explorer_verification.items():
        parts.append(f'<div class="card"><b>{esc(vk.replace("_", " ").title())}</b>: {esc(str(vv))}</div>')

# Old reference format sections — render only if present
for section_name, section_data, card_cls in [
    ("Warnings", explorer_warnings, "warn"),
    ("Patterns", explorer_patterns, "info"),
    ("Abandoned Ideas", explorer_abandoned, "info"),
    ("Emotional Dynamics", explorer_emotional, "info"),
    ("Surprises", explorer_surprises, "info"),
]:
    if section_data:
        parts.append(f"<h3>{section_name} ({len(section_data)})</h3>")
        for item in section_data:
            parts.append(f'<div class="card {card_cls}">{esc(item)}</div>')

if explorer_free_notes:
    parts.append("<h3>Free Notes</h3>")
    parts.append(f'<pre>{esc(explorer_free_notes)}</pre>')

parts.append("</div>")

# Panel 5: Idea Graph
parts.append('<div class="panel" id="p5">')
parts.append("<h2>Idea Evolution Graph</h2>")

# Canonical uses "metadata", old reference uses "statistics"
total_nodes_meta = graph_meta.get("total_nodes", graph_meta.get("total_ideas", len(graph_nodes)))
total_edges_meta = graph_meta.get("total_edges", graph_meta.get("total_transitions", len(graph_edges)))
parts.append(f"<p>{total_nodes_meta} nodes, {total_edges_meta} edges</p>")

# Metadata details (canonical)
if graph_meta:
    meta_items = []
    for mk, mv in graph_meta.items():
        if mk not in ("total_nodes", "total_edges", "total_ideas", "total_transitions", "transition_type_distribution"):
            meta_items.append(f"<b>{esc(mk.replace('_', ' ').title())}</b>: {esc(str(mv))}")
    if meta_items:
        parts.append(f'<div class="card info">{" | ".join(meta_items)}</div>')

# Subgraphs (old reference format)
if graph_subgraphs:
    parts.append("<h3>Subgraphs</h3>")
    for sg in graph_subgraphs:
        if isinstance(sg, dict):
            parts.append(f'<div class="card info"><b>{esc(sg.get("name",""))}</b> ({len(sg.get("node_ids",[]))} nodes)<br>{esc(sg.get("summary",""))}</div>')

# Transition distribution (old reference "statistics" format)
trans_dist = graph_meta.get("transition_type_distribution", {})
if trans_dist:
    parts.append("<h3>Transition Distribution</h3><table><tr><th>Type</th><th>Count</th></tr>")
    for t, c in sorted(trans_dist.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0):
        if isinstance(c, (int, float)) and c > 0:
            parts.append(f"<tr><td>{esc(t)}</td><td>{c}</td></tr>")
    parts.append("</table>")

# Edge type summary (canonical — compute from edges)
if graph_edges and not trans_dist:
    edge_types = {}
    for e in graph_edges:
        if isinstance(e, dict):
            etype = e.get("type", "unknown")
            edge_types[etype] = edge_types.get(etype, 0) + 1
    if edge_types:
        parts.append("<h3>Edge Type Distribution</h3><table><tr><th>Type</th><th>Count</th></tr>")
        for t, c in sorted(edge_types.items(), key=lambda x: -x[1]):
            parts.append(f"<tr><td>{esc(t)}</td><td>{c}</td></tr>")
        parts.append("</table>")

# All Nodes — canonical has {id, label, description, message_index, confidence, maturity}
#              old reference has {name, description, confidence, first_appearance}
parts.append(f"<h3>All Nodes ({len(graph_nodes)})</h3><div class='grid'>")
for n in graph_nodes[:30]:
    if not isinstance(n, dict):
        continue
    # "label" is canonical, "name" is old reference
    node_name = n.get("label", n.get("name", n.get("id", "?")))
    description = n.get("description", "")
    confidence = n.get("confidence", "")
    maturity = n.get("maturity", "")
    # "message_index" is canonical, "first_appearance" is old reference
    first_msg = n.get("message_index", n.get("first_appearance", "?"))
    conf_cls = {"fragile": "warn", "experimental": "info", "proven": "success"}.get(confidence, "")
    details = f"Confidence: {confidence}"
    if maturity:
        details += f" | Maturity: {maturity}"
    details += f" | First: msg {first_msg}"
    parts.append(f'<div class="node"><div class="name">{esc(node_name)}</div><div>{esc(description)}</div><div class="edge">{details}</div></div>')
parts.append("</div></div>")

# Panel 6: Synthesis
parts.append('<div class="panel" id="p6">')
parts.append("<h2>Multi-Pass Synthesis</h2>")

# Session character (canonical)
if synthesis_session_char:
    parts.append(f'<div class="card success"><b>Session Character</b><br>{esc(synthesis_session_char)}</div>')

# Key findings (canonical)
if synthesis_key_findings:
    if isinstance(synthesis_key_findings, list):
        parts.append(f"<h3>Key Findings ({len(synthesis_key_findings)})</h3>")
        for kf in synthesis_key_findings:
            parts.append(f'<div class="card info">{esc(str(kf))}</div>')
    elif isinstance(synthesis_key_findings, dict):
        parts.append("<h3>Key Findings</h3>")
        parts.append(f'<div class="card info"><pre>{esc(json.dumps(synthesis_key_findings, indent=2))}</pre></div>')

# Passes — normalized to synthesis_passes_list (handles both dict and list source)
for sp in synthesis_passes_list:
    label = sp.get("label", sp.get("pass_key", "?"))
    temperature = sp.get("temperature", "?")
    content = sp.get("content", "")
    findings = sp.get("findings", {})

    parts.append(f'<h3>{esc(label)} (temp {temperature})</h3>')

    # Canonical format: content is a string
    if content:
        parts.append(f'<div class="card"><pre>{esc(content)}</pre></div>')

    # Old reference format: findings is a dict of lists/dicts/values
    if findings:
        for fk, fv in findings.items():
            if isinstance(fv, list):
                parts.append(f"<b>{esc(fk)}</b> ({len(fv)} items)")
                for item in fv[:10]:
                    if isinstance(item, dict):
                        parts.append(f'<div class="card info">{esc(json.dumps(item, indent=2))}</div>')
                    else:
                        parts.append(f'<div class="card">{esc(str(item))}</div>')
            elif isinstance(fv, dict):
                parts.append(f'<div class="card"><b>{esc(fk)}</b><pre>{esc(json.dumps(fv, indent=2))}</pre></div>')
            else:
                parts.append(f'<div class="card"><b>{esc(fk)}</b>: {esc(str(fv))}</div>')

# Cross-session links (canonical)
cross_links = synthesis.get("cross_session_links", [])
if cross_links:
    parts.append(f"<h3>Cross-Session Links ({len(cross_links)})</h3>")
    for cl in cross_links:
        if isinstance(cl, dict):
            parts.append(f'<div class="card info"><pre>{esc(json.dumps(cl, indent=2))}</pre></div>')
        else:
            parts.append(f'<div class="card info">{esc(str(cl))}</div>')

parts.append("</div>")

# Panel 7: Grounded Markers
parts.append('<div class="panel" id="p7">')
parts.append("<h2>Grounded Markers</h2>")

# Canonical format: flat "markers" list with {marker_id, category, claim, evidence, confidence, actionable_guidance}
if markers_flat:
    # Group by category for better display
    by_category = {}
    for m in markers_flat:
        if not isinstance(m, dict):
            continue
        cat = m.get("category", "uncategorized")
        by_category.setdefault(cat, []).append(m)

    parts.append(f"<p>{len(markers_flat)} markers across {len(by_category)} categories</p>")
    for cat, cat_markers in sorted(by_category.items()):
        parts.append(f'<h3>{esc(cat.replace("_", " ").title())} ({len(cat_markers)})</h3>')
        for m in cat_markers:
            marker_id = m.get("marker_id", "")
            claim = m.get("claim", "")
            evidence = m.get("evidence", "")
            confidence = m.get("confidence", "")
            guidance = m.get("actionable_guidance", "")
            # Map confidence to tag class
            if isinstance(confidence, (int, float)):
                if confidence >= 0.8:
                    tag_cls = "tag-high"
                elif confidence >= 0.5:
                    tag_cls = "tag-medium"
                else:
                    tag_cls = "tag-low"
                conf_display = f"{confidence:.0%}"
            else:
                tag_cls = "tag-medium"
                conf_display = str(confidence)
            parts.append(f'<div class="card info"><span class="tag {tag_cls}">{conf_display}</span> <b>[{esc(marker_id)}]</b> {esc(claim)}')
            if evidence:
                parts.append(f'<br><i>Evidence: {esc(evidence)}</i>')
            if guidance:
                parts.append(f'<br><b>Guidance:</b> {esc(guidance)}')
            parts.append('</div>')

# Old reference format: iron_rules_registry, warnings, patterns, recommendations, metrics
if markers_iron_rules:
    parts.append(f"<h3>Iron Rules Registry ({len(markers_iron_rules)})</h3>")
    for r in markers_iron_rules:
        if not isinstance(r, dict):
            continue
        caps = r.get("caps_ratio", 0)
        parts.append(f'<div class="iron"><b>Rule {r.get("rule_number","?")}</b>: {esc(r.get("rule",""))}<br><span class="caps">Established: msg {r.get("established_at","")} | Caps: {caps} | Status: {r.get("status","")}</span><br>{esc(r.get("evidence",""))}</div>')

if markers_warnings:
    parts.append(f"<h3>Warnings ({len(markers_warnings)})</h3>")
    for w in markers_warnings:
        if not isinstance(w, dict):
            continue
        sev = w.get("severity", "medium")
        parts.append(f'<div class="card warn"><span class="tag tag-{sev}">{sev}</span> <b>[{w.get("id","")}] {esc(w.get("target",""))}</b><br>{esc(w.get("warning",""))}<br><i>Evidence: {esc(w.get("evidence",""))}</i></div>')

if markers_patterns:
    parts.append(f"<h3>Behavioral Patterns ({len(markers_patterns)})</h3>")
    for p in markers_patterns:
        if not isinstance(p, dict):
            continue
        parts.append(f'<div class="card info"><b>[{p.get("id","")}]</b> {esc(p.get("pattern",""))}<br>Frequency: {esc(p.get("frequency",""))}<br>Action: {esc(p.get("action",""))}</div>')

if markers_recommendations:
    parts.append(f"<h3>Recommendations ({len(markers_recommendations)})</h3>")
    for r in markers_recommendations:
        if not isinstance(r, dict):
            continue
        pri = r.get("priority", "medium")
        parts.append(f'<div class="card"><span class="tag tag-{pri}">{pri}</span> <b>[{r.get("id","")}] {esc(r.get("target",""))}</b><br>{esc(r.get("recommendation",""))}</div>')

if markers_metrics:
    parts.append(f"<h3>Metrics ({len(markers_metrics)})</h3>")
    for m in markers_metrics:
        if not isinstance(m, dict):
            continue
        parts.append(f'<div class="card metric"><b>[{m.get("id","")}] {esc(m.get("metric",""))}</b><br>Value: <b>{esc(m.get("value",""))}</b><br>Source: {esc(m.get("source",""))}</div>')

parts.append("</div>")

# Panel 8: File Dossiers
parts.append('<div class="panel" id="p8">')
parts.append("<h2>File Dossiers (15 files)</h2>")
for d in dossiers.get("files", []):
    parts.append(f'<div class="card"><h3>{esc(d.get("filename",""))}</h3>')
    parts.append(f'<b>Mentions:</b> {d.get("total_mentions",0)} | <b>Confidence:</b> {d.get("confidence","")}')
    parts.append(f'<br><b>Story:</b> {esc(d.get("story_arc",""))}')
    parts.append(f'<br><b>Warnings:</b> {len(d.get("warnings",[]))} | <b>Recommendations:</b> {len(d.get("recommendations",[]))}')
    cb = d.get("claude_behavior", {})
    parts.append(f'<br><b>Claude Behavior:</b> impulse={esc(cb.get("impulse_control","?"))}, authority={esc(cb.get("authority_response","?"))}, overconfidence={esc(cb.get("overconfidence","?"))}, context_damage={esc(cb.get("context_damage","?"))}')
    parts.append("</div>")
parts.append("</div>")

# Panel 9: CLAUDE.md Analysis
parts.append('<div class="panel" id="p9">')
parts.append("<h2>CLAUDE.md Impact Analysis</h2>")
for gk, gv in claude_md.get("gate_analysis", {}).items():
    parts.append(f'<div class="card warn"><h3>{esc(gk)}</h3>')
    if isinstance(gv, dict):
        parts.append(f'<b>Impact:</b> {esc(gv.get("session_impact",""))}')
        eff = gv.get("effectiveness","")
        parts.append(f'<br><b>Effectiveness:</b> {esc(eff if isinstance(eff,str) else str(eff))}')
        rec = gv.get("recommended_change","")
        parts.append(f'<br><b>Recommended Change:</b> {esc(rec if isinstance(rec,str) else str(rec))}')
    parts.append("</div>")
fa = claude_md.get("framing_analysis", {})
for fk, fv in fa.items():
    parts.append(f'<div class="card"><h3>Framing: {esc(fk)}</h3>')
    if isinstance(fv, dict):
        parts.append(f'<b>Assessment:</b> {esc(str(fv.get("overall_assessment",""))[:600])}')
    parts.append("</div>")
parts.append("<h3>Improvement Recommendations</h3>")
for r in claude_md.get("claude_md_improvement_recommendations", []):
    pri = r.get("priority", "medium")
    parts.append(f'<div class="card"><span class="tag tag-{pri}">{pri}</span> <b>[{r.get("id","")}] {esc(r.get("target",""))}</b><br>{esc(str(r.get("recommendation","")))}</div>')
parts.append("</div>")

# Panel 10: Hyperdoc Blocks
parts.append('<div class="panel" id="p10">')
parts.append("<h2>Hyperdoc Comment Blocks</h2>")
parts.append("<p>These are the actual comment blocks ready to be inserted into code files.</p>")
for hf in hyperdoc_files:
    name = hf.replace("_hyperdoc.txt", ".py")
    content = load_text(hf)
    parts.append(f'<h3>{name}</h3><pre>{esc(content)}</pre>')
parts.append("</div>")

# JavaScript
parts.append("""<script>
function showTab(n){
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.toggle('active',i===n)});
  document.querySelectorAll('.panel').forEach((p,i)=>{p.classList.toggle('active',i===n)});
}
</script></body></html>""")

html_content = "\n".join(parts)
out = BASE / "pipeline_viewer.html"
with open(out, "w") as f:
    f.write(html_content)
print(f"Written: {out} ({os.path.getsize(out):,} bytes)")

# ======================================================================
# @ctx HYPERDOC — HISTORICAL (generated 2026-02-08, requires realtime update)
# These annotations are from the Phase 4b bulk processing run across 284
# sessions. The code below may have changed since these markers were
# generated. Markers reflect the state of the codebase as of Feb 8, 2026.
# ======================================================================

# --- HEADER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================

# --- FOOTER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================
# # ===========================================================================
# # HYPERDOC HEADER: generate_viewer.py
# # @ctx:version=1 @ctx:schema=hyperdoc_v2 @ctx:source_sessions=conv_4953cc6b,conv_4c08a224,conv_750f50f9
# # @ctx:generated=2026-02-08T18:42:00Z @ctx:generator=phase_4b_opus
# # @ctx:file_status=DELETED @ctx:exists_on_disk=false
# # @ctx:confidence=tentative @ctx:churn=low @ctx:mentions=4
# # @ctx:emotion=indifference_to_dismissal
# # @ctx:failed_approaches=1
# # ===========================================================================
# #
# # --- STORY ARC ---
# #
# # generate_viewer.py was created as one of the 18 executable pipeline scripts
# # in the hyperdocs_3 system, responsible for generating HTML visualizations from
# # pipeline outputs. It appeared in 3 sessions but was never a focus of deep
# # analysis in any of them. In session 4c08a224, during the 40-file systematic
# # analysis, it was categorized as one of 11 files recommended for ARCHIVE --
# # deemed non-essential to the pipeline's core mission. The file also carried a
# # design flaw common to viewer components: it used JavaScript fetch() to load
# # local data files, which fails when opened via file:// URLs. Session 750f50f9
# # documented this failure and the pivot to an embedded viewer approach. The file
# # was eventually deleted from disk, replaced by the embedded viewer pattern.
# #
# # --- FRICTION: WHAT WENT WRONG AND WHY ---
# #
# # @ctx:friction="Hardcoded session IDs in active output code required manual cleanup"
# # @ctx:trace=conv_4953cc6b:msg1081
# #   [F01] generate_viewer.py contained hardcoded session IDs and paths in its
# #   active output code (not just docstrings or templates). At msg 1081, Claude
# #   identified 6 remaining hardcoded references across multiple files, and
# #   specifically called out generate_viewer.py and generate_dossiers.py as
# #   having refs in active output code that needed fixing. The hardcoded paths
# #   violated the config.py pattern established for the hyperdocs_3 system.
# #
# # @ctx:friction="JavaScript fetch approach fails with file:// URLs, breaking user rule"
# # @ctx:trace=conv_750f50f9:msg0862
# #   [F02] The viewer used JavaScript fetch() or XMLHttpRequest to load local
# #   JSON files. When users opened the HTML via file:// URLs (double-clicking),
# #   browsers block these requests due to CORS/security policies. This violated
# #   the user's permanent rule: 'User NEVER starts servers.' The file had to be
# #   rebuilt with content embedded directly in the HTML. This friction was
# #   documented in the idea graph as the transition from idea_hyperdoc_writing_v2
# #   to idea_embedded_viewer, and in the grounded_markers as a medium-severity
# #   warning about the file:// constraint.
# #
# # @ctx:friction="File recommended for archive during systematic analysis, indicating low value"
# # @ctx:trace=conv_4c08a224:msg0144
# #   [F03] During the 40-file systematic analysis in session 4c08a224, generate_viewer.py
# #   was classified in the ARCHIVE category alongside 10 other files (analyze_claude_ai_export.py,
# #   compare_with_without_hyperdocs.py, generate_project_gantt.py, hyperdoc_live_server.py,
# #   hyperdoc_file_scanner.py, hyperdoc_query.py, semantic_chunker.py, spawn_analysis_agents.py,
# #   granular_edit_extractor_v3.py, and others). The analysis concluded these files were not
# #   essential to the core pipeline. generate_viewer.py received only surface-level analysis
# #   (status: 'Surface-level analysis only', confidence: 'tentative').
# #
# # --- DECISIONS: CHOSE X OVER Y BECAUSE Z ---
# #
# # @ctx:decision="chose embedded HTML viewer over JavaScript-fetching viewer because file:// URLs block fetch requests and user never starts servers"
# # @ctx:trace=conv_750f50f9:msg0862
# #   Alternatives considered: (1) JavaScript fetch viewer requiring a local server,
# #   (2) embedded viewer with content directly in HTML, (3) data URI approach.
# #   Why rejected: JavaScript fetch fails silently or with CORS errors when
# #   opened via file:// URLs. The user has a permanent rule that they never
# #   start servers manually. The embedded approach was chosen because it works
# #   with direct file opening and requires zero infrastructure.
# #
# # @ctx:decision="chose to archive generate_viewer.py over keeping or enhancing it because it was non-essential to the core extraction pipeline"
# # @ctx:trace=conv_4c08a224:msg0144
# #   Alternatives considered: KEEP (retain as-is), ENHANCE (add features),
# #   REPLACE (rewrite from scratch), ARCHIVE (remove from active codebase).
# #   Why rejected: The file generated visualizations, not core extraction logic.
# #   The pipeline's value comes from its extraction and analysis phases (thread
# #   extraction, geological reading, dossier generation, hyperdoc writing), not
# #   from viewer generation. Viewer functionality was handled by other files
# #   (hyperdoc_embedded_viewer.html, gate_control_panel.html, dashboard.py).
# #
# # --- WARNINGS ---
# #
# # @ctx:warning="[W01] [medium] Static HTML viewers that fetch files via JavaScript fail with file:// URLs. This is a recurring issue that Claude forgets across sessions. Any HTML-generating task must embed content directly or use data URLs."
# # @ctx:trace=conv_750f50f9:msg0862
# #   Resolution: Resolved at msg 862 in session 750f50f9 by rebuilding as embedded viewer.
# #   Evidence: Grounded marker in session 750f50f9 synthesis finding G9. Idea graph
# #   edge idea_hyperdoc_writing_v2 -> idea_embedded_viewer (evolved, trigger_message 862).
# #
# # @ctx:warning="[W02] [low] File contains hardcoded session IDs in active output code, not just templates."
# # @ctx:trace=conv_4953cc6b:msg1081
# #   Resolution: Resolved at msg 1081 in session 4953cc6b. Claude fixed the references.
# #   Evidence: Batch 010 message at index 1081 explicitly states the fix.
# #
# # --- IRON RULES ---
# #
# # - User NEVER starts servers. All visualizations must work from static HTML
# #   files opened via file:// URLs. No manual python3 server.py commands.
# # - User NEVER opens HTML files manually. Claude must auto-open with 'open' command.
# # - HTML must embed content directly. No JavaScript fetch() or XMLHttpRequest
# #   for local files.
# #
# # --- CLAUDE BEHAVIOR ON THIS FILE ---
# #
# # @ctx:claude_pattern="impulse_control: adequate -- Claude did not attempt to deeply analyze this file; it was mentioned in passing within larger file audits. No evidence of premature action on this specific file."
# # @ctx:claude_pattern="authority_response: adequate -- When the 40-file analysis recommended archiving, Claude followed the systematic classification without pushback."
# # @ctx:claude_pattern="overconfidence: mild -- In session 4953cc6b msg 503, Claude listed generate_viewer.py as one of 18 files that 'actually execute' in the pipeline, but the file was later deemed non-essential. This suggests the initial assessment overstated the file's importance."
# # @ctx:claude_pattern="context_damage: moderate -- The file:// URL constraint is a recurring issue Claude forgets across sessions (documented in session 750f50f9 synthesis G9). Claude built a JavaScript-fetching viewer despite the user's permanent rule against server dependencies, requiring a rebuild."
# #
# # --- EMOTIONAL CONTEXT ---
# #
# # User showed no specific emotional reaction to generate_viewer.py. The file
# # appeared in bulk listings and batch analyses, not in focused discussions.
# # In session 4c08a224, the user's overall emotional context was focused on
# # wanting a systematic analysis of every file ('I told you I want to meaningfully
# # analyze every file'). generate_viewer.py received only surface-level treatment
# # despite this demand, but the user did not specifically call it out. The file's
# # archival status suggests it was not emotionally significant to the user.
# # In session 750f50f9, the viewer rebuild at msg 862 was met with relief
# # (emotional_context on idea_embedded_viewer: 'Relieved. Simple fix for a
# # recurring issue (Claude forgetting user rules).').
# #
# # --- FAILED APPROACHES ---
# #
# # @ctx:failed_approaches=1
# # [ABANDONED] JavaScript-fetching viewer -> Embedded HTML viewer (msg 862, session 750f50f9)
# #   The original generate_viewer.py used JavaScript fetch() to load pipeline
# #   output JSON files and render them as HTML. This approach failed because
# #   browsers block fetch requests from file:// URLs for security reasons. The
# #   user's permanent rule is that they never start servers manually, so the
# #   server workaround was not acceptable. The approach was abandoned in favor
# #   of embedding content directly into the HTML file.
# #
# # --- RECOMMENDATIONS ---
# #
# # [R01] (priority: low)
# #   This file has been deleted from disk and archived. No action needed unless
# #   the viewer generation concept is revived. If revived, the embedded HTML
# #   pattern must be used -- not JavaScript fetch.
# #
# # [R02] (priority: medium)
# #   Any future HTML visualization generator must be pre-contextualized with
# #   the file:// URL constraint before writing any code. This is a recurring
# #   Claude failure pattern documented in session 750f50f9 synthesis finding G9.
# #
# # ===========================================================================
# ======================================================================



# ======================================================================
# @ctx HYPERDOC FOOTER
# ======================================================================

