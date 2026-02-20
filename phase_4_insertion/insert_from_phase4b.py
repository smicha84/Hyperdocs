#!/usr/bin/env python3
"""
Phase 5: Insert hyperdocs from Phase 4b JSON into source code files.

Reads from: output/hyperdocs/*_hyperdoc.json
Writes to:  output/enhanced_files/{filename}  (COPIES — originals untouched)

Each hyperdoc JSON has:
  - header: multiline string → inserted after imports, before first class/function
  - inline_annotations: [{target, target_type, comment_lines}, ...] → inserted before each target
  - footer: multiline string → appended at end of file

Only processes files that exist on disk. Skips deleted/archived/ghost files.
"""
import ast
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
HYPERDOCS_DIR = Path(__file__).resolve().parent.parent / "output" / "hyperdocs"
ENHANCED_DIR = Path(__file__).resolve().parent.parent / "output" / "enhanced_files"
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"


def find_source_file(file_path_field):
    """
    Locate the actual source file on disk from the hyperdoc's file_path field.
    Searches: project root, hooks dir, apps dir, archive dirs, hyperdocs_2 dirs.
    """
    fp = Path(file_path_field)
    name = fp.name

    # Try exact path from project root
    candidate = PROJECT_ROOT / fp
    if candidate.exists():
        return candidate

    # Try hooks directory with bare filename
    candidate = HOOKS_DIR / name
    if candidate.exists():
        return candidate

    # Try hooks directory with full relative path
    candidate = HOOKS_DIR / fp
    if candidate.exists():
        return candidate

    # Try docs subdirectory
    candidate = HOOKS_DIR / "docs" / name
    if candidate.exists():
        return candidate

    # Search apps directories
    apps_dir = PROJECT_ROOT / "apps"
    if apps_dir.exists():
        for match in apps_dir.rglob(name):
            return match

    # Search archive directories
    for archive_base in [
        PROJECT_ROOT / "archive",
        HOOKS_DIR / "hyperdoc" / "archive",
        HOOKS_DIR / "hyperdoc" / "hyperdocs_2" / "V1" / "code",
        HOOKS_DIR / "hyperdoc" / "hyperdocs_2" / "V2" / "code",
        HOOKS_DIR / "hyperdoc" / "hyperdocs_2" / "V5" / "code",
        HOOKS_DIR / "hyperdoc" / "hyperdocs_3",
        PROJECT_ROOT / "output",
    ]:
        if archive_base.exists():
            for match in archive_base.rglob(name):
                # Skip our own output
                if "enhanced_files" in str(match) or "hyperdoc_inputs" in str(match):
                    continue
                return match

    return None


