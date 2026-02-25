#!/usr/bin/env python3
"""
Full Pipeline Schematic Generator — ELK.js Layered DAG Layout
=============================================================

Produces hyperdocs-full-schematic.html: a self-contained, interactive SVG
schematic of the entire Hyperdocs pipeline (all scripts, data files, edges)
using ELK.js for automatic hierarchical layout.

Uses hand-curated I/O manifests (_io_phase0.py, _io_phase1_2.py,
_io_phase3_4.py, _io_tools.py) produced by reading every pipeline script
line by line.

Layout strategy:
  - Flat ELK graph for layout (avoids edge-ownership hierarchy issues)
  - Phase/sub-cluster boxes rendered as visual overlays after layout
  - Session Data Bus: high-fanout data files routed through a shared bus bar
  - ELK.js handles layer assignment, edge crossing minimization, edge routing

Output: {REPO_ROOT}/hyperdocs-full-schematic.html

Usage:
    python3 tools/generate_full_schematic.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools._io_phase0 import PHASE0_IO
from tools._io_phase1_2 import PHASE1_2_IO
from tools._io_phase3_4 import PHASE3_4_IO
from tools._io_tools import TOOLS_IO
from tools.generate_pipeline_canvas_data import normalize_data_path, is_pipeline_data
from tools.generate_schematic import PHASE_MAP, OPTIONAL_SCRIPTS

# ── Merge all manifests ─────────────────────────────────────────────
COMPLETE_IO = {}
COMPLETE_IO.update(PHASE0_IO)
COMPLETE_IO.update(PHASE1_2_IO)
COMPLETE_IO.update(PHASE3_4_IO)
COMPLETE_IO.update(TOOLS_IO)

# ── Phase configuration ─────────────────────────────────────────────

PHASE_LABELS = {
    "0":     "Phase 0: Deterministic Prep",
    "1":     "Phase 1: Extraction",
    "2":     "Phase 2: Synthesis",
    "3":     "Phase 3: Evidence + Dossiers",
    "4a":    "Phase 4a: Cross-Session Aggregation",
    "4b":    "Phase 4b: Hyperdoc Insertion",
    "tools": "Tools / Utilities",
}

PHASE_COLORS = {
    "0":     "#22d3ee",
    "1":     "#a78bfa",
    "2":     "#4ade80",
    "3":     "#fbbf24",
    "4a":    "#f87171",
    "4b":    "#fb923c",
    "tools": "#6b7280",
}

PHASE_ORDER = ["0", "1", "2", "3", "4a", "4b", "tools"]

# ── Sub-cluster assignments ─────────────────────────────────────────

SUB_CLUSTERS = {
    # Phase 0
    "phase_0_prep/enrich_session.py":            ("0", "Core"),
    "phase_0_prep/prepare_agent_data.py":        ("0", "Core"),
    "phase_0_prep/llm_pass_runner.py":           ("0", "LLM Passes"),
    "phase_0_prep/merge_llm_results.py":         ("0", "LLM Passes"),
    "phase_0_prep/prompts.py":                   ("0", "LLM Passes"),
    "phase_0_prep/batch_p0_llm.py":              ("0", "LLM Passes"),
    "phase_0_prep/opus_classifier.py":           ("0", "Opus Path"),
    "phase_0_prep/build_opus_messages.py":       ("0", "Opus Path"),
    "phase_0_prep/claude_session_reader.py":     ("0", "Libraries"),
    "phase_0_prep/geological_reader.py":         ("0", "Libraries"),
    "phase_0_prep/claude_behavior_analyzer.py":  ("0", "Libraries"),
    "phase_0_prep/message_filter.py":            ("0", "Libraries"),
    "phase_0_prep/metadata_extractor.py":        ("0", "Libraries"),
    "phase_0_prep/code_similarity.py":           ("0", "Libraries"),
    "phase_0_prep/batch_phase0_reprocess.py":    ("0", "Batch"),
    # Phase 1
    "phase_1_extraction/opus_phase1.py":               ("1", "Primary"),
    "phase_1_extraction/extract_threads.py":           ("1", "Fallback"),
    "phase_1_extraction/tag_semantic_primitives.py":   ("1", "Fallback"),
    "phase_1_extraction/batch_p1_llm.py":              ("1", "Batch"),
    "phase_1_extraction/interactive_batch_runner.py":  ("1", "Batch"),
    # Phase 2
    "phase_2_synthesis/backfill_phase2.py":   ("2", "Synthesis"),
    "phase_2_synthesis/file_genealogy.py":    ("2", "Synthesis"),
    "phase_2_synthesis/code_similarity.py":   ("2", "Synthesis"),
    # Phase 3
    "phase_3_hyperdoc_writing/collect_file_evidence.py":  ("3", "Evidence Collection"),
    "phase_3_hyperdoc_writing/evidence_resolver.py":      ("3", "Evidence Collection"),
    "phase_3_hyperdoc_writing/evidence/base.py":          ("3", "Evidence Collection"),
    "phase_3_hyperdoc_writing/evidence/debug_sequence.py":       ("3", "Evidence Renderers"),
    "phase_3_hyperdoc_writing/evidence/decision_trace.py":       ("3", "Evidence Renderers"),
    "phase_3_hyperdoc_writing/evidence/emotional_arc.py":        ("3", "Evidence Renderers"),
    "phase_3_hyperdoc_writing/evidence/file_timeline.py":        ("3", "Evidence Renderers"),
    "phase_3_hyperdoc_writing/evidence/geological_event.py":     ("3", "Evidence Renderers"),
    "phase_3_hyperdoc_writing/evidence/idea_transition.py":      ("3", "Evidence Renderers"),
    "phase_3_hyperdoc_writing/evidence/reaction_log.py":         ("3", "Evidence Renderers"),
    "phase_3_hyperdoc_writing/generate_dossiers.py":   ("3", "Output"),
    "phase_3_hyperdoc_writing/generate_viewer.py":     ("3", "Output"),
    "phase_3_hyperdoc_writing/write_hyperdocs.py":     ("3", "Output"),
    "phase_3_hyperdoc_writing/write_more_hyperdocs.py": ("3", "Output"),
    # Phase 4a
    "phase_4a_aggregation/aggregate_dossiers.py": ("4a", "Aggregation"),
    # Phase 4b
    "phase_4_insertion/insert_hyperdocs_v2.py":  ("4b", "Insertion"),
    "phase_4_insertion/insert_hyperdocs.py":     ("4b", "Insertion"),
    "phase_4_insertion/insert_from_phase4b.py":  ("4b", "Insertion"),
    "phase_4_insertion/hyperdoc_layers.py":      ("4b", "Insertion"),
    # Tools — Orchestrators
    "tools/run_pipeline.py":    ("tools", "Orchestrators"),
    "tools/batch_runner.py":    ("tools", "Orchestrators"),
    "tools/batch_phase3a.py":   ("tools", "Orchestrators"),
    # Tools — Validators
    "tools/schema_normalizer.py":       ("tools", "Validators"),
    "tools/schema_validator.py":        ("tools", "Validators"),
    "tools/normalize_agent_output.py":  ("tools", "Validators"),
    "tools/schema_contracts.py":        ("tools", "Validators"),
    # Tools — Scanners
    "tools/completeness_scanner.py":     ("tools", "Scanners"),
    "tools/pipeline_health_check.py":    ("tools", "Scanners"),
    "tools/pipeline_status.py":          ("tools", "Scanners"),
    "tools/data_lifecycle.py":           ("tools", "Scanners"),
    "tools/verify_data_locations.py":    ("tools", "Scanners"),
    # Tools — Generators
    "tools/generate_schematic.py":              ("tools", "Generators"),
    "tools/generate_pipeline_canvas_data.py":   ("tools", "Generators"),
    "tools/generate_pipeline_excel.py":         ("tools", "Generators"),
    "tools/extract_dashboard_data.py":          ("tools", "Generators"),
    "tools/add_data_trace_sheets.py":           ("tools", "Generators"),
    "tools/analyze_data_flow.py":               ("tools", "Generators"),
    "tools/collect_visualizations.py":          ("tools", "Generators"),
    "tools/hyperdoc_comparison.py":             ("tools", "Generators"),
    # Tools — Utilities
    "config.py":              ("tools", "Utilities"),
    "tools/json_io.py":       ("tools", "Utilities"),
    "tools/log_config.py":    ("tools", "Utilities"),
    "tools/file_lock.py":     ("tools", "Utilities"),
}

# ── Session Data Bus members ────────────────────────────────────────

BUS_DATA_FILES = {
    "enriched_session.json",
    "session_metadata.json",
    "thread_extractions.json",
    "geological_notes.json",
    "semantic_primitives.json",
    "explorer_notes.json",
    "idea_graph.json",
    "synthesis.json",
    "grounded_markers.json",
}


def get_phase_id(rel_path):
    """Determine phase ID from a script's relative path."""
    for dir_prefix, phase_id in PHASE_MAP.items():
        if rel_path.startswith(dir_prefix):
            return phase_id
    if rel_path.startswith("tools/") or rel_path == "config.py":
        return "tools"
    return "tools"


