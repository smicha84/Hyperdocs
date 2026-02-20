#!/usr/bin/env python3
"""Generate a comprehensive HTML viewer for all pipeline outputs."""
import json
import os
import html
from pathlib import Path

BASE = Path(__file__).parent

def load(name):
    with open(BASE / name) as f:
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
threads = load("thread_extractions.json")
geo = load("geological_notes.json")
prims = load("semantic_primitives.json")
explorer = load("explorer_notes.json")
graph = load("idea_graph.json")
synthesis = load("synthesis.json")
markers = load("grounded_markers.json")
dossiers = load("file_dossiers.json")
claude_md = load("claude_md_analysis.json")

stats = summary["session_stats"]

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
parts.append(f"""<div class="header">
<h1>Hyperdocs Multi-Agent Extraction Pipeline</h1>
<div class="sub">{stats['total_messages']} messages | {stats['user_messages']} user / {stats['assistant_messages']} assistant</div>
<div class="stats-bar">
<div class="stat"><b>{stats['total_messages']}</b>Messages</div>
<div class="stat"><b>{len(stats.get('frustration_peaks',[]))}</b>Frustration Peaks</div>
<div class="stat"><b>{len(stats.get('emergency_interventions',[]))}</b>Emergency Interventions</div>
<div class="stat"><b>{len(stats.get('file_mention_counts',{}))}</b>Unique Files</div>
<div class="stat"><b>{stats['total_input_tokens']:,}</b>Input Tokens</div>
<div class="stat"><b>{threads['total_analyzed']}</b>Extractions</div>
<div class="stat"><b>{len(graph['nodes'])}</b>Idea Nodes</div>
<div class="stat"><b>{len(graph['edges'])}</b>Transitions</div>
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
td = stats["tier_distribution"]
parts.append(f"""<table><tr><th>Tier</th><th>Count</th><th>%</th></tr>
<tr><td>1 (Skip)</td><td>{td['1_skip']}</td><td>{td['1_skip']/stats['total_messages']*100:.0f}%</td></tr>
<tr><td>2 (Basic)</td><td>{td['2_basic']}</td><td>{td['2_basic']/stats['total_messages']*100:.0f}%</td></tr>
<tr><td>3 (Standard)</td><td>{td['3_standard']}</td><td>{td['3_standard']/stats['total_messages']*100:.0f}%</td></tr>
<tr><td>4 (Priority)</td><td>{td['4_priority']}</td><td>{td['4_priority']/stats['total_messages']*100:.0f}%</td></tr>
</table>""")
parts.append("<h2>Top Files by Mention Count</h2><table><tr><th>#</th><th>File</th><th>Mentions</th></tr>")
for i, (f, c) in enumerate(stats.get("top_files", [])[:15], 1):
    parts.append(f"<tr><td>{i}</td><td>{esc(f)}</td><td>{c}</td></tr>")
parts.append("</table></div>")

# Panel 1: Threads
parts.append('<div class="panel" id="p1">')
parts.append("<h2>Thread Extractions</h2>")
parts.append(f"<p>Analyzed {threads['total_analyzed']} tier-4 messages</p>")
parts.append("<h3>Narrative Arc (12 Chapters)</h3>")
arc = threads.get("narrative_arc", {})
parts.append("<table><tr><th>#</th><th>Chapter</th></tr>")
for k, v in arc.items():
    parts.append(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>")
parts.append("</table>")
parts.append("<h3>Claude Behavior Patterns</h3>")
for p in threads.get("claude_behavior_patterns", []):
    parts.append(f'<div class="card warn">{esc(p)}</div>')
parts.append("<h3>Key Crisis Moments</h3>")
for c in threads.get("key_crisis_moments", []):
    if isinstance(c, dict):
        parts.append(f'<div class="card warn"><b>idx {c.get("index","?")}</b>: {esc(c.get("description",""))}</div>')
    else:
        parts.append(f'<div class="card warn">{esc(c)}</div>')
parts.append("<h3>Marker Summary</h3>")
pivots = sum(1 for e in threads.get("extractions",[]) if e.get("markers",{}).get("is_pivot"))
failures = sum(1 for e in threads.get("extractions",[]) if e.get("markers",{}).get("is_failure"))
breakthroughs = sum(1 for e in threads.get("extractions",[]) if e.get("markers",{}).get("is_breakthrough"))
deceptions = sum(1 for e in threads.get("extractions",[]) if e.get("markers",{}).get("deception_detected"))
gems = sum(1 for e in threads.get("extractions",[]) if e.get("markers",{}).get("is_ignored_gem"))
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
parts.append(f"<h3>Micro ({len(geo['micro'])} entries)</h3>")
for m in geo["micro"]:
    parts.append(f'<div class="card info"><b>idx {m.get("index","?")}</b> [{m.get("type","")}] {esc(m.get("significance",""))}</div>')
parts.append(f"<h3>Meso ({len(geo['meso'])} patterns)</h3>")
for m in geo["meso"]:
    w = m.get("window", [])
    parts.append(f'<div class="card info"><b>{w}</b> [{m.get("pattern","")}] {esc(m.get("description",""))}</div>')
parts.append(f"<h3>Macro ({len(geo['macro'])} arcs)</h3>")
for m in geo["macro"]:
    w = m.get("window", [])
    parts.append(f'<div class="card"><b>{esc(m.get("arc_name",""))}</b> [{w[0]}-{w[1]}]<br>{esc(m.get("goal",""))}<br><i>Outcome:</i> {esc(m.get("outcome",""))}<br><i>Fault lines:</i> {len(m.get("fault_lines",[]))}</div>')
parts.append("<h3>Recurring Patterns</h3>")
for k, v in geo.get("recurring_patterns", {}).items():
    parts.append(f'<div class="card warn"><b>{esc(k)}</b><br>{esc(v.get("description","") if isinstance(v,dict) else v)}</div>')
parts.append("</div>")

# Panel 3: Primitives
parts.append('<div class="panel" id="p3">')
parts.append("<h2>Semantic Primitives</h2>")
parts.append(f"<p>Tagged {prims['total_tagged']} messages</p>")
dist = prims.get("distributions", {})
for dim, vals in dist.items():
    if isinstance(vals, dict):
        parts.append(f"<h3>{dim}</h3><table><tr><th>Value</th><th>Count</th></tr>")
        for k2, v2 in sorted(vals.items(), key=lambda x: -x[1] if isinstance(x[1],int) else 0):
            parts.append(f"<tr><td>{esc(k2)}</td><td>{v2}</td></tr>")
        parts.append("</table>")
    else:
        parts.append(f'<div class="card info"><b>{dim}</b>: {vals}</div>')
parts.append("</div>")

# Panel 4: Explorer
parts.append('<div class="panel" id="p4">')
parts.append("<h2>Free Explorer Notes</h2>")
parts.append(f'<div class="card success"><b>What Matters Most</b><br>{esc(explorer.get("what_matters_most",""))}</div>')
for section in ["observations","warnings","patterns","abandoned_ideas","emotional_dynamics","surprises"]:
    items = explorer.get(section, [])
    parts.append(f"<h3>{section.replace('_',' ').title()} ({len(items)})</h3>")
    for item in items:
        cls = "warn" if "warn" in section else "info"
        parts.append(f'<div class="card {cls}">{esc(item)}</div>')
parts.append("<h3>Free Notes</h3>")
parts.append(f'<pre>{esc(explorer.get("free_notes",""))}</pre>')
parts.append("</div>")

# Panel 5: Idea Graph
parts.append('<div class="panel" id="p5">')
parts.append("<h2>Idea Evolution Graph</h2>")
gs = graph.get("statistics", {})
parts.append(f"<p>{gs.get('total_ideas',0)} nodes, {gs.get('total_transitions',0)} edges, 0 cycles</p>")
parts.append("<h3>Subgraphs</h3>")
for sg in graph.get("subgraphs", []):
    parts.append(f'<div class="card info"><b>{esc(sg.get("name",""))}</b> ({len(sg.get("node_ids",[]))} nodes)<br>{esc(sg.get("summary",""))}</div>')
parts.append("<h3>Transition Distribution</h3><table><tr><th>Type</th><th>Count</th></tr>")
for t, c in sorted(gs.get("transition_type_distribution",{}).items(), key=lambda x:-x[1]):
    if c > 0:
        parts.append(f"<tr><td>{t}</td><td>{c}</td></tr>")
parts.append("</table>")
parts.append("<h3>All Nodes</h3><div class='grid'>")
for n in graph["nodes"][:30]:
    conf_cls = {"fragile":"warn","experimental":"info","proven":"success"}.get(n.get("confidence",""),"")
    parts.append(f'<div class="node"><div class="name">{esc(n["name"])}</div><div>{esc(n.get("description",""))}</div><div class="edge">Confidence: {n.get("confidence","")} | First: msg {n.get("first_appearance","?")}</div></div>')
parts.append("</div></div>")

# Panel 6: Synthesis
parts.append('<div class="panel" id="p6">')
parts.append("<h2>6-Pass Synthesis</h2>")
for p in synthesis.get("passes", []):
    pn = p["pass_number"]
    parts.append(f'<h3>Pass {pn}: {p["focus"]} (temp {p.get("temperature","?")})</h3>')
    findings = p.get("findings", {})
    for fk, fv in findings.items():
        if isinstance(fv, list):
            parts.append(f"<b>{fk}</b> ({len(fv)} items)")
            for item in fv[:10]:
                if isinstance(item, dict):
                    parts.append(f'<div class="card info">{esc(json.dumps(item, indent=2))}</div>')
                else:
                    parts.append(f'<div class="card">{esc(str(item))}</div>')
        elif isinstance(fv, dict):
            parts.append(f'<div class="card"><b>{fk}</b><pre>{esc(json.dumps(fv, indent=2))}</pre></div>')
        else:
            parts.append(f'<div class="card"><b>{fk}</b>: {esc(str(fv))}</div>')
parts.append("</div>")

# Panel 7: Grounded Markers
parts.append('<div class="panel" id="p7">')
parts.append("<h2>Grounded Markers</h2>")
parts.append("<h3>Iron Rules Registry</h3>")
for r in markers.get("iron_rules_registry", []):
    caps = r.get("caps_ratio", 0)
    parts.append(f'<div class="iron"><b>Rule {r.get("rule_number","?")}</b>: {esc(r.get("rule",""))}<br><span class="caps">Established: msg {r.get("established_at","")} | Caps: {caps} | Status: {r.get("status","")}</span><br>{esc(r.get("evidence",""))}</div>')
parts.append(f"<h3>Warnings ({len(markers.get('warnings',[]))})</h3>")
for w in markers.get("warnings", []):
    sev = w.get("severity","medium")
    parts.append(f'<div class="card warn"><span class="tag tag-{sev}">{sev}</span> <b>[{w.get("id","")}] {esc(w.get("target",""))}</b><br>{esc(w.get("warning",""))}<br><i>Evidence: {esc(w.get("evidence",""))}</i></div>')
parts.append(f"<h3>Behavioral Patterns ({len(markers.get('patterns',[]))})</h3>")
for p in markers.get("patterns", []):
    parts.append(f'<div class="card info"><b>[{p.get("id","")}]</b> {esc(p.get("pattern",""))}<br>Frequency: {esc(p.get("frequency",""))}<br>Action: {esc(p.get("action",""))}</div>')
parts.append(f"<h3>Recommendations ({len(markers.get('recommendations',[]))})</h3>")
for r in markers.get("recommendations", []):
    pri = r.get("priority","medium")
    parts.append(f'<div class="card"><span class="tag tag-{pri}">{pri}</span> <b>[{r.get("id","")}] {esc(r.get("target",""))}</b><br>{esc(r.get("recommendation",""))}</div>')
parts.append(f"<h3>Metrics ({len(markers.get('metrics',[]))})</h3>")
for m in markers.get("metrics", []):
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

