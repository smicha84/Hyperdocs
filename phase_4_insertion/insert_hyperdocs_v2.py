#!/usr/bin/env python3
"""
Smart Hyperdoc Insertion (V2) — Header + Inline + Footer

Places hyperdoc content at three locations in each code file:
1. HEADER: After imports, before first class/function (file-level context)
2. INLINE: Before specific functions/classes that have per-function data
3. FOOTER: At end of file (version history, metrics, idea graph subgraphs)

Reads from: output/session_3b7084d5/hyperdoc_v2/{filename}_header.txt
                                                 {filename}_inline.json
                                                 {filename}_footer.txt

Writes to:  output/session_3b7084d5/hyperdoc_previews_v2/{filename}
"""
import ast
import json
import os
import re
from pathlib import Path
from datetime import datetime

import sys as _sys
BASE = Path(__file__).parent
# V5 source directory — use config if available, fallback to v5_compat
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import V5_SOURCE_DIR
    V5_CODE = V5_SOURCE_DIR
except ImportError:
    V5_CODE = Path(__file__).resolve().parent.parent / "phase_0_prep" / "v5_compat"
HYPERDOC_V2_DIR = BASE / "hyperdoc_v2"
PREVIEW_DIR = BASE / "hyperdoc_previews_v2"


def find_header_insertion_point(lines):
    """
    Find the line index where the header hyperdoc should be inserted.

    Strategy: after imports/module-level setup, before first class/function/decorator.
    Reuses the proven logic from insert_hyperdocs.py v1.
    """
    i = 0
    n = len(lines)

    # Skip shebang
    if i < n and lines[i].startswith("#!"):
        i += 1

    # Skip blank lines after shebang
    while i < n and lines[i].strip() == "":
        i += 1

    # Skip module docstring
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

    # Skip header comments (#ARCHITECTURE:, #WHY:, etc.)
    while i < n and lines[i].strip().startswith("#"):
        i += 1

    while i < n and lines[i].strip() == "":
        i += 1

    # Skip imports and module-level setup
    in_try_block = False
    last_import_end = i

    while i < n:
        stripped = lines[i].strip()

        if stripped == "":
            i += 1
            continue

        if stripped.startswith("#"):
            i += 1
            continue

        if stripped.startswith("import ") or stripped.startswith("from "):
            i += 1
            if "(" in stripped and ")" not in stripped:
                while i < n and ")" not in lines[i]:
                    i += 1
                if i < n:
                    i += 1
            last_import_end = i
            continue

        if stripped.startswith("try:"):
            in_try_block = True
            i += 1
            continue
        if stripped.startswith("except") and in_try_block:
            i += 1
            while i < n and (lines[i].startswith("    ") or lines[i].strip() == ""):
                i += 1
            in_try_block = False
            last_import_end = i
            continue
        if in_try_block:
            i += 1
            continue

        if any(stripped.startswith(p) for p in [
            "load_dotenv", "PROJECT_ROOT", "client ", "client=",
            "API_CALL_LOG", "DAYS ", "DAYS=",
        ]):
            i += 1
            last_import_end = i
            continue

        if re.match(r'^[A-Z_]+ = ', stripped):
            i += 1
            last_import_end = i
            continue

        if re.match(r'^[a-z_]+\(', stripped) and not stripped.startswith("def "):
            i += 1
            last_import_end = i
            continue

        if (stripped.startswith("class ") or
            stripped.startswith("def ") or
            stripped.startswith("@")):
            break

        i += 1
        last_import_end = i

    return last_import_end


def get_function_class_locations(source_text):
    """
    Use AST to find all top-level and class-level function/class definitions.

    Returns list of dicts: {name, type, line, col_offset}
    Line numbers are 1-indexed (matching source file).
    """
    locations = []
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return locations

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            locations.append({
                "name": node.name,
                "type": "function",
                "line": node.lineno,
                "decorator_line": node.decorator_list[0].lineno if node.decorator_list else node.lineno,
            })
        elif isinstance(node, ast.ClassDef):
            locations.append({
                "name": node.name,
                "type": "class",
                "line": node.lineno,
                "decorator_line": node.decorator_list[0].lineno if node.decorator_list else node.lineno,
            })

    # Sort by line number
    locations.sort(key=lambda x: x["line"])
    return locations


