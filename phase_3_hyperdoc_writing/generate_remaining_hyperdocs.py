#!/usr/bin/env python3
"""
Generate hyperdoc blocks for the remaining 10 files (we already have 5).
Uses file_dossiers.json + grounded_markers.json to compose blocks.
"""
import json
import re
import os
from pathlib import Path

BASE = Path(__file__).parent
V5 = BASE.parent.parent / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_2" / "V5" / "code"
BLOCKS_DIR = BASE / "hyperdoc_blocks"
PREVIEW_DIR = BASE / "hyperdoc_previews"
DEST_DIR = BASE.parent.parent / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_2" / "hyperdoc code files"
BLOCKS_DIR.mkdir(exist_ok=True)
PREVIEW_DIR.mkdir(exist_ok=True)
DEST_DIR.mkdir(exist_ok=True)

# Already done
ALREADY_DONE = {
    "unified_orchestrator.py", "geological_reader.py", "hyperdoc_pipeline.py",
    "story_marker_generator.py", "six_thread_extractor.py"
}

# Special location for one file
SPECIAL_PATHS = {
    "opus_struggle_analyzer.py": BASE.parent.parent / ".claude" / "hooks" / "hyperdoc" / "opus_struggle_analyzer.py"
}

dossiers = json.load(open(BASE / "file_dossiers.json"))
markers = json.load(open(BASE / "grounded_markers.json"))


def get_applicable_warnings(filename, all_warnings):
    """Get warnings that apply to a specific file."""
    result = []
    for w in all_warnings:
        target = w.get("target", "").lower()
        if filename.lower().replace(".py", "") in target or "any file" in target or "all" in target.split():
            result.append(w)
    return result


def get_applicable_recs(filename, all_recs):
    """Get recommendations that apply to a specific file."""
    result = []
    for r in all_recs:
        target = r.get("target", "").lower()
        if filename.lower().replace(".py", "") in target or "any file" in target or "any new" in target:
            result.append(r)
    return result


def generate_block(dossier, filename):
    """Generate a hyperdoc comment block from a file dossier."""
    lines = []
    lines.append(f"# ===========================================================================")
    lines.append(f"# HYPERDOC BLOCK: {filename}")
    lines.append(f"# Session: {SESSION_ID} | Generated: 2026-02-06")
    lines.append(f"# ===========================================================================")
    lines.append(f"#")

    # @ctx header
    conf = dossier.get("confidence", "tentative")
    mentions = dossier.get("total_mentions", 0)
    lines.append(f"# @ctx:state={conf} @ctx:confidence={conf}")
    lines.append(f"# @ctx:intent=maintainability @ctx:updated=2026-02-05")
    lines.append(f"# @ctx:total_mentions={mentions}")
    lines.append(f"#")

    # Story arc
    lines.append(f"# --- STORY ARC ---")
    arc = dossier.get("story_arc", "No story arc available.")
    for line in _wrap(arc, 90):
        lines.append(f"#   {line}")
    lines.append(f"#")

    # Key decisions
    decisions = dossier.get("key_decisions", [])
    if decisions:
        lines.append(f"# --- DECISIONS ---")
        for d in decisions:
            lines.append(f"#")
            for line in _wrap(d, 90):
                lines.append(f"# @ctx:decision=\"{line}\"")
        lines.append(f"#")

    # Warnings
    warnings = dossier.get("warnings", [])
    if warnings:
        lines.append(f"# --- WARNINGS ---")
        for w in warnings:
            if isinstance(w, dict):
                wid = w.get("id", "")
                sev = w.get("severity", "medium")
                text = w.get("warning", "")
                ev = w.get("evidence", "")
                lines.append(f"#")
                lines.append(f"# @ctx:warning=\"[{wid}] [{sev.upper()}] {text[:200]}\"")
                if ev:
                    lines.append(f"#   Evidence: {ev}")
            else:
                lines.append(f"# @ctx:warning=\"{str(w)[:200]}\"")
        lines.append(f"#")

    # Recommendations
    recs = dossier.get("recommendations", [])
    if recs:
        lines.append(f"# --- RECOMMENDATIONS ---")
        for r in recs:
            if isinstance(r, dict):
                rid = r.get("id", "")
                pri = r.get("priority", "medium")
                text = r.get("recommendation", "")
                lines.append(f"#")
                lines.append(f"# [{rid}] (priority: {pri})")
                for line in _wrap(text, 90):
                    lines.append(f"#   {line}")
            else:
                lines.append(f"#   {str(r)[:200]}")
        lines.append(f"#")

    # Iron rules (applicable to all files)
    iron_rules = markers.get("iron_rules_registry", [])
    if iron_rules:
        lines.append(f"# --- IRON RULES (session-wide, applicable to all files) ---")
        for r in iron_rules:
            rnum = r.get("rule_number", "?")
            rule = r.get("rule", "")
            est = r.get("established_at", "?")
            status = r.get("status", "active")
            ev = r.get("evidence", "")
            lines.append(f"#")
            lines.append(f"# @ctx:iron_rule={rnum} \"{rule}\"")
            lines.append(f"#   Established at: msg {est} | Status: {status}")
            if ev:
                lines.append(f"#   Evidence: {ev}")
        lines.append(f"#")

    # Claude behavior
    cb = dossier.get("claude_behavior", {})
    if cb:
        lines.append(f"# --- CLAUDE BEHAVIOR ON THIS FILE ---")
        for k, v in cb.items():
            lines.append(f"# @ctx:claude_pattern=\"{k}: {v}\"")
        lines.append(f"#")

    # Related files
    related = dossier.get("related_files", [])
    if related:
        lines.append(f"# --- RELATED FILES ---")
        for rf in related:
            lines.append(f"# - {rf}")
        lines.append(f"#")

    # Idea graph subgraphs
    subgraphs = dossier.get("idea_graph_subgraphs", [])
    if subgraphs:
        lines.append(f"# --- IDEA GRAPH SUBGRAPHS ---")
        for sg in subgraphs:
            if isinstance(sg, dict):
                lines.append(f"# [{sg.get('name','')}] ({sg.get('node_count','')} nodes)")
                summary = sg.get("summary", "")
                for line in _wrap(summary, 90):
                    lines.append(f"#   {line}")
            else:
                lines.append(f"# {sg}")
        lines.append(f"#")

    # Key metrics (session-wide)
    lines.append(f"# --- KEY METRICS (session-wide) ---")
    lines.append(f"# [M01] Premature victory rate: 1 per 475 messages (9 in 4269)")
    lines.append(f"# [M02] Confidence-evidence mismatch: 5.7:1")
    lines.append(f"# [M03] Post-context-reset violation rate: 31%")
    lines.append(f"#")

    lines.append(f"# ===========================================================================")
    lines.append(f"# END HYPERDOC BLOCK: {filename}")
    lines.append(f"# ===========================================================================")

    return "\n".join(lines)


