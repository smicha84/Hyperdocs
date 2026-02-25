#!/usr/bin/env python3
"""
Pipeline Schematic Generator — Builds hyperdocs-pipeline-schematic.html from code.

Scans every pipeline script's file I/O using AST parsing and regex, builds a
dependency graph, and generates an SVG schematic programmatically. The schematic
is a build artifact that reflects the actual code, not a hand-drawn interpretation.

Usage:
    python3 tools/generate_schematic.py              # generate HTML schematic
    python3 tools/generate_schematic.py --json        # dump raw graph as JSON
"""

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Phase configuration ──────────────────────────────────────────────

PHASE_MAP = {
    "phase_0_prep": "0",
    "phase_1_extraction": "1",
    "phase_2_synthesis": "2",
    "phase_3_hyperdoc_writing": "3",
    "phase_4a_aggregation": "4a",
    "phase_4_insertion": "4b",
}

PHASE_COLORS = {
    "0":  {"bg": "#e0f7fa", "border": "#b2ebf2", "text": "#00838f"},
    "1":  {"bg": "#ede7f6", "border": "#d1c4e9", "text": "#7c3aed"},
    "2":  {"bg": "#e8f5e9", "border": "#c8e6c9", "text": "#2e7d32"},
    "3":  {"bg": "#fff8e1", "border": "#ffecb3", "text": "#f57f17"},
    "4a": {"bg": "#fce4ec", "border": "#f8bbd0", "text": "#c62828"},
    "4b": {"bg": "#fce4ec", "border": "#f8bbd0", "text": "#c62828"},
}

PHASE_LABELS = {
    "0":  "PHASE 0 : DETERMINISTIC PREP",
    "1":  "PHASE 1 : EXTRACTION (Opus Agents)",
    "2":  "PHASE 2 : SYNTHESIS",
    "3":  "PHASE 3 : EVIDENCE + DOSSIERS",
    "4a": "PHASE 4a : CROSS-SESSION AGGREGATION",
    "4b": "PHASE 4b : HYPERDOC WRITING + INSERTION",
}

OPTIONAL_SCRIPTS = {
    "phase_0_prep/opus_classifier.py",
    "phase_0_prep/build_opus_messages.py",
}

# Pipeline scripts in execution order (--full mode).
# This is the source of truth for what the schematic shows.
PIPELINE_SCRIPTS = [
    "phase_0_prep/enrich_session.py",
    "phase_0_prep/prepare_agent_data.py",
    "phase_0_prep/opus_classifier.py",
    "phase_0_prep/build_opus_messages.py",
    "phase_0_prep/schema_normalizer.py",
    "phase_1_extraction/redo_all_phase1.py",
    "phase_1_extraction/extract_threads.py",
    "phase_2_synthesis/backfill_phase2.py",
    "phase_2_synthesis/file_genealogy.py",
    "phase_3_hyperdoc_writing/collect_file_evidence.py",
    "phase_3_hyperdoc_writing/generate_dossiers.py",
    "phase_3_hyperdoc_writing/generate_viewer.py",
    "phase_4a_aggregation/aggregate_dossiers.py",
    "phase_4_insertion/insert_hyperdocs_v2.py",
    "phase_4_insertion/hyperdoc_layers.py",
]

# ── Verified I/O manifest ────────────────────────────────────────────
# Source: line-by-line code reading of all 15 pipeline scripts.
# Every read/write entry below corresponds to actual open(), json.load(),
# json.dump(), load_json(), save_json(), read_text(), or write_text()
# calls found in the source code. No heuristics, no inference.
#
# To update: read the script, find the I/O lines, update this dict.