def extract_io(entry):
    """Extract normalized reads/writes from a manifest entry."""
    raw_reads = entry.get("reads", entry.get("READS", []))
    raw_writes = entry.get("writes", entry.get("WRITES", []))

    reads = []
    for r in raw_reads:
        norm = normalize_data_path(r)
        if is_pipeline_data(norm):
            reads.append(norm)

    writes = []
    for w in raw_writes:
        norm = normalize_data_path(w)
        if is_pipeline_data(norm):
            writes.append(norm)

    return sorted(set(reads)), sorted(set(writes))


def safe_id(name):
    """Make a string safe for use as a JS/ELK node ID."""
    return (name.replace("/", "_").replace(".", "_").replace("*", "x")
            .replace("{", "").replace("}", "").replace(" ", "_")
            .replace("-", "_").replace("(", "").replace(")", ""))


def build_graph_data():
    """Build the complete graph data structure for the schematic."""
    scripts = {}
    all_data_files = set()
    writers = {}   # data_file -> [script_ids]
    readers = {}   # data_file -> [script_ids]

    for rel_path, entry in COMPLETE_IO.items():
        reads, writes = extract_io(entry)
        phase_id = get_phase_id(rel_path)

        if rel_path in SUB_CLUSTERS:
            _, sub_cluster = SUB_CLUSTERS[rel_path]
        else:
            sub_cluster = "Other"

        is_optional = rel_path in OPTIONAL_SCRIPTS
        is_evidence_renderer = ("evidence/" in rel_path
                                and rel_path != "phase_3_hyperdoc_writing/evidence/base.py")

        scripts[rel_path] = {
            "id": safe_id(rel_path),
            "label": Path(rel_path).name,
            "rel_path": rel_path,
            "phase_id": phase_id,
            "sub_cluster": sub_cluster,
            "reads": reads,
            "writes": writes,
            "optional": is_optional,
            "is_evidence_renderer": is_evidence_renderer,
        }

        for f in writes:
            all_data_files.add(f)
            writers.setdefault(f, []).append(rel_path)
        for f in reads:
            all_data_files.add(f)
            readers.setdefault(f, []).append(rel_path)

    # Build data file nodes
    data_files = {}
    for fname in sorted(all_data_files):
        is_bus = fname in BUS_DATA_FILES
        phase_id = "tools"
        if fname in writers:
            first_writer = writers[fname][0]
            phase_id = get_phase_id(first_writer)

        data_files[fname] = {
            "id": safe_id(f"data_{fname}"),
            "label": fname,
            "phase_id": phase_id,
            "is_bus": is_bus,
            "writer_count": len(writers.get(fname, [])),
            "reader_count": len(readers.get(fname, [])),
            "total_connections": len(writers.get(fname, [])) + len(readers.get(fname, [])),
        }

    # Build edges
    direct_edges = []
    bus_write_edges = []
    bus_read_edges = []

    for fname, writer_ids in writers.items():
        data_node = data_files.get(fname)
        if not data_node:
            continue
        for script_id in writer_ids:
            script = scripts.get(script_id)
            if not script:
                continue
            edge = {
                "source": script["id"],
                "target": data_node["id"],
                "type": "write",
                "data_file": fname,
                "source_phase": script["phase_id"],
            }
            if data_node["is_bus"]:
                bus_write_edges.append(edge)
            else:
                direct_edges.append(edge)

    for fname, reader_ids in readers.items():
        data_node = data_files.get(fname)
        if not data_node:
            continue
        for script_id in reader_ids:
            script = scripts.get(script_id)
            if not script:
                continue
            edge = {
                "source": data_node["id"],
                "target": script["id"],
                "type": "read",
                "data_file": fname,
                "target_phase": script["phase_id"],
                "cross_phase": data_node["phase_id"] != script["phase_id"],
            }
            if data_node["is_bus"]:
                bus_read_edges.append(edge)
            else:
                direct_edges.append(edge)

    return {
        "scripts": scripts,
        "data_files": data_files,
        "direct_edges": direct_edges,
        "bus_write_edges": bus_write_edges,
        "bus_read_edges": bus_read_edges,
        "writers": writers,
        "readers": readers,
    }