def _wrap(text, width):
    """Simple word wrap."""
    words = str(text).split()
    lines = []
    current = []
    length = 0
    for w in words:
        if length + len(w) + 1 > width and current:
            lines.append(" ".join(current))
            current = [w]
            length = len(w)
        else:
            current.append(w)
            length += len(w) + 1
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def find_insertion_point(lines):
    """Find where to insert hyperdoc (after imports, before first def/class)."""
    i = 0
    n = len(lines)
    if i < n and lines[i].startswith("#!"):
        i += 1
    while i < n and lines[i].strip() == "":
        i += 1
    if i < n and (lines[i].strip().startswith('"""') or lines[i].strip().startswith("'''")):
        quote = lines[i].strip()[:3]
        if lines[i].strip().count(quote) >= 2:
            i += 1
        else:
            i += 1
            while i < n and quote not in lines[i]:
                i += 1
            if i < n:
                i += 1
    while i < n and lines[i].strip() == "":
        i += 1
    while i < n and lines[i].strip().startswith("#"):
        i += 1
    while i < n and lines[i].strip() == "":
        i += 1
    in_try = False
    while i < n:
        s = lines[i].strip()
        if s == "" or s.startswith("#"):
            i += 1
            continue
        if s.startswith("import ") or s.startswith("from "):
            i += 1
            if "(" in s and ")" not in s:
                while i < n and ")" not in lines[i]:
                    i += 1
                if i < n:
                    i += 1
            continue
        if s.startswith("try:"):
            in_try = True
            i += 1
            continue
        if s.startswith("except") and in_try:
            i += 1
            while i < n and (lines[i].startswith("    ") or lines[i].strip() == ""):
                i += 1
            in_try = False
            continue
        if in_try:
            i += 1
            continue
        if any(s.startswith(p) for p in [
            "load_dotenv", "PROJECT_ROOT", "client ", "client=",
            "API_CALL_LOG", "DAYS ", "DAYS=",
        ]):
            i += 1
            continue
        if re.match(r'^[A-Z_]+ = ', s):
            i += 1
            continue
        if re.match(r'^[a-z_]+\(', s) and not s.startswith("def "):
            i += 1
            continue
        if s.startswith("class ") or s.startswith("def ") or s.startswith("@"):
            break
        i += 1
    return i


# Build dossier lookup
dossier_map = {d["filename"]: d for d in dossiers.get("files", [])}

count = 0
for filename, dossier in dossier_map.items():
    if filename in ALREADY_DONE:
        print(f"  SKIP (already done): {filename}")
        continue

    # Find source file
    source_path = SPECIAL_PATHS.get(filename, V5 / filename)
    if not source_path.exists():
        print(f"  SKIP (not found): {filename} at {source_path}")
        continue

    # Generate hyperdoc block
    block = generate_block(dossier, filename)

    # Write block file
    block_file = BLOCKS_DIR / f"{filename.replace('.py', '')}_hyperdoc.txt"
    block_file.write_text(block)

    # Read source, insert, write preview
    with open(source_path) as f:
        source_lines = f.readlines()

    insertion_point = find_insertion_point(source_lines)
    result = []
    result.extend(source_lines[:insertion_point])
    if result and result[-1].strip() != "":
        result.append("\n")
    result.append("\n")
    for line in block.splitlines():
        result.append(line + "\n")
    result.append("\n\n")
    result.extend(source_lines[insertion_point:])

    preview_path = PREVIEW_DIR / filename
    with open(preview_path, "w") as f:
        f.writelines(result)

    # Also copy to destination
    dest_path = DEST_DIR / filename
    with open(dest_path, "w") as f:
        f.writelines(result)

    block_lines = len(block.splitlines())
    print(f"  {filename}: {len(source_lines)} lines + {block_lines} hyperdoc at line {insertion_point} → {len(result)} lines")
    count += 1

# Also copy the 5 already-done files to dest if not already there
for filename in ALREADY_DONE:
    src = PREVIEW_DIR / filename
    dst = DEST_DIR / filename
    if src.exists() and not dst.exists():
        import shutil
        shutil.copy2(src, dst)
        print(f"  COPIED (existing): {filename}")

print(f"\nGenerated {count} new hyperdoc blocks.")
print(f"All files at: {DEST_DIR}")