def insert_all(source_lines, header_text, inline_data, footer_text, filename):
    """
    Insert header, inline comments, and footer into source lines.

    Returns new list of lines.
    """
    source_text = "".join(source_lines)
    ast_locations = get_function_class_locations(source_text)

    # Build a map of function/class name -> insertion line (0-indexed)
    # We insert BEFORE the decorator or def/class line
    name_to_line = {}
    for loc in ast_locations:
        # Use decorator_line - 1 for 0-indexed insertion point
        name_to_line[loc["name"]] = loc["decorator_line"] - 1

    # Build inline insertion map: line_index -> comment_lines
    inline_insertions = {}
    if inline_data and "inline_comments" in inline_data:
        for entry in inline_data["inline_comments"]:
            target = entry.get("target", "")
            if target in name_to_line:
                line_idx = name_to_line[target]
                inline_insertions[line_idx] = entry.get("comment_lines", [])

    # Find header insertion point
    header_point = find_header_insertion_point(source_lines)

    # Build result with all insertions
    # We need to process insertions from bottom to top to avoid index shifts
    # Collect all insertion points
    insertions = []

    # Header
    if header_text and header_text.strip():
        header_lines = [line + "\n" for line in header_text.splitlines()]
        insertions.append((header_point, header_lines, "header"))

    # Inline (adjust indices for header insertion)
    for line_idx, comment_lines in sorted(inline_insertions.items()):
        formatted = []
        for cl in comment_lines:
            formatted.append(cl + "\n")
        insertions.append((line_idx, formatted, "inline"))

    # Sort insertions by position, bottom-first (so inserting doesn't shift later indices)
    insertions.sort(key=lambda x: x[0], reverse=True)

    result = list(source_lines)

    for insert_idx, insert_lines, insert_type in insertions:
        # Add spacing
        padded = []
        if insert_type == "header":
            padded.append("\n")
            padded.extend(insert_lines)
            padded.append("\n")
        elif insert_type == "inline":
            padded.extend(insert_lines)

        result[insert_idx:insert_idx] = padded

    # Footer: append at end
    if footer_text and footer_text.strip():
        result.append("\n\n")
        for line in footer_text.splitlines():
            result.append(line + "\n")
        result.append("\n")

    return result


def process_file(filename):
    """Process one file: read source, read hyperdoc parts, insert, write preview."""
    source_path = V5_CODE / filename
    header_path = HYPERDOC_V2_DIR / f"{filename}_header.txt"
    inline_path = HYPERDOC_V2_DIR / f"{filename}_inline.json"
    footer_path = HYPERDOC_V2_DIR / f"{filename}_footer.txt"
    preview_path = PREVIEW_DIR / filename

    if not source_path.exists():
        print(f"  SKIP {filename}: source not found at {source_path}")
        return False

    if not header_path.exists():
        print(f"  SKIP {filename}: header not found at {header_path}")
        return False

    # Read source
    with open(source_path) as f:
        source_lines = f.readlines()

    # Read header
    header_text = header_path.read_text() if header_path.exists() else ""

    # Read inline JSON
    inline_data = None
    if inline_path.exists():
        try:
            inline_data = json.loads(inline_path.read_text())
        except json.JSONDecodeError as e:
            print(f"  WARN {filename}: inline JSON parse error: {e}")

    # Read footer
    footer_text = footer_path.read_text() if footer_path.exists() else ""

    # Insert
    result_lines = insert_all(source_lines, header_text, inline_data, footer_text, filename)

    # Write preview
    with open(preview_path, "w") as f:
        f.writelines(result_lines)

    orig_lines = len(source_lines)
    new_lines = len(result_lines)
    inline_count = len(inline_data.get("inline_comments", [])) if inline_data else 0

    print(f"  {filename}:")
    print(f"    Original: {orig_lines} lines")
    print(f"    Header: {'yes' if header_text.strip() else 'no'}")
    print(f"    Inline: {inline_count} function annotations")
    print(f"    Footer: {'yes' if footer_text.strip() else 'no'}")
    print(f"    Preview: {new_lines} lines -> {preview_path}")
    print(f"    Size: {os.path.getsize(preview_path):,} bytes")
    print()
    return True


# All 15 files from file_dossiers.json
ALL_FILES = [
    "unified_orchestrator.py",
    "geological_reader.py",
    "hyperdoc_pipeline.py",
    "story_marker_generator.py",
    "six_thread_extractor.py",
    "geological_pipeline.py",
    "marker_generator.py",
    "opus_logger.py",
    "opus_struggle_analyzer.py",
    "layer_builder.py",
    "resurrection_engine.py",
    "tiered_llm_caller.py",
    "semantic_chunker.py",
    "anti_resurrection.py",
    "four_thread_extractor.py",
]


def main():
    print("=" * 60)
    print("Smart Hyperdoc Insertion V2 — Header + Inline + Footer")
    print("=" * 60)
    print(f"Source dir:     {V5_CODE}")
    print(f"Hyperdoc dir:   {HYPERDOC_V2_DIR}")
    print(f"Preview dir:    {PREVIEW_DIR}")
    print(f"Timestamp:      {datetime.now().isoformat()}")
    print()

    PREVIEW_DIR.mkdir(exist_ok=True)

    success = 0
    skipped = 0

    for filename in ALL_FILES:
        if process_file(filename):
            success += 1
        else:
            skipped += 1

    print("=" * 60)
    print(f"Results: {success} files processed, {skipped} skipped")
    print(f"Previews at: {PREVIEW_DIR}")
    print("These are COPIES — originals are untouched.")


if __name__ == "__main__":
    main()