def build_elk_graph(graph_data):
    """Build a flat ELK graph — all nodes at root level, edges at root.

    ELK's bundled JS requires edges to be owned by the LCA of their endpoints.
    With a flat graph, all edges are at root level, avoiding hierarchy issues.
    Phase/cluster groupings are rendered visually after layout using node metadata.
    """
    scripts = graph_data["scripts"]
    data_files = graph_data["data_files"]

    # Collect evidence renderer scripts for collapsed group node
    evidence_renderers = [s for s in scripts.values() if s["is_evidence_renderer"]]
    evidence_renderer_ids = {s["id"] for s in evidence_renderers}

    children = []

    # Script nodes (skip individual evidence renderers — they get a group node)
    for rel_path, script in scripts.items():
        if script["id"] in evidence_renderer_ids:
            continue
        children.append({
            "id": script["id"],
            "width": 220,
            "height": 40,
            "labels": [{"text": script["label"]}],
        })

    # Evidence renderers collapsed group node
    if evidence_renderers:
        children.append({
            "id": "evidence_renderers_group",
            "width": 240,
            "height": 40,
            "labels": [{"text": f"Evidence Renderers ({len(evidence_renderers)})"}],
        })

    # Non-bus data file nodes
    for fname, df in data_files.items():
        if df["is_bus"]:
            continue
        children.append({
            "id": df["id"],
            "width": 200,
            "height": 32,
            "labels": [{"text": df["label"]}],
        })

    # Bus data file nodes
    for fname, df in data_files.items():
        if not df["is_bus"]:
            continue
        children.append({
            "id": df["id"],
            "width": 200,
            "height": 32,
            "labels": [{"text": df["label"]}],
        })

    # Build all edges at root level
    edges = []
    eid = 0

    def add_edge(src, tgt, etype, data_file):
        nonlocal eid
        # Remap evidence renderer edges to group node
        if src in evidence_renderer_ids:
            src = "evidence_renderers_group"
        if tgt in evidence_renderer_ids:
            tgt = "evidence_renderers_group"
        edges.append({
            "id": f"e{eid}",
            "sources": [src],
            "targets": [tgt],
        })
        eid += 1

    for e in graph_data["direct_edges"]:
        add_edge(e["source"], e["target"], e["type"], e["data_file"])
    for e in graph_data["bus_write_edges"]:
        add_edge(e["source"], e["target"], "bus_write", e["data_file"])
    for e in graph_data["bus_read_edges"]:
        add_edge(e["source"], e["target"], "bus_read", e["data_file"])

    # Deduplicate edges (evidence renderer remapping may cause dupes)
    seen = set()
    unique_edges = []
    for edge in edges:
        key = (edge["sources"][0], edge["targets"][0])
        if key not in seen and key[0] != key[1]:
            seen.add(key)
            unique_edges.append(edge)

    # Re-number
    for i, edge in enumerate(unique_edges):
        edge["id"] = f"e{i}"

    return {
        "id": "root",
        "children": children,
        "edges": unique_edges,
        "layoutOptions": {
            "elk.algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.spacing.nodeNode": "20",
            "elk.spacing.edgeNode": "16",
            "elk.spacing.edgeEdge": "10",
            "elk.layered.spacing.nodeNodeBetweenLayers": "60",
            "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
            "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
            "elk.padding": "[top=30,left=30,bottom=30,right=30]",
            "elk.edgeRouting": "ORTHOGONAL",
        },
    }


def build_node_metadata(graph_data):
    """Build metadata dicts for the JS side: node info, groupings, edge types."""
    scripts = graph_data["scripts"]
    data_files = graph_data["data_files"]

    evidence_renderers = [s for s in scripts.values() if s["is_evidence_renderer"]]
    evidence_renderer_ids = {s["id"] for s in evidence_renderers}

    # Node info for info panel
    node_info = {}
    for rel_path, s in scripts.items():
        nid = s["id"]
        if nid in evidence_renderer_ids:
            continue
        node_info[nid] = {
            "label": s["label"],
            "relPath": rel_path,
            "phase": s["phase_id"],
            "cluster": s["sub_cluster"],
            "reads": s["reads"],
            "writes": s["writes"],
            "optional": s["optional"],
            "nodeType": "script",
        }
    # Evidence renderers group
    if evidence_renderers:
        node_info["evidence_renderers_group"] = {
            "label": f"Evidence Renderers ({len(evidence_renderers)})",
            "relPath": "phase_3_hyperdoc_writing/evidence/*",
            "phase": "3",
            "cluster": "Evidence Renderers",
            "reads": [],
            "writes": [],
            "optional": False,
            "nodeType": "evidence_group",
            "children": [s["rel_path"] for s in evidence_renderers],
        }

    for fname, df in data_files.items():
        node_info[df["id"]] = {
            "label": df["label"],
            "phase": df["phase_id"],
            "isBus": df["is_bus"],
            "writerCount": df["writer_count"],
            "readerCount": df["reader_count"],
            "writers": graph_data["writers"].get(fname, []),
            "readers": graph_data["readers"].get(fname, []),
            "nodeType": "bus_data" if df["is_bus"] else "data",
        }

    # Edge type lookup (for rendering styles)
    edge_types = {}
    for e in graph_data["direct_edges"]:
        edge_types[(e["source"], e["target"])] = e["type"]
    for e in graph_data["bus_write_edges"]:
        # Remap evidence renderer sources
        src = e["source"]
        if src in evidence_renderer_ids:
            src = "evidence_renderers_group"
        edge_types[(src, e["target"])] = "bus_write"
    for e in graph_data["bus_read_edges"]:
        tgt = e["target"]
        if tgt in evidence_renderer_ids:
            tgt = "evidence_renderers_group"
        edge_types[(e["source"], tgt)] = "bus_read"

    # Phase/cluster grouping for visual overlays
    grouping = {}
    for rel_path, s in scripts.items():
        nid = s["id"]
        if nid in evidence_renderer_ids:
            nid = "evidence_renderers_group"
        grouping[nid] = {
            "phase": s["phase_id"],
            "cluster": s["sub_cluster"],
        }
    for fname, df in data_files.items():
        grouping[df["id"]] = {
            "phase": df["phase_id"] if not df["is_bus"] else "bus",
            "cluster": "Bus" if df["is_bus"] else "Data",
        }

    return node_info, edge_types, grouping