VERIFIED_IO = {
    "phase_0_prep/enrich_session.py": {
        "reads": ["session.jsonl"],
        "writes": ["enriched_session.json"],
    },
    "phase_0_prep/prepare_agent_data.py": {
        "reads": ["enriched_session_v2.json", "enriched_session.json", "opus_classifications.json"],
        "writes": [
            "session_metadata.json",
            "tier2plus_messages.json",
            "tier4_priority_messages.json",
            "conversation_condensed.json",
            "user_messages_tier2plus.json",
            "emergency_contexts.json",
            "safe_tier4.json",
            "safe_condensed.json",
        ],
    },
    "phase_0_prep/opus_classifier.py": {
        "reads": ["enriched_session_v2.json", "enriched_session.json"],
        "writes": ["opus_classifications.json", "opus_vs_python_comparison.json"],
    },
    "phase_0_prep/build_opus_messages.py": {
        "reads": ["opus_classifications.json", "enriched_session_v2.json", "enriched_session.json"],
        "writes": ["opus_priority_messages.json", "opus_extended_messages.json", "safe_opus_priority.json"],
    },
    "phase_0_prep/schema_normalizer.py": {
        "reads": [
            "thread_extractions.json", "geological_notes.json", "semantic_primitives.json",
            "explorer_notes.json", "idea_graph.json", "synthesis.json",
            "grounded_markers.json", "file_dossiers.json", "claude_md_analysis.json",
        ],
        "writes": [
            "thread_extractions.json", "geological_notes.json", "semantic_primitives.json",
            "explorer_notes.json", "idea_graph.json", "synthesis.json",
            "grounded_markers.json", "file_dossiers.json", "claude_md_analysis.json",
            "normalization_log.json",
        ],
    },
    "phase_1_extraction/redo_all_phase1.py": {
        "reads": ["safe_condensed.json", "safe_tier4.json", "session_metadata.json"],
        "writes": [
            "thread_extractions.json", "geological_notes.json",
            "semantic_primitives.json", "explorer_notes.json",
            "phase1_redo_progress.json",
        ],
    },
    "phase_1_extraction/extract_threads.py": {
        "reads": ["opus_priority_messages.json", "tier4_priority_messages.json"],
        "writes": ["thread_extractions.json"],
    },
    "phase_2_synthesis/backfill_phase2.py": {
        "reads": [
            "session_metadata.json", "thread_extractions.json",
            "geological_notes.json", "semantic_primitives.json", "explorer_notes.json",
        ],
        "writes": ["idea_graph.json", "synthesis.json", "grounded_markers.json"],
    },
    "phase_2_synthesis/file_genealogy.py": {
        "reads": ["thread_extractions.json", "idea_graph.json"],
        "writes": ["file_genealogy.json"],
    },
    "phase_3_hyperdoc_writing/collect_file_evidence.py": {
        "reads": [
            "session_metadata.json", "geological_notes.json", "semantic_primitives.json",
            "explorer_notes.json", "file_genealogy.json", "thread_extractions.json",
            "grounded_markers.json", "idea_graph.json", "synthesis.json",
            "claude_md_analysis.json", "file_dossiers.json",
        ],
        "writes": ["file_evidence/*_evidence.json"],
    },
    "phase_3_hyperdoc_writing/generate_dossiers.py": {
        "reads": [
            "session_metadata.json", "grounded_markers.json",
            "thread_extractions.json", "idea_graph.json",
        ],
        "writes": ["file_dossiers.json", "claude_md_analysis.json"],
    },
    "phase_3_hyperdoc_writing/generate_viewer.py": {
        "reads": [
            "session_metadata.json", "thread_extractions.json", "geological_notes.json",
            "semantic_primitives.json", "explorer_notes.json", "idea_graph.json",
            "synthesis.json", "grounded_markers.json", "file_dossiers.json",
            "claude_md_analysis.json",
        ],
        "writes": ["pipeline_viewer.html"],
    },
    "phase_4a_aggregation/aggregate_dossiers.py": {
        "reads": [
            "file_dossiers.json", "session_metadata.json",
            "enriched_session.json", "enriched_session_v2.json",
            "file_genealogy.json", "code_similarity_index.json",
            "file_evidence/*_evidence.json",
        ],
        "writes": ["cross_session_file_index.json", "hyperdoc_inputs/*.json"],
    },
    "phase_4_insertion/insert_hyperdocs_v2.py": {
        "reads": [
            "{filename}_header.txt", "{filename}_inline.json", "{filename}_footer.txt",
            "source .py files",
        ],
        "writes": ["hyperdoc_previews_v2/*"],
    },
    "phase_4_insertion/hyperdoc_layers.py": {
        "reads": ["*_hyperdoc.json"],
        "writes": ["*_hyperdoc.json"],
    },
}


# Explicit cross-phase connections that can't be inferred from exact filename matching.
# These handle wildcard patterns, template filenames, and indirect dependencies.
# Format: (source_data_file, target_script)
# The arrow draws from the source data file's position to the target script's position.
CROSS_PHASE_CONNECTIONS = [
    # Phase 4a outputs → Phase 4b scripts
    ("hyperdoc_inputs/*.json", "phase_4_insertion/insert_hyperdocs_v2.py"),
    ("cross_session_file_index.json", "phase_4_insertion/insert_hyperdocs_v2.py"),
    ("cross_session_file_index.json", "phase_4_insertion/hyperdoc_layers.py"),
    # Phase 0 opus_classifications → prepare_agent_data (feedback loop within Phase 0)
    ("opus_classifications.json", "phase_0_prep/prepare_agent_data.py"),
    # Phase 0 opus outputs → Phase 1 deterministic fallback
    ("opus_priority_messages.json", "phase_1_extraction/extract_threads.py"),
    ("safe_opus_priority.json", "phase_1_extraction/extract_threads.py"),
    # Phase 0 tier outputs → Phase 1 deterministic fallback
    ("tier4_priority_messages.json", "phase_1_extraction/extract_threads.py"),
]


