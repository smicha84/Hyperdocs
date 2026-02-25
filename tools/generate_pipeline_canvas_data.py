#!/usr/bin/env python3
"""
Pipeline Canvas Data Generator — Produces pipeline-data.json for the interactive SVG canvas.

Uses hand-curated I/O manifests (tools/_io_phase0.py, _io_phase1_2.py, _io_phase3_4.py,
_io_tools.py) produced by reading every pipeline script line by line. No heuristics.

Output: ~/wrecktangle-site/public/pipeline-canvas/pipeline-data.json
        ~/wrecktangle-site/public/pipeline-canvas/pipeline-data.js

Usage:
    python3 tools/generate_pipeline_canvas_data.py
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import from sibling tools
sys.path.insert(0, str(REPO_ROOT))
from tools.generate_schematic import (
    PHASE_MAP,
    PHASE_LABELS,
    PIPELINE_SCRIPTS,
    OPTIONAL_SCRIPTS,
)
from tools.analyze_data_flow import OUTPUT_PHASE_MAP

# Import hand-curated I/O manifests
from tools._io_phase0 import PHASE0_IO
from tools._io_phase1_2 import PHASE1_2_IO
from tools._io_phase3_4 import PHASE3_4_IO
from tools._io_tools import TOOLS_IO

# ── Merge all manifests into one ─────────────────────────────────────
COMPLETE_IO = {}
COMPLETE_IO.update(PHASE0_IO)
COMPLETE_IO.update(PHASE1_2_IO)
COMPLETE_IO.update(PHASE3_4_IO)
COMPLETE_IO.update(TOOLS_IO)

# ── Output path ──────────────────────────────────────────────────────
OUTPUT_DIR = Path.home() / "wrecktangle-site" / "public" / "pipeline-canvas"
OUTPUT_FILE = OUTPUT_DIR / "pipeline-data.json"
OUTPUT_JS = OUTPUT_DIR / "pipeline-data.js"

# ── Phase configuration (dark-mode colors for SVG canvas) ────────────
DARK_PHASE_COLORS = {
    "0":    {"bg": "#0d2830", "border": "#22d3ee", "text": "#67e8f9"},
    "1":    {"bg": "#1a1530", "border": "#a78bfa", "text": "#c4b5fd"},
    "2":    {"bg": "#0d2818", "border": "#4ade80", "text": "#86efac"},
    "3":    {"bg": "#2a2008", "border": "#fbbf24", "text": "#fde68a"},
    "4a":   {"bg": "#2a1015", "border": "#f87171", "text": "#fca5a5"},
    "4b":   {"bg": "#2a1015", "border": "#f87171", "text": "#fca5a5"},
    "tools": {"bg": "#1a1a1a", "border": "#6b7280", "text": "#9ca3af"},
}

PHASE_ORDER = {"0": 0, "1": 1, "2": 2, "3": 3, "4a": 4, "4b": 5, "tools": 6}
PHASE_NUM_TO_ID = {0: "0", 1: "1", 2: "2", 3: "3", 4: "4a", -1: "tools"}

EXCLUDED_DIRS = {
    "v5_compat", "output", "__pycache__", ".git", "commands",
    "obsolete", "archive_originals", "standby", "idea_graph_explorer",
    "system_file_report", "hyperdoc_previews", "evidence",
}

PIPELINE_SCRIPTS_SET = set(PIPELINE_SCRIPTS)

# Patterns too generic to be meaningful data nodes
SKIP_PATTERNS = {
    "*.json", "*.jsonl", "*.py", "*.html", "*.txt", "*.lock",
    "*.md", "*.js", "*.toml",
    ".env", "CLAUDE.md", "config.py",
    "**/*.py", "**/*.jsonl",
    "~/.claude/projects/**/*.jsonl",
    "{REPO}/**/*.py",
    "projects/**/*.jsonl",
    "**/*.jsonl",
}


# ── Path normalization ───────────────────────────────────────────────

def normalize_data_path(raw_path: str) -> str:
    """Strip all directory prefixes, keep only the basename or last meaningful path component."""
    path = raw_path

    # Strip everything up to the last meaningful filename
    # Remove ~ prefixes
    path = re.sub(r"^~/[^/]+/", "", path)  # ~/PERMANENT_HYPERDOCS/, ~/wrecktangle-site/, etc.
    # Keep stripping directory components that are containers
    path = re.sub(r"^(PERMANENT_HYPERDOCS|wrecktangle-site|public|pipeline-canvas)/", "", path)
    path = re.sub(r"^(sessions|indexes|output|tools)/", "", path)
    path = re.sub(r"^session_[^/]*/", "", path)  # session_0012ebed/, session_*/
    path = re.sub(r"^~/\.claude/[^/]*/", "", path)
    path = re.sub(r"^~/\.agent/[^/]*/", "", path)
    path = re.sub(r"^~/Hyperdocs/[^/]*/", "", path)
    path = re.sub(r"^~/Hyperdocs/", "", path)
    path = re.sub(r"^\{[^}]+\}/", "", path)
    path = re.sub(r"^experiment/[^/]*/[^/]*/", "", path)
    path = re.sub(r"^phase_[^/]*/", "", path)
    path = re.sub(r"^\*\*/", "", path)
    path = re.sub(r"^completed/", "", path)
    path = re.sub(r"^viz-gallery/", "", path)
    path = re.sub(r"^diagrams/", "", path)

    # Second pass — strip remaining session_*/ and similar prefixes
    path = re.sub(r"^session_[^/]*/", "", path)
    path = re.sub(r"^sessions/", "", path)
    path = re.sub(r"^indexes/", "", path)
    path = re.sub(r"^output/", "", path)
    path = re.sub(r"^tools/", "", path)

    # Normalize template variables to wildcards
    path = re.sub(r"\{[^}]+\}", "*", path)

    return path


def is_pipeline_data(path: str) -> bool:
    """Return True if this normalized path represents meaningful pipeline data."""
    if path in SKIP_PATTERNS:
        return False
    # Skip bare wildcards
    if path in {"*", "*.*"}:
        return False
    # Skip paths that are just file extension wildcards
    if re.match(r"^\*+\.(\w+)$", path):
        ext = path.split(".")[-1]
        if ext in {"json", "jsonl", "py", "html", "txt", "md", "js", "toml", "lock", "xlsx"}:
            return False
    # Skip multi-wildcard glob patterns like "**/*.jsonl", "*_**.jsonl"
    if path.count("*") >= 2 and "/" not in path and not path.endswith(".json"):
        return False
    # Skip .py files (code imports, not data files)
    if path.endswith(".py"):
        return False
    # Skip .log files
    if path.endswith(".log"):
        return False
    # Skip bare directory globs
    if path.endswith("/*") or path == "*":
        return False
    return True


# ── File discovery ───────────────────────────────────────────────────

def discover_py_files():
    """Walk phase directories, tools/, and config.py to find every .py file."""
    files = []
    for root, dirs, filenames in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        rel_root = Path(root).relative_to(REPO_ROOT)
        root_str = str(rel_root)
        if root_str == ".":
            for f in filenames:
                if f == "config.py":
                    files.append(Path(root) / f)
        elif root_str.startswith(("phase_", "tools")):
            for f in sorted(filenames):
                if f.endswith(".py") and f != "__init__.py":
                    files.append(Path(root) / f)
    return files


# ── Phase + type classification ──────────────────────────────────────

def get_phase_id(rel_path: str) -> str:
    for dir_prefix, phase_id in PHASE_MAP.items():
        if rel_path.startswith(dir_prefix):
            return phase_id
    if rel_path.startswith("tools/") or rel_path == "config.py":
        return "tools"
    return "tools"


def classify_node(rel_path: str) -> str:
    if rel_path == "config.py":
        return "config"
    if rel_path in PIPELINE_SCRIPTS_SET:
        return "core"
    name = Path(rel_path).name
    if "batch" in name.lower() or "orchestrat" in name.lower():
        return "batch"
    return "support"


# ── Line number extraction (for code popup highlighting) ─────────────

def extract_highlight_lines(source: str) -> dict:
    imports, reads, writes = [], [], []
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        ln = i + 1
        if re.match(r"from\s+phase_\d", stripped) or re.match(r"from\s+tools\.", stripped):
            imports.append(ln)
        elif re.match(r"import\s+tools\.", stripped):
            imports.append(ln)
        elif re.match(r"from\s+config\s+import", stripped):
            imports.append(ln)
        if re.search(r"json\.load\s*\(|\.read_text\s*\(|load_json\s*\(", stripped):
            reads.append(ln)
        elif re.search(r"open\s*\([^)]*\)\s+as\s+\w+:", stripped) and ".json" in stripped:
            if not re.search(r"['\"]w['\"]", stripped):
                reads.append(ln)
        if re.search(r"json\.dump\s*\(|\.write_text\s*\(|save_json\s*\(", stripped):
            writes.append(ln)
        elif re.search(r"open\s*\([^)]*['\"]w['\"]", stripped):
            writes.append(ln)
    return {"imports": imports, "reads": reads, "writes": writes}


# ── Main generation ──────────────────────────────────────────────────

def generate():
    print("Discovering Python files...")
    py_files = discover_py_files()
    print(f"  Found {len(py_files)} .py files")
    print(f"  Manifest covers {len(COMPLETE_IO)} files")

    # ── Build script nodes ──
    nodes = []
    nodes_by_id = {}

    manifest_hits = 0
    manifest_misses = []

    for filepath in py_files:
        rel_path = str(filepath.relative_to(REPO_ROOT))
        phase_id = get_phase_id(rel_path)
        source = filepath.read_text(encoding="utf-8", errors="replace")
        line_count = len(source.split("\n"))
        node_type = classify_node(rel_path)
        is_optional = rel_path in OPTIONAL_SCRIPTS

        # I/O from hand-curated manifest
        if rel_path in COMPLETE_IO:
            manifest_hits += 1
            raw_reads = COMPLETE_IO[rel_path].get("reads", [])
            raw_writes = COMPLETE_IO[rel_path].get("writes", [])
        else:
            manifest_misses.append(rel_path)
            raw_reads = []
            raw_writes = []

        # Normalize paths and filter
        io_reads = []
        for r in raw_reads:
            norm = normalize_data_path(r)
            if is_pipeline_data(norm):
                io_reads.append(norm)

        io_writes = []
        for w in raw_writes:
            norm = normalize_data_path(w)
            if is_pipeline_data(norm):
                io_writes.append(norm)

        io_reads = sorted(set(io_reads))
        io_writes = sorted(set(io_writes))

        highlight = extract_highlight_lines(source)

        node = {
            "id": rel_path,
            "label": Path(rel_path).name,
            "phase_id": phase_id,
            "type": node_type,
            "optional": is_optional,
            "x": 0, "y": 0, "width": 200, "height": 44,
            "line_count": line_count,
            "source_code": source,
            "reads": io_reads,
            "writes": io_writes,
            "highlight_lines": highlight,
        }
        nodes.append(node)
        nodes_by_id[node["id"]] = node

    print(f"  Manifest hits: {manifest_hits}/{len(py_files)}")
    if manifest_misses:
        print(f"  Manifest misses: {len(manifest_misses)}")
        for m in manifest_misses:
            print(f"    {m}")

    # ── Create data file nodes ──
    print("Creating data file nodes...")
    all_data_files = set()
    writers = {}
    readers = {}
    for node in nodes:
        for f in node["writes"]:
            all_data_files.add(f)
            writers.setdefault(f, []).append(node["id"])
        for f in node["reads"]:
            all_data_files.add(f)
            readers.setdefault(f, []).append(node["id"])

    data_nodes = []
    data_nodes_by_id = {}
    for fname in sorted(all_data_files):
        # Determine phase from OUTPUT_PHASE_MAP or infer from writers
        phase_num = OUTPUT_PHASE_MAP.get(fname, -1)
        if phase_num == -1 and fname in writers:
            writer_node = nodes_by_id.get(writers[fname][0])
            phase_id = writer_node["phase_id"] if writer_node else "tools"
        else:
            phase_id = PHASE_NUM_TO_ID.get(phase_num, "tools")

        data_id = f"data:{fname}"
        data_node = {
            "id": data_id,
            "label": fname,
            "phase_id": phase_id,
            "type": "data",
            "optional": False,
            "x": 0, "y": 0, "width": 170, "height": 32,
            "line_count": 0,
            "source_code": "",
            "reads": [], "writes": [],
            "highlight_lines": {"imports": [], "reads": [], "writes": []},
        }
        data_nodes.append(data_node)
        data_nodes_by_id[data_id] = data_node

    print(f"  {len(data_nodes)} data file nodes")

    # ── Build edges ──
    print("Building edges...")
    edges = []
    edge_set = set()
    edge_id = 0

    for fname, writer_ids in writers.items():
        data_id = f"data:{fname}"
        if data_id not in data_nodes_by_id:
            continue
        for script_id in writer_ids:
            key = (script_id, data_id)
            if key not in edge_set:
                edge_set.add(key)
                edges.append({
                    "id": f"e{edge_id}",
                    "source": script_id, "target": data_id,
                    "label": "", "edge_type": "write", "control_points": [],
                })
                edge_id += 1

    for fname, reader_ids in readers.items():
        data_id = f"data:{fname}"
        if data_id not in data_nodes_by_id:
            continue
        for script_id in reader_ids:
            if script_id not in nodes_by_id:
                continue
            key = (data_id, script_id)
            if key not in edge_set:
                edge_set.add(key)
                edges.append({
                    "id": f"e{edge_id}",
                    "source": data_id, "target": script_id,
                    "label": "", "edge_type": "read", "control_points": [],
                })
                edge_id += 1

    print(f"  {len(edges)} edges total")

    # Merge data nodes into main list
    nodes.extend(data_nodes)
    nodes_by_id.update(data_nodes_by_id)

    # ── Compute layout ──
    print("Computing layout positions...")
    script_groups = {}
    data_groups = {}
    for node in nodes:
        if node["type"] == "data":
            data_groups.setdefault(node["phase_id"], []).append(node)
        else:
            script_groups.setdefault(node["phase_id"], []).append(node)

    type_order = {"core": 0, "batch": 1, "support": 2, "config": 3}
    for pid in script_groups:
        script_groups[pid].sort(key=lambda n: (type_order.get(n["type"], 9), n["label"]))
    for pid in data_groups:
        data_groups[pid].sort(key=lambda n: n["label"])

    phases = []
    script_col_width = 260
    data_col_width = 190
    col_gap = 16
    container_pad = 10
    node_spacing = 52
    header_height = 50

    for phase_id in ["0", "1", "2", "3", "4a", "4b", "tools"]:
        scripts = script_groups.get(phase_id, [])
        data = data_groups.get(phase_id, [])
        if not scripts and not data:
            continue

        order = PHASE_ORDER.get(phase_id, 99)
        colors = DARK_PHASE_COLORS.get(phase_id, DARK_PHASE_COLORS["tools"])
        label = PHASE_LABELS.get(phase_id, "TOOLS / UTILITIES" if phase_id == "tools" else f"Phase {phase_id}")

        container_width = container_pad + script_col_width + col_gap + data_col_width + container_pad
        row_count = max(len(scripts), len(data))
        container_height = header_height + row_count * node_spacing + 20
        container_x = 40 + order * (container_width + 40)
        container_y = 40

        phases.append({
            "id": f"phase_{phase_id}",
            "label": label, "order": order, "color": colors,
            "x": container_x, "y": container_y,
            "width": container_width, "height": container_height,
        })

        for idx, node in enumerate(scripts):
            node["x"] = container_x + container_pad
            node["y"] = container_y + header_height + idx * node_spacing
            node["width"] = script_col_width
            node["height"] = 44

        for idx, node in enumerate(data):
            node["x"] = container_x + container_pad + script_col_width + col_gap
            node["y"] = container_y + header_height + idx * node_spacing
            node["width"] = data_col_width
            node["height"] = 32

    # ── Write output ──
    output = {
        "generated_at": datetime.now().isoformat(),
        "phases": phases, "nodes": nodes, "edges": edges,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_str = json.dumps(output, indent=2)
    with open(OUTPUT_FILE, "w") as f:
        f.write(json_str)
    with open(OUTPUT_JS, "w") as f:
        f.write("window.PIPELINE_DATA = ")
        f.write(json_str)
        f.write(";\n")

    print(f"\nWrote: {OUTPUT_FILE}")
    print(f"  Size: {OUTPUT_FILE.stat().st_size:,} bytes")
    print(f"Wrote: {OUTPUT_JS}")
    print(f"  Size: {OUTPUT_JS.stat().st_size:,} bytes")

    script_count = len([n for n in nodes if n["type"] != "data"])
    data_count = len([n for n in nodes if n["type"] == "data"])
    print(f"  Phases: {len(phases)} | Scripts: {script_count} | Data: {data_count} | Edges: {len(edges)}")

    for p in phases:
        s = len([n for n in nodes if f"phase_{n['phase_id']}" == p["id"] and n["type"] != "data"])
        d = len([n for n in nodes if f"phase_{n['phase_id']}" == p["id"] and n["type"] == "data"])
        print(f"  {p['label']}: {s} scripts, {d} data files")


if __name__ == "__main__":
    generate()