def generate_html(elk_graph, graph_data):
    """Generate the self-contained HTML file."""
    now = datetime.now().strftime("%b %d, %Y %H:%M")
    scripts = graph_data["scripts"]
    data_files = graph_data["data_files"]

    evidence_renderers = [s for s in scripts.values() if s["is_evidence_renderer"]]
    evidence_renderer_ids = {s["id"] for s in evidence_renderers}
    effective_script_count = len(scripts) - len(evidence_renderers) + (1 if evidence_renderers else 0)

    total_edges = len(elk_graph["edges"])

    node_info, edge_types, grouping = build_node_metadata(graph_data)

    # Convert edge_types to serializable form
    edge_type_list = {}
    for (src, tgt), etype in edge_types.items():
        edge_type_list[f"{src}|{tgt}"] = etype

    graph_json = json.dumps(elk_graph)
    node_info_json = json.dumps(node_info)
    edge_type_json = json.dumps(edge_type_list)
    grouping_json = json.dumps(grouping)
    phase_colors_json = json.dumps(PHASE_COLORS)
    phase_labels_json = json.dumps(PHASE_LABELS)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hyperdocs Full Pipeline Schematic</title>
<style>
:root {{
  --bg: #0d1117;
  --surface: #161b22;
  --surface2: #1c2333;
  --border: rgba(255,255,255,0.08);
  --border-hi: rgba(255,255,255,0.2);
  --text: #e6edf3;
  --text-dim: #8b949e;
  --text-muted: #484f58;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --mono: 'SF Mono', 'Fira Code', Consolas, monospace;
}}
/* Dark mode only — designed for dark backgrounds */
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--text); font-family:var(--font); overflow:hidden; height:100vh; }}
header {{
  background:var(--surface); border-bottom:1px solid var(--border);
  padding:8px 16px; display:flex; justify-content:space-between; align-items:center;
  z-index:100; position:relative;
}}
header h1 {{ font-size:15px; font-weight:600; }}
header .stats {{ font-size:11px; color:var(--text-dim); margin-top:2px; }}
.controls {{ display:flex; align-items:center; gap:6px; }}
.controls button {{
  padding:4px 10px; border:1px solid var(--border); background:var(--surface2);
  color:var(--text-dim); font-size:11px; font-family:var(--mono); border-radius:4px;
  cursor:pointer; transition:all 0.15s;
}}
.controls button:hover {{ border-color:var(--border-hi); color:var(--text); }}
.controls button.active {{ background:#1a6bff22; border-color:#1a6bff88; color:#58a6ff; }}
.zbtn {{ width:28px; padding:4px !important; text-align:center; }}
#canvas {{
  width:100%; height:calc(100vh - 52px); overflow:hidden; position:relative; cursor:grab;
}}
#canvas.panning {{ cursor:grabbing; }}
#canvas svg {{ position:absolute; top:0; left:0; }}
/* Dimming */
.dimmed {{ opacity:0.06 !important; }}
.hi {{ opacity:1 !important; }}
.hi-edge {{ opacity:1 !important; stroke-width:2.5 !important; }}
/* Info panel */
#info {{
  position:fixed; right:12px; top:64px; width:320px; background:var(--surface);
  border:1px solid var(--border-hi); border-radius:8px; padding:12px; font-size:12px;
  z-index:200; display:none; box-shadow:0 4px 16px rgba(0,0,0,.3);
  max-height:calc(100vh - 80px); overflow-y:auto;
}}
#info.vis {{ display:block; }}
#info h3 {{ font-size:13px; margin-bottom:6px; font-family:var(--mono); }}
#info .m {{ color:var(--text-dim); margin-bottom:3px; font-size:11px; }}
#info .fl {{ margin-top:6px; }}
#info .fl span {{
  display:inline-block; background:var(--surface2); border:1px solid var(--border);
  border-radius:3px; padding:1px 5px; margin:2px; font-family:var(--mono); font-size:10px;
}}
#info .x {{ position:absolute; top:8px; right:8px; background:none; border:none;
  color:var(--text-dim); cursor:pointer; font-size:14px; }}