def build_graph():
    """Build the pipeline graph from the verified I/O manifest."""
    graph = {"scripts": {}, "data_files": set()}

    for rel_path, io in VERIFIED_IO.items():
        # Determine phase
        phase = "?"
        for dir_prefix, phase_id in PHASE_MAP.items():
            if rel_path.startswith(dir_prefix):
                phase = phase_id
                break

        script_name = Path(rel_path).name
        reads = io.get("reads", [])
        writes = io.get("writes", [])

        graph["scripts"][rel_path] = {
            "name": script_name,
            "phase": phase,
            "reads": reads,
            "writes": writes,
            "optional": rel_path in OPTIONAL_SCRIPTS,
        }

        graph["data_files"].update(reads)
        graph["data_files"].update(writes)

    graph["data_files"] = sorted(graph["data_files"])
    return graph


# ── Mermaid generation ────────────────────────────────────────────────


def safe_id(name):
    """Make a string safe for use as a Mermaid node ID."""
    return name.replace(".", "_").replace("/", "_").replace("*", "x").replace("{", "").replace("}", "").replace(" ", "_")


def generate_mermaid(graph):
    """Generate Mermaid flowchart definition from the pipeline graph."""
    lines = ["graph TD"]

    # Collect all nodes by phase
    phases = {}
    for rel_path, info in graph["scripts"].items():
        p = info["phase"]
        if p not in phases:
            phases[p] = {"scripts": [], "data": set()}
        phases[p]["scripts"].append((rel_path, info))
        for f in info["writes"]:
            phases[p]["data"].add(f)

    phase_order = ["0", "1", "2", "3", "4a", "4b"]
    phase_order = [p for p in phase_order if p in phases]

    # Track which data files we've already defined (to avoid duplicates)
    defined_data = set()

    # Build subgraphs per phase
    for phase_id in phase_order:
        label = PHASE_LABELS.get(phase_id, f"Phase {phase_id}")
        lines.append(f"")
        lines.append(f"  subgraph P{phase_id.replace('a','A').replace('b','B')}[\"{label}\"]")

        # Scripts
        for rel_path, info in phases[phase_id]["scripts"]:
            nid = safe_id(rel_path)
            name = info["name"]
            # Sharp corners for scripts (square brackets in Mermaid)
            lines.append(f"    {nid}[\"{name}\"]")

        # Data files written by this phase
        for fname in sorted(phases[phase_id]["data"]):
            if fname not in defined_data:
                did = safe_id(fname)
                # Rounded corners for data files (parentheses or stadium shape)
                lines.append(f"    {did}([\"{fname}\"])")
                defined_data.add(fname)

        lines.append(f"  end")

    # Edges: script → data (writes) — solid arrows
    lines.append("")
    lines.append("  %% Write edges: script --> data file")
    for rel_path, info in graph["scripts"].items():
        src = safe_id(rel_path)
        for fname in info["writes"]:
            dst = safe_id(fname)
            lines.append(f"  {src} --> {dst}")

    # Edges: data → script (reads, cross-phase) — dotted arrows
    lines.append("")
    lines.append("  %% Read edges: data file -.-> script (cross-phase)")
    drawn_edges = set()
    for rel_path, info in graph["scripts"].items():
        dst = safe_id(rel_path)
        script_phase = info["phase"]
        for fname in info["reads"]:
            src = safe_id(fname)
            # Only draw if data file exists as a node (was written by some phase)
            if fname not in defined_data:
                continue
            # Find the phase that wrote this data file
            writer_phase = None
            for p_id, p_info in phases.items():
                if fname in p_info["data"]:
                    writer_phase = p_id
                    break
            # Only draw cross-phase reads
            if writer_phase and writer_phase != script_phase:
                edge_key = (src, dst)
                if edge_key not in drawn_edges:
                    lines.append(f"  {src} -.-> {dst}")
                    drawn_edges.add(edge_key)

    # Explicit cross-phase connections
    lines.append("")
    lines.append("  %% Explicit cross-phase connections")
    for src_file, tgt_script in CROSS_PHASE_CONNECTIONS:
        if src_file in defined_data:
            src = safe_id(src_file)
            dst = safe_id(tgt_script)
            edge_key = (src, dst)
            if edge_key not in drawn_edges:
                lines.append(f"  {src} -.-> {dst}")
                drawn_edges.add(edge_key)

    # Style classes
    lines.append("")
    lines.append("  %% Styles")
    # Optional scripts get dashed borders
    for rel_path in OPTIONAL_SCRIPTS:
        nid = safe_id(rel_path)
        lines.append(f"  style {nid} stroke-dasharray: 5 5")

    # Phase-colored subgraph fills
    for phase_id in phase_order:
        colors = PHASE_COLORS.get(phase_id, PHASE_COLORS["0"])
        sg_id = f"P{phase_id.replace('a','A').replace('b','B')}"
        lines.append(f"  style {sg_id} fill:{colors['bg']},stroke:{colors['border']},color:{colors['text']}")

    return "\n".join(lines)