def find_header_insertion_point(lines):
    """
    Find the line index where the header should be inserted.
    After imports/module-level setup, before first class/function/decorator.
    Reuses proven logic from insert_hyperdocs_v2.py.
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

    # Skip header comments
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
    Use AST to find all function/class definitions.
    Returns list of {name, type, line, decorator_line}.
    Line numbers are 1-indexed.
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

    locations.sort(key=lambda x: x["line"])
    return locations


def format_comment_block(text, prefix="# "):
    """Convert a multiline string into comment lines."""
    lines = []
    for line in text.splitlines():
        if line.strip() == "":
            lines.append("#\n")
        else:
            lines.append(f"{prefix}{line}\n")
    return lines


def insert_all(source_lines, header_text, inline_annotations, footer_text):
    """
    Insert header, inline annotations, and footer into source lines.
    Returns new list of lines.
    """
    source_text = "".join(source_lines)
    ast_locations = get_function_class_locations(source_text)

    # Build name → insertion line map (0-indexed)
    name_to_line = {}
    for loc in ast_locations:
        name_to_line[loc["name"]] = loc["decorator_line"] - 1

    # Build inline insertion map: line_index → formatted comment lines
    inline_insertions = {}
    if inline_annotations:
        for entry in inline_annotations:
            target = entry.get("target", "")
            comment_lines = entry.get("comment_lines", [])
            if target in name_to_line and comment_lines:
                line_idx = name_to_line[target]
                formatted = []
                for cl in comment_lines:
                    formatted.append(f"# {cl}\n")
                inline_insertions[line_idx] = formatted

    # Find header insertion point
    header_point = find_header_insertion_point(source_lines)

    # Collect all insertions
    insertions = []

    # Header
    if header_text and header_text.strip():
        header_lines = format_comment_block(header_text)
        insertions.append((header_point, header_lines, "header"))

    # Inline annotations
    for line_idx, comment_lines in sorted(inline_insertions.items()):
        insertions.append((line_idx, comment_lines, "inline"))

    # Sort bottom-first to avoid index shifts
    insertions.sort(key=lambda x: x[0], reverse=True)

    result = list(source_lines)

    for insert_idx, insert_lines, insert_type in insertions:
        padded = []
        if insert_type == "header":
            padded.append("\n")
            padded.append("# " + "=" * 70 + "\n")
            padded.append("# @ctx HYPERDOC — Phase 4b Generated\n")
            padded.append("# " + "=" * 70 + "\n")
            padded.extend(insert_lines)
            padded.append("# " + "=" * 70 + "\n")
            padded.append("\n")
        elif insert_type == "inline":
            padded.append("# @ctx:inline ----\n")
            padded.extend(insert_lines)
            padded.append("# ----\n")

        result[insert_idx:insert_idx] = padded

    # Footer: append at end
    if footer_text and footer_text.strip():
        result.append("\n\n")
        result.append("# " + "=" * 70 + "\n")
        result.append("# @ctx HYPERDOC FOOTER\n")
        result.append("# " + "=" * 70 + "\n")
        for line in footer_text.splitlines():
            if line.strip() == "":
                result.append("#\n")
            else:
                result.append(f"# {line}\n")
        result.append("# " + "=" * 70 + "\n")

    return result


def process_non_python(source_path, data, file_path, stats):
    """Handle non-Python files with appropriate comment syntax."""
    ext = source_path.suffix
    header = data.get("header", "")
    footer = data.get("footer", "")

    if not header and not footer:
        stats["skipped_empty"] += 1
        return

    # Determine comment syntax
    if ext in (".md", ".txt"):
        # Use HTML comments for markdown/text
        prefix_start = "<!-- @ctx HYPERDOC\n"
        prefix_end = "-->\n"
        line_prefix = ""
    elif ext in (".html",):
        prefix_start = "<!-- @ctx HYPERDOC\n"
        prefix_end = "-->\n"
        line_prefix = ""
    elif ext in (".js",):
        prefix_start = "/* @ctx HYPERDOC\n"
        prefix_end = "*/\n"
        line_prefix = " * "
    elif ext in (".json",):
        # JSON cannot have comments — write as a companion .hyperdoc.md file
        out_name = Path(file_path).name + ".hyperdoc.md"
        out_path = ENHANCED_DIR / out_name
        content = f"# Hyperdoc: {file_path}\n\n"
        if header:
            content += header + "\n\n"
        if footer:
            content += "---\n\n" + footer + "\n"
        out_path.write_text(content)
        stats["success"] += 1
        stats["total_enhanced_lines"] += content.count("\n")
        return
    elif ext in (".toml",):
        prefix_start = "# @ctx HYPERDOC\n"
        prefix_end = "# /HYPERDOC\n"
        line_prefix = "# "
    else:
        stats["skipped_non_python"] += 1
        return

    try:
        source_text = source_path.read_text()
    except (OSError, UnicodeDecodeError):
        stats["errors"].append(f"{file_path}: read error")
        return

    result = ""

    # For MD/HTML/JS/TOML: prepend header, append footer
    if header:
        result += prefix_start
        for line in header.splitlines():
            result += line_prefix + line + "\n"
        result += prefix_end + "\n"

    result += source_text

    if footer:
        result += "\n\n"
        result += prefix_start.replace("HYPERDOC", "HYPERDOC FOOTER")
        for line in footer.splitlines():
            result += line_prefix + line + "\n"
        result += prefix_end

    out_name = Path(file_path).name
    out_path = ENHANCED_DIR / out_name
    if out_path.exists():
        parent = Path(file_path).parent.name or "root"
        out_path = ENHANCED_DIR / f"{parent}__{out_name}"

    out_path.write_text(result)

    orig = source_text.count("\n")
    enhanced = result.count("\n")
    stats["success"] += 1
    stats["total_original_lines"] += orig
    stats["total_enhanced_lines"] += enhanced


def process_hyperdoc(hyperdoc_path, stats):
    """Process one hyperdoc JSON file."""
    try:
        data = json.loads(hyperdoc_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        stats["errors"].append(f"{hyperdoc_path.name}: JSON error: {e}")
        return

    file_path = data.get("file_path", "")
    if not file_path:
        stats["errors"].append(f"{hyperdoc_path.name}: no file_path field")
        return

    # Find source file
    source_path = find_source_file(file_path)
    if source_path is None:
        stats["skipped_missing"] += 1
        return

    # Handle non-Python files with appropriate comment syntax
    if source_path.suffix != ".py":
        return process_non_python(source_path, data, file_path, stats)

    # Read source
    try:
        source_lines = source_path.read_text().splitlines(keepends=True)
    except (OSError, UnicodeDecodeError) as e:
        stats["errors"].append(f"{file_path}: read error: {e}")
        return

    header = data.get("header", "")
    inline_annotations = data.get("inline_annotations", [])
    footer = data.get("footer", "")

    # Skip if no content
    if not header and not inline_annotations and not footer:
        stats["skipped_empty"] += 1
        return

    # Insert
    result_lines = insert_all(source_lines, header, inline_annotations, footer)

    # Determine output path — preserve relative structure
    safe_name = file_path.replace("/", "_").replace(".", "_") + ".py"
    # Use the actual filename for readability
    out_name = Path(file_path).name
    # Handle duplicates by prefixing with parent dir
    out_path = ENHANCED_DIR / out_name
    if out_path.exists():
        parent = Path(file_path).parent.name or "root"
        out_path = ENHANCED_DIR / f"{parent}__{out_name}"

    out_path.write_text("".join(result_lines))

    orig = len(source_lines)
    enhanced = len(result_lines)
    inline_count = len([a for a in inline_annotations if a.get("comment_lines")])

    stats["success"] += 1
    stats["total_original_lines"] += orig
    stats["total_enhanced_lines"] += enhanced
    stats["total_inline_annotations"] += inline_count

    if stats["success"] <= 10 or stats["success"] % 50 == 0:
        print(f"  {file_path}: {orig} → {enhanced} lines (+{enhanced - orig}), "
              f"{inline_count} inline annotations")


def main():
    print("=" * 70)
    print("Phase 5: Insert Hyperdocs from Phase 4b into Source Files")
    print("=" * 70)
    print(f"Hyperdocs dir:  {HYPERDOCS_DIR}")
    print(f"Hooks dir:      {HOOKS_DIR}")
    print(f"Output dir:     {ENHANCED_DIR}")
    print(f"Timestamp:      {datetime.now().isoformat()}")
    print()

    ENHANCED_DIR.mkdir(parents=True, exist_ok=True)

    hyperdoc_files = sorted(HYPERDOCS_DIR.glob("*_hyperdoc.json"))
    print(f"Found {len(hyperdoc_files)} hyperdoc JSON files")
    print()

    stats = {
        "success": 0,
        "skipped_missing": 0,
        "skipped_non_python": 0,
        "skipped_empty": 0,
        "errors": [],
        "total_original_lines": 0,
        "total_enhanced_lines": 0,
        "total_inline_annotations": 0,
    }

    for hf in hyperdoc_files:
        process_hyperdoc(hf, stats)

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Enhanced:              {stats['success']} files")
    print(f"  Skipped (not on disk): {stats['skipped_missing']}")
    print(f"  Skipped (non-Python):  {stats['skipped_non_python']}")
    print(f"  Skipped (empty):       {stats['skipped_empty']}")
    print(f"  Errors:                {len(stats['errors'])}")
    print()
    print(f"  Total original lines:  {stats['total_original_lines']:,}")
    print(f"  Total enhanced lines:  {stats['total_enhanced_lines']:,}")
    print(f"  Lines added:           {stats['total_enhanced_lines'] - stats['total_original_lines']:,}")
    print(f"  Inline annotations:    {stats['total_inline_annotations']}")
    print()
    print(f"  Enhanced files at: {ENHANCED_DIR}")
    print(f"  These are COPIES — originals are UNTOUCHED.")

    if stats["errors"]:
        print()
        print("ERRORS:")
        for e in stats["errors"][:20]:
            print(f"  {e}")

    return 0 if not stats["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