/* Legend */
#legend {{
  position:fixed; left:12px; bottom:12px; background:var(--surface);
  border:1px solid var(--border); border-radius:8px; padding:8px 12px;
  font-size:10px; z-index:200; display:flex; gap:14px; opacity:0.9;
}}
.li {{ display:flex; align-items:center; gap:4px; color:var(--text-dim); }}
.sw {{ width:14px; height:9px; border-radius:2px; border:1px solid; display:inline-block; }}
.ln {{ width:18px; height:0; display:inline-block; }}
#loading {{
  position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
  font-size:14px; color:var(--text-dim); z-index:300;
}}
</style>
</head>
<body>
<header>
  <div>
    <h1>Hyperdocs Pipeline Schematic</h1>
    <div class="stats">{len(scripts)} scripts &middot; {len(data_files)} data files &middot; {total_edges} edges &middot; Generated {now}</div>
  </div>
  <div class="controls">
    <button id="bt" class="active" onclick="tog('tools')">Tools</button>
    <button id="bd" class="active" onclick="tog('data')">Data</button>
    <button id="bb" class="active" onclick="tog('bus')">Bus</button>
    <button class="zbtn" onclick="zi()">+</button>
    <button class="zbtn" onclick="zo()">&minus;</button>
    <button class="zbtn" onclick="zf()">&#8634;</button>
  </div>
</header>

<div id="canvas"></div>

<div id="info">
  <button class="x" onclick="ci()">&times;</button>
  <div id="ic"></div>
</div>

<div id="legend">
  <div class="li"><span class="sw" style="background:#22d3ee22;border-color:#22d3ee"></span>P0</div>
  <div class="li"><span class="sw" style="background:#a78bfa22;border-color:#a78bfa"></span>P1</div>
  <div class="li"><span class="sw" style="background:#4ade8022;border-color:#4ade80"></span>P2</div>
  <div class="li"><span class="sw" style="background:#fbbf2422;border-color:#fbbf24"></span>P3</div>
  <div class="li"><span class="sw" style="background:#f8717122;border-color:#f87171"></span>P4a</div>
  <div class="li"><span class="sw" style="background:#fb923c22;border-color:#fb923c"></span>P4b</div>
  <div class="li"><span class="ln" style="border-top:2px solid #8b949e"></span>Write</div>
  <div class="li"><span class="ln" style="border-top:2px dashed #fbbf24"></span>Read</div>
  <div class="li"><span class="ln" style="border-top:1.5px dotted #6b7280"></span>Bus</div>
</div>

<div id="loading">Laying out {effective_script_count} nodes + {len(data_files)} data files with ELK.js...</div>

<script src="https://cdn.jsdelivr.net/npm/elkjs@0.9.3/lib/elk.bundled.js"></script>
<script>
const G={graph_json};
const NI={node_info_json};
const ET={edge_type_json};
const GR={grouping_json};
const PC={phase_colors_json};
const PL={phase_labels_json};

let svgEl,tx=0,ty=0,sc=1,pan=false,px=0,py=0;
let show={{tools:true,data:true,bus:true}};

async function run(){{
  const elk=new ELK();
  try{{
    const laid=await elk.layout(G);
    render(laid);
    document.getElementById('loading').style.display='none';
    zf();
  }}catch(err){{
    document.getElementById('loading').textContent='Layout error: '+err.message;
    console.error(err);
  }}
}}