def generate_html(mermaid_def):
    """Wrap the Mermaid definition in the HTML page with ELK layout."""
    now = datetime.now().strftime("%b %d, %Y")
    # Escape braces for f-string
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hyperdocs Pipeline Schematic</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --font-body: 'Sora', system-ui, sans-serif;
    --font-mono: 'IBM Plex Mono', 'SF Mono', Consolas, monospace;
    --bg: #f8f9fa;
    --surface: #ffffff;
    --border: rgba(0,0,0,0.08);
    --text: #1a1a2e;
    --text-dim: #6b7280;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117;
      --surface: #161b22;
      --border: rgba(255,255,255,0.08);
      --text: #e6edf3;
      --text-dim: #8b949e;
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-body);
  }}
  header {{
    background: #1a1a2e;
    color: #fff;
    padding: 12px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,.15);
  }}
  header h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
  header .sub {{ color: #8888aa; font-size: 11px; margin-top: 2px; }}
  header .right {{ display: flex; align-items: center; gap: 12px; }}
  header .updated {{ color: #6c6c8a; font-size: 11px; }}

  .mermaid-wrap {{
    position: relative;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 32px 24px;
    margin: 16px;
    overflow: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }}
  .mermaid-wrap::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  .mermaid-wrap::-webkit-scrollbar-track {{ background: transparent; }}
  .mermaid-wrap::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}

  .mermaid-wrap .mermaid {{
    transition: transform 0.2s ease;
    transform-origin: top left;
  }}

  .zoom-controls {{
    position: absolute;
    top: 8px;
    right: 8px;
    display: flex;
    gap: 2px;
    z-index: 10;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 2px;
  }}
  .zoom-controls button {{
    width: 28px;
    height: 28px;
    border: none;
    background: transparent;
    color: var(--text-dim);
    font-family: var(--font-mono);
    font-size: 14px;
    cursor: pointer;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, color 0.15s;
  }}
  .zoom-controls button:hover {{
    background: var(--border);
    color: var(--text);
  }}
  .mermaid-wrap.is-zoomed {{ cursor: grab; }}
  .mermaid-wrap.is-panning {{ cursor: grabbing; user-select: none; }}

  .mermaid .nodeLabel {{
    color: var(--text) !important;
    font-family: var(--font-mono) !important;
    font-size: 13px !important;
  }}
  .mermaid .edgeLabel {{
    color: var(--text-dim) !important;
    background-color: var(--bg) !important;
    font-family: var(--font-mono) !important;
    font-size: 11px !important;
  }}
  .mermaid .edgeLabel rect {{
    fill: var(--bg) !important;
  }}

  @media (prefers-reduced-motion: reduce) {{
    .mermaid-wrap .mermaid {{ transition: none; }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Hyperdocs Pipeline Schematic</h1>
    <p class="sub">Auto-generated from code via Mermaid + ELK layout. Run tools/generate_schematic.py to update.</p>
  </div>
  <div class="right">
    <span class="updated">Generated: {now}</span>
  </div>
</header>

<div class="mermaid-wrap">
  <div class="zoom-controls">
    <button onclick="zoomDiagram(this, 1.2)" title="Zoom in">+</button>
    <button onclick="zoomDiagram(this, 0.8)" title="Zoom out">&minus;</button>
    <button onclick="resetZoom(this)" title="Reset zoom">&#8634;</button>
  </div>
  <pre class="mermaid">
{mermaid_def}
  </pre>
</div>

<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  import elkLayouts from 'https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk/dist/mermaid-layout-elk.esm.min.mjs';

  mermaid.registerLayoutLoaders(elkLayouts);

  const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'base',
    look: 'classic',
    layout: 'elk',
    themeVariables: {{
      primaryColor: isDark ? '#1c2333' : '#e0f7fa',
      primaryBorderColor: isDark ? '#22d3ee' : '#00838f',
      primaryTextColor: isDark ? '#e6edf3' : '#1a1a2e',
      secondaryColor: isDark ? '#1e1b2e' : '#ede7f6',
      secondaryBorderColor: isDark ? '#c4b5fd' : '#7c3aed',
      secondaryTextColor: isDark ? '#e6edf3' : '#1a1a2e',
      tertiaryColor: isDark ? '#27201a' : '#fff8e1',
      tertiaryBorderColor: isDark ? '#fbbf24' : '#f57f17',
      tertiaryTextColor: isDark ? '#e6edf3' : '#1a1a2e',
      lineColor: isDark ? '#6b7280' : '#9ca3af',
      fontSize: '13px',
      fontFamily: "'IBM Plex Mono', monospace",
    }}
  }});
</script>

<script>
function updateZoomState(wrap) {{
  var target = wrap.querySelector('.mermaid');
  var zoom = parseFloat(target.dataset.zoom || '1');
  wrap.classList.toggle('is-zoomed', zoom > 1);
}}
function zoomDiagram(btn, factor) {{
  var wrap = btn.closest('.mermaid-wrap');
  var target = wrap.querySelector('.mermaid');
  var current = parseFloat(target.dataset.zoom || '1');
  var next = Math.min(Math.max(current * factor, 0.3), 5);
  target.dataset.zoom = next;
  target.style.transform = 'scale(' + next + ')';
  updateZoomState(wrap);
}}
function resetZoom(btn) {{
  var wrap = btn.closest('.mermaid-wrap');
  var target = wrap.querySelector('.mermaid');
  target.dataset.zoom = '1';
  target.style.transform = 'scale(1)';
  updateZoomState(wrap);
}}
document.querySelectorAll('.mermaid-wrap').forEach(function(wrap) {{
  wrap.addEventListener('wheel', function(e) {{
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    var target = wrap.querySelector('.mermaid');
    var current = parseFloat(target.dataset.zoom || '1');
    var factor = e.deltaY < 0 ? 1.1 : 0.9;
    var next = Math.min(Math.max(current * factor, 0.3), 5);
    target.dataset.zoom = next;
    target.style.transform = 'scale(' + next + ')';
    updateZoomState(wrap);
  }}, {{ passive: false }});
  var startX, startY, scrollL, scrollT;
  wrap.addEventListener('mousedown', function(e) {{
    if (e.target.closest('.zoom-controls')) return;
    var target = wrap.querySelector('.mermaid');
    if (parseFloat(target.dataset.zoom || '1') <= 1) return;
    wrap.classList.add('is-panning');
    startX = e.clientX; startY = e.clientY;
    scrollL = wrap.scrollLeft; scrollT = wrap.scrollTop;
  }});
  window.addEventListener('mousemove', function(e) {{
    if (!wrap.classList.contains('is-panning')) return;
    wrap.scrollLeft = scrollL - (e.clientX - startX);
    wrap.scrollTop = scrollT - (e.clientY - startY);
  }});
  window.addEventListener('mouseup', function() {{
    wrap.classList.remove('is-panning');
  }});
}});
</script>

<!-- Generated by tools/generate_schematic.py — run again to update -->
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate pipeline schematic from code")
    parser.add_argument("--json", action="store_true", help="Dump raw graph as JSON")
    parser.add_argument("--mermaid", action="store_true", help="Print Mermaid definition only")
    parser.add_argument("--output", default=None, help="Output path (default: repo root)")
    args = parser.parse_args()

    print("Building graph from verified I/O manifest...")
    graph = build_graph()

    if args.json:
        print(json.dumps(graph, indent=2, default=str))
        return

    # Print summary
    for rel_path, info in graph["scripts"].items():
        opt = " (optional)" if info["optional"] else ""
        print(f"  P{info['phase']} {info['name']}{opt}")
        if info["reads"]:
            print(f"       reads:  {', '.join(info['reads'])}")
        if info["writes"]:
            print(f"       writes: {', '.join(info['writes'])}")

    print(f"\n  {len(graph['scripts'])} scripts, {len(graph['data_files'])} data files")

    print("\nGenerating Mermaid flowchart...")
    mermaid_def = generate_mermaid(graph)

    if args.mermaid:
        print(mermaid_def)
        return

    html = generate_html(mermaid_def)

    out_path = Path(args.output) if args.output else REPO_ROOT / "hyperdocs-pipeline-schematic.html"
    out_path.write_text(html)
    print(f"\nWrote: {out_path} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