function render(laid){{
  const c=document.getElementById('canvas');
  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  const W=laid.width+40, H=laid.height+40;
  svg.setAttribute('width',W);
  svg.setAttribute('height',H);
  svg.setAttribute('viewBox',`0 0 ${{W}} ${{H}}`);

  // Defs
  const defs=document.createElementNS(ns,'defs');
  function mkArrow(id,fill){{
    const m=document.createElementNS(ns,'marker');
    m.setAttribute('id',id); m.setAttribute('viewBox','0 0 10 6');
    m.setAttribute('refX','10'); m.setAttribute('refY','3');
    m.setAttribute('markerWidth','7'); m.setAttribute('markerHeight','5');
    m.setAttribute('orient','auto');
    const p=document.createElementNS(ns,'path');
    p.setAttribute('d','M0,0 L10,3 L0,6 Z'); p.setAttribute('fill',fill);
    m.appendChild(p); defs.appendChild(m);
  }}
  mkArrow('aw','#8b949e');
  mkArrow('ar','#fbbf24');
  mkArrow('ab','#6b7280');
  svg.appendChild(defs);

  const mg=document.createElementNS(ns,'g');
  mg.setAttribute('id','mg');

  // Collect positions
  const pos={{}};
  for(const n of laid.children){{
    pos[n.id]={{x:n.x,y:n.y,w:n.width,h:n.height}};
  }}

  // Draw phase/cluster background boxes
  drawGroups(mg,ns,pos);

  // Draw edges first (behind nodes)
  const edgeG=document.createElementNS(ns,'g');
  edgeG.setAttribute('id','edges');
  if(laid.edges){{
    for(const e of laid.edges){{
      const src=e.sources[0], tgt=e.targets[0];
      const key=src+'|'+tgt;
      const etype=ET[key]||'write';
      const g=document.createElementNS(ns,'g');
      g.setAttribute('class','edge');
      g.setAttribute('data-src',src);
      g.setAttribute('data-tgt',tgt);
      g.setAttribute('data-type',etype);

      let d;
      if(e.sections&&e.sections.length>0){{
        const s=e.sections[0];
        d=`M${{s.startPoint.x}},${{s.startPoint.y}}`;
        if(s.bendPoints)for(const b of s.bendPoints)d+=` L${{b.x}},${{b.y}}`;
        d+=` L${{s.endPoint.x}},${{s.endPoint.y}}`;
      }}else{{
        const sp=pos[src], tp=pos[tgt];
        if(!sp||!tp)continue;
        d=`M${{sp.x+sp.w}},${{sp.y+sp.h/2}} L${{tp.x}},${{tp.y+tp.h/2}}`;
      }}

      const p=document.createElementNS(ns,'path');
      p.setAttribute('d',d);
      p.setAttribute('fill','none');

      if(etype==='write'){{
        const sph=(GR[src]||{{}}).phase||'';
        p.setAttribute('stroke',PC[sph]||'#8b949e');
        p.setAttribute('stroke-width','1.5');
        p.setAttribute('marker-end','url(#aw)');
      }}else if(etype==='read'){{
        p.setAttribute('stroke','#fbbf24');
        p.setAttribute('stroke-width','1');
        p.setAttribute('stroke-dasharray','5 3');
        p.setAttribute('marker-end','url(#ar)');
      }}else if(etype==='bus_write'){{
        const sph=(GR[src]||{{}}).phase||'';
        p.setAttribute('stroke',PC[sph]||'#8b949e');
        p.setAttribute('stroke-width','1.5');
        p.setAttribute('marker-end','url(#aw)');
      }}else if(etype==='bus_read'){{
        p.setAttribute('stroke','#6b7280');
        p.setAttribute('stroke-width','0.8');
        p.setAttribute('stroke-dasharray','3 3');
        p.setAttribute('opacity','0.4');
        p.setAttribute('marker-end','url(#ab)');
      }}

      g.appendChild(p);
      edgeG.appendChild(g);
    }}
  }}
  mg.appendChild(edgeG);

  // Draw nodes
  const nodeG=document.createElementNS(ns,'g');
  nodeG.setAttribute('id','nodes');
  for(const n of laid.children){{
    const info=NI[n.id]||{{}};
    const nt=info.nodeType||'script';
    const gr=GR[n.id]||{{}};
    const phase=gr.phase||'tools';
    const col=PC[phase]||'#6b7280';

    const g=document.createElementNS(ns,'g');
    g.setAttribute('data-id',n.id);
    g.setAttribute('data-phase',phase);
    g.setAttribute('data-type',nt);
    g.setAttribute('class','node');
    g.style.cursor='pointer';

    const rect=document.createElementNS(ns,'rect');
    rect.setAttribute('x',n.x);
    rect.setAttribute('y',n.y);
    rect.setAttribute('width',n.width);
    rect.setAttribute('height',n.height);

    if(nt==='script'){{
      rect.setAttribute('rx','3');
      rect.setAttribute('fill',col+'18');
      rect.setAttribute('stroke',col);
      rect.setAttribute('stroke-width','2');
      if(info.optional)rect.setAttribute('stroke-dasharray','5 3');
    }}else if(nt==='evidence_group'){{
      rect.setAttribute('rx','4');
      rect.setAttribute('fill',(PC['3']||'#fbbf24')+'12');
      rect.setAttribute('stroke',PC['3']||'#fbbf24');
      rect.setAttribute('stroke-width','1.5');
      rect.setAttribute('stroke-dasharray','4 2');
    }}else if(nt==='bus_data'){{
      rect.setAttribute('rx','12');
      rect.setAttribute('fill','var(--surface,#161b22)');
      rect.setAttribute('stroke','#fbbf24');
      rect.setAttribute('stroke-width','1.5');
    }}else{{
      rect.setAttribute('rx','12');
      rect.setAttribute('fill','var(--surface2,#1c2333)');
      rect.setAttribute('stroke','var(--text-muted,#484f58)');
      rect.setAttribute('stroke-width','1');
    }}

    g.appendChild(rect);

    const txt=document.createElementNS(ns,'text');
    txt.setAttribute('x',n.x+8);
    txt.setAttribute('y',n.y+n.height/2);
    txt.setAttribute('dominant-baseline','central');
    txt.setAttribute('font-family',"'SF Mono',Consolas,monospace");
    txt.setAttribute('pointer-events','none');

    const label=(n.labels&&n.labels[0])?n.labels[0].text:n.id;
    const maxCh=Math.floor((n.width-16)/7);
    txt.textContent=label.length>maxCh?label.slice(0,maxCh-2)+'..':label;

    if(nt==='bus_data'){{
      txt.setAttribute('font-size','10'); txt.setAttribute('fill','#fbbf24');
    }}else if(nt==='data'){{
      txt.setAttribute('font-size','10'); txt.setAttribute('fill','var(--text-dim,#8b949e)');
    }}else{{
      txt.setAttribute('font-size','11'); txt.setAttribute('fill','var(--text,#e6edf3)');
    }}

    g.appendChild(txt);

    g.addEventListener('mouseenter',()=>hl(n.id));
    g.addEventListener('mouseleave',()=>clr());
    g.addEventListener('click',(ev)=>{{ev.stopPropagation();si(n.id);}});

    nodeG.appendChild(g);
  }}
  mg.appendChild(nodeG);

  svg.appendChild(mg);
  c.innerHTML='';
  c.appendChild(svg);
  svgEl=svg;
  at();
}}

function drawGroups(mg,ns,pos){{
  // Compute bounding boxes per phase and per (phase,cluster)
  const phaseBB={{}};
  const clusterBB={{}};
  for(const[nid,gr] of Object.entries(GR)){{
    const p=pos[nid];
    if(!p)continue;
    const ph=gr.phase;
    const cl=gr.cluster;
    const pad=12;

    // Phase bounding box
    if(ph&&ph!=='bus'){{
      if(!phaseBB[ph])phaseBB[ph]={{x1:p.x-pad,y1:p.y-pad,x2:p.x+p.w+pad,y2:p.y+p.h+pad}};
      else{{
        phaseBB[ph].x1=Math.min(phaseBB[ph].x1,p.x-pad);
        phaseBB[ph].y1=Math.min(phaseBB[ph].y1,p.y-pad);
        phaseBB[ph].x2=Math.max(phaseBB[ph].x2,p.x+p.w+pad);
        phaseBB[ph].y2=Math.max(phaseBB[ph].y2,p.y+p.h+pad);
      }}
    }}

    // Bus bounding box
    if(ph==='bus'){{
      if(!phaseBB['bus'])phaseBB['bus']={{x1:p.x-pad,y1:p.y-pad,x2:p.x+p.w+pad,y2:p.y+p.h+pad}};
      else{{
        phaseBB['bus'].x1=Math.min(phaseBB['bus'].x1,p.x-pad);
        phaseBB['bus'].y1=Math.min(phaseBB['bus'].y1,p.y-pad);
        phaseBB['bus'].x2=Math.max(phaseBB['bus'].x2,p.x+p.w+pad);
        phaseBB['bus'].y2=Math.max(phaseBB['bus'].y2,p.y+p.h+pad);
      }}
    }}

    // Cluster bounding box (within phase)
    if(ph&&cl){{
      const ck=ph+'|'+cl;
      if(!clusterBB[ck])clusterBB[ck]={{x1:p.x-6,y1:p.y-6,x2:p.x+p.w+6,y2:p.y+p.h+6,phase:ph,cluster:cl}};
      else{{
        clusterBB[ck].x1=Math.min(clusterBB[ck].x1,p.x-6);
        clusterBB[ck].y1=Math.min(clusterBB[ck].y1,p.y-6);
        clusterBB[ck].x2=Math.max(clusterBB[ck].x2,p.x+p.w+6);
        clusterBB[ck].y2=Math.max(clusterBB[ck].y2,p.y+p.h+6);
      }}
    }}
  }}

  // Draw phase backgrounds
  for(const[ph,bb] of Object.entries(phaseBB)){{
    const col=PC[ph]||'#6b7280';
    const g=document.createElementNS(ns,'g');
    g.setAttribute('class','phase-grp');
    g.setAttribute('data-phase',ph);

    const rect=document.createElementNS(ns,'rect');
    rect.setAttribute('x',bb.x1-8);
    rect.setAttribute('y',bb.y1-24);
    rect.setAttribute('width',bb.x2-bb.x1+16);
    rect.setAttribute('height',bb.y2-bb.y1+32);
    rect.setAttribute('rx','8');
    rect.setAttribute('fill',col+'12');
    rect.setAttribute('stroke',col+'50');
    rect.setAttribute('stroke-width','1.5');
    g.appendChild(rect);

    const lbl=document.createElementNS(ns,'text');
    lbl.setAttribute('x',bb.x1);
    lbl.setAttribute('y',bb.y1-12);
    lbl.setAttribute('font-size','13');
    lbl.setAttribute('font-weight','700');
    lbl.setAttribute('font-family',"var(--font)");
    lbl.setAttribute('fill',col);
    lbl.setAttribute('letter-spacing','0.5');
    lbl.textContent=ph==='bus'?'Core Session Data Bus':(PL[ph]||('Phase '+ph));
    g.appendChild(lbl);

    mg.appendChild(g);
  }}

  // Draw cluster outlines (subtle)
  for(const[ck,bb] of Object.entries(clusterBB)){{
    const col=PC[bb.phase]||'#6b7280';
    const rect=document.createElementNS(ns,'rect');
    rect.setAttribute('x',bb.x1-4);
    rect.setAttribute('y',bb.y1-14);
    rect.setAttribute('width',bb.x2-bb.x1+8);
    rect.setAttribute('height',bb.y2-bb.y1+18);
    rect.setAttribute('rx','4');
    rect.setAttribute('fill',col+'06');
    rect.setAttribute('stroke',col+'28');
    rect.setAttribute('stroke-width','0.8');
    rect.setAttribute('stroke-dasharray','4 3');
    mg.appendChild(rect);

    const lbl=document.createElementNS(ns,'text');
    lbl.setAttribute('x',bb.x1);
    lbl.setAttribute('y',bb.y1-4);
    lbl.setAttribute('font-size','10');
    lbl.setAttribute('font-weight','600');
    lbl.setAttribute('font-family',"var(--font)");
    lbl.setAttribute('fill',col+'70');
    lbl.setAttribute('letter-spacing','0.3');
    lbl.textContent=bb.cluster;
    mg.appendChild(lbl);
  }}
}}

// ── Highlight ───────────────────────────────────────────────
function hl(nid){{
  const nodes=document.querySelectorAll('.node');
  const edges=document.querySelectorAll('.edge');
  const conn=new Set([nid]);
  edges.forEach(e=>{{
    const s=e.getAttribute('data-src'),t=e.getAttribute('data-tgt');
    if(s===nid||t===nid){{conn.add(s);conn.add(t);e.classList.add('hi-edge');e.classList.remove('dimmed');}}
    else{{e.classList.add('dimmed');e.classList.remove('hi-edge');}}
  }});
  nodes.forEach(n=>{{
    const id=n.getAttribute('data-id');
    if(conn.has(id)){{n.classList.add('hi');n.classList.remove('dimmed');}}
    else{{n.classList.add('dimmed');n.classList.remove('hi');}}
  }});
}}
function clr(){{
  document.querySelectorAll('.dimmed').forEach(e=>e.classList.remove('dimmed'));
  document.querySelectorAll('.hi').forEach(e=>e.classList.remove('hi'));
  document.querySelectorAll('.hi-edge').forEach(e=>e.classList.remove('hi-edge'));
}}

// ── Info panel ──────────────────────────────────────────────
function si(nid){{
  const p=document.getElementById('info'),c=document.getElementById('ic');
  const i=NI[nid];
  if(!i){{c.innerHTML='<div class="m">No info for '+nid+'</div>';p.classList.add('vis');return;}}
  let h='<h3>'+i.label+'</h3>';
  if(i.nodeType==='script'||i.nodeType==='evidence_group'){{
    h+='<div class="m">Phase: '+i.phase+' &middot; '+i.cluster+'</div>';
    h+='<div class="m">'+i.relPath+'</div>';
    if(i.optional)h+='<div class="m" style="color:#fbbf24">Optional</div>';
    if(i.children)h+='<div class="fl"><strong>Contains:</strong><br>'+i.children.map(c=>'<span>'+c.split('/').pop()+'</span>').join('')+'</div>';
    if(i.reads&&i.reads.length)h+='<div class="fl"><strong>Reads:</strong><br>'+i.reads.map(f=>'<span>'+f+'</span>').join('')+'</div>';
    if(i.writes&&i.writes.length)h+='<div class="fl"><strong>Writes:</strong><br>'+i.writes.map(f=>'<span>'+f+'</span>').join('')+'</div>';
  }}else{{
    h+='<div class="m">Phase: '+i.phase+(i.isBus?' &middot; Bus Member':'')+'</div>';
    h+='<div class="m">Writers: '+i.writerCount+' &middot; Readers: '+i.readerCount+'</div>';
    if(i.writers&&i.writers.length)h+='<div class="fl"><strong>Written by:</strong><br>'+i.writers.map(f=>'<span>'+f.split('/').pop()+'</span>').join('')+'</div>';
    if(i.readers&&i.readers.length)h+='<div class="fl"><strong>Read by:</strong><br>'+i.readers.map(f=>'<span>'+f.split('/').pop()+'</span>').join('')+'</div>';
  }}
  c.innerHTML=h;p.classList.add('vis');
}}
function ci(){{document.getElementById('info').classList.remove('vis');}}

// ── Toggle ──────────────────────────────────────────────────
function tog(what){{
  show[what]=!show[what];
  const btnMap={{tools:'bt',data:'bd',bus:'bb'}};
  document.getElementById(btnMap[what]).classList.toggle('active',show[what]);

  if(what==='tools'){{
    document.querySelectorAll('.node[data-phase="tools"]').forEach(n=>n.style.display=show.tools?'':'none');
    document.querySelectorAll('.phase-grp[data-phase="tools"]').forEach(n=>n.style.display=show.tools?'':'none');
  }}
  if(what==='data'){{
    document.querySelectorAll('.node[data-type="data"]').forEach(n=>n.style.display=show.data?'':'none');
  }}
  if(what==='bus'){{
    document.querySelectorAll('.node[data-type="bus_data"]').forEach(n=>n.style.display=show.bus?'':'none');
    document.querySelectorAll('.phase-grp[data-phase="bus"]').forEach(n=>n.style.display=show.bus?'':'none');
  }}
  // Update edge visibility
  document.querySelectorAll('.edge').forEach(e=>{{
    const t=e.getAttribute('data-type');
    const s=e.getAttribute('data-src'),tg=e.getAttribute('data-tgt');
    let vis=true;
    if(!show.bus&&(t==='bus_write'||t==='bus_read'))vis=false;
    if(!show.data&&(t==='write'||t==='read'))vis=false;
    if(!show.tools){{
      const sn=document.querySelector('.node[data-id="'+s+'"]');
      const tn=document.querySelector('.node[data-id="'+tg+'"]');
      if((sn&&sn.getAttribute('data-phase')==='tools')||(tn&&tn.getAttribute('data-phase')==='tools'))vis=false;
    }}
    e.style.display=vis?'':'none';
  }});
}}

// ── Pan & Zoom ──────────────────────────────────────────────
function at(){{
  if(!svgEl)return;
  svgEl.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{sc}})`;
  svgEl.style.transformOrigin='0 0';
}}
function zi(){{sc=Math.min(sc*1.3,5);at();}}
function zo(){{sc=Math.max(sc/1.3,0.05);at();}}
function zf(){{
  if(!svgEl)return;
  const cv=document.getElementById('canvas');
  const cw=cv.clientWidth,ch=cv.clientHeight;
  const sw=parseFloat(svgEl.getAttribute('width'))||cw;
  const sh=parseFloat(svgEl.getAttribute('height'))||ch;
  sc=Math.min(cw/sw,ch/sh)*0.92;
  tx=(cw-sw*sc)/2; ty=(ch-sh*sc)/2;
  at();
}}

const cv=document.getElementById('canvas');
cv.addEventListener('mousedown',e=>{{
  if(e.target.closest('.node'))return;
  pan=true; px=e.clientX-tx; py=e.clientY-ty; cv.classList.add('panning');
}});
window.addEventListener('mousemove',e=>{{
  if(!pan)return; tx=e.clientX-px; ty=e.clientY-py; at();
}});
window.addEventListener('mouseup',()=>{{pan=false;cv.classList.remove('panning');}});
cv.addEventListener('wheel',e=>{{
  e.preventDefault();
  const f=e.deltaY<0?1.1:0.9;
  const r=cv.getBoundingClientRect();
  const mx=e.clientX-r.left, my=e.clientY-r.top;
  const ns=Math.min(Math.max(sc*f,0.05),5);
  tx=mx-(mx-tx)*(ns/sc); ty=my-(my-ty)*(ns/sc); sc=ns; at();
}},{{passive:false}});
cv.addEventListener('click',e=>{{if(!e.target.closest('.node'))ci();}});

document.addEventListener('keydown',e=>{{
  if(e.key==='Escape')ci();
  if(e.key==='t')tog('tools');
  if(e.key==='d')tog('data');
  if(e.key==='b')tog('bus');
  if(e.key==='+'||e.key==='=')zi();
  if(e.key==='-')zo();
  if(e.key==='0')zf();
}});

run();
</script>
</body>
</html>"""
    return html


def main():
    print("Building graph from I/O manifests...")
    graph_data = build_graph_data()

    scripts = graph_data["scripts"]
    data_files = graph_data["data_files"]
    direct = graph_data["direct_edges"]
    bus_w = graph_data["bus_write_edges"]
    bus_r = graph_data["bus_read_edges"]

    print(f"  Scripts:      {len(scripts)}")
    print(f"  Data files:   {len(data_files)}")
    print(f"    Bus:        {sum(1 for d in data_files.values() if d['is_bus'])}")
    print(f"    Direct:     {sum(1 for d in data_files.values() if not d['is_bus'])}")
    print(f"  Edges:")
    print(f"    Direct:     {len(direct)}")
    print(f"    Bus write:  {len(bus_w)}")
    print(f"    Bus read:   {len(bus_r)}")
    print(f"    Total:      {len(direct) + len(bus_w) + len(bus_r)}")

    phase_counts = {}
    for s in scripts.values():
        phase_counts.setdefault(s["phase_id"], 0)
        phase_counts[s["phase_id"]] += 1
    for pid in PHASE_ORDER:
        if pid in phase_counts:
            print(f"  {PHASE_LABELS.get(pid, pid)}: {phase_counts[pid]} scripts")

    print("\nBuilding ELK graph (flat layout)...")
    elk_graph = build_elk_graph(graph_data)
    print(f"  ELK nodes:  {len(elk_graph['children'])}")
    print(f"  ELK edges:  {len(elk_graph['edges'])}")

    print("Generating HTML...")
    html = generate_html(elk_graph, graph_data)

    out_path = REPO_ROOT / "hyperdocs-full-schematic.html"
    out_path.write_text(html)
    print(f"\nWrote: {out_path}")
    print(f"  Size: {len(html):,} bytes")


if __name__ == "__main__":
    main()
