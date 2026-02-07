#!/usr/bin/env python3
"""
Insert hyperdoc blocks into copies of the original code files.

Places the hyperdoc comment block after imports and module-level code,
before the first class or function definition. This is the canonical
position: the first thing a future Claude reads after understanding
what the file imports.
"""
import re
import os
from pathlib import Path

BASE = Path(__file__).parent
V5_CODE = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_2" / "V5" / "code"
BLOCKS_DIR = BASE / "hyperdoc_blocks"
PREVIEW_DIR = BASE / "hyperdoc_previews"
PREVIEW_DIR.mkdir(exist_ok=True)

# Map hyperdoc block files to source code files
FILE_MAP = {
    "unified_orchestrator_hyperdoc.txt": "unified_orchestrator.py",
    "geological_reader_hyperdoc.txt": "geological_reader.py",
    "hyperdoc_pipeline_hyperdoc.txt": "hyperdoc_pipeline.py",
    "story_marker_generator_hyperdoc.txt": "story_marker_generator.py",
    "six_thread_extractor_hyperdoc.txt": "six_thread_extractor.py",
}


def find_insertion_point(lines):
    """
    Find the line index where the hyperdoc should be inserted.

    Strategy:
    1. Skip shebang line (#!) if present
    2. Skip module docstring (triple-quoted)
    3. Skip all import lines and module-level assignments/comments
    4. Insert BEFORE the first class/function definition or decorated definition

    Returns the line index where insertion should happen.
    """
    i = 0
    n = len(lines)

    # Skip shebang
    if i < n and lines[i].startswith("#!"):
        i += 1

    # Skip blank lines after shebang
    while i < n and lines[i].strip() == "":
        i += 1

    # Skip module docstring (triple quote)
    if i < n and (lines[i].strip().startswith('"""') or lines[i].strip().startswith("'''")):
        quote = lines[i].strip()[:3]
        # Check if single-line docstring
        if lines[i].strip().count(quote) >= 2:
            i += 1
        else:
            # Multi-line docstring — find closing quotes
            i += 1
            while i < n and quote not in lines[i]:
                i += 1
            if i < n:
                i += 1  # Skip the closing line

    # Skip blank lines after docstring
    while i < n and lines[i].strip() == "":
        i += 1

    # Skip comments that are part of the module header (before imports)
    # These are often architectural notes like #ARCHITECTURE:, #WHY:, etc.
    while i < n and lines[i].strip().startswith("#"):
        i += 1

    # Skip blank lines
    while i < n and lines[i].strip() == "":
        i += 1

    # Now skip all imports and module-level setup code
    # This includes: import, from...import, try/except import blocks,
    # module-level assignments, load_dotenv(), client = ..., etc.
    in_try_block = False
    last_import_end = i

    while i < n:
        stripped = lines[i].strip()

        # Skip blank lines
        if stripped == "":
            i += 1
            continue

        # Skip comments between imports
        if stripped.startswith("#"):
            i += 1
            continue

        # Import statements
        if stripped.startswith("import ") or stripped.startswith("from "):
            i += 1
            # Handle multi-line imports (parenthesized)
            if "(" in stripped and ")" not in stripped:
                while i < n and ")" not in lines[i]:
                    i += 1
                if i < n:
                    i += 1
            last_import_end = i
            continue

        # try/except blocks (common for conditional imports)
        if stripped.startswith("try:"):
            in_try_block = True
            i += 1
            continue
        if stripped.startswith("except") and in_try_block:
            i += 1
            # Skip the except body
            while i < n and (lines[i].startswith("    ") or lines[i].strip() == ""):
                i += 1
            in_try_block = False
            last_import_end = i
            continue
        if in_try_block:
            i += 1
            continue

        # Module-level setup (common patterns in V5 code)
        # load_dotenv(), client = Anthropic(), PROJECT_ROOT = ..., etc.
        if any(stripped.startswith(p) for p in [
            "load_dotenv", "PROJECT_ROOT", "client ", "client=",
            "API_CALL_LOG", "DAYS ", "DAYS=",
        ]):
            i += 1
            last_import_end = i
            continue

        # Module-level assignments that look like constants
        if re.match(r'^[A-Z_]+ = ', stripped):
            i += 1
            last_import_end = i
            continue

        # Module-level function calls (setup)
        if re.match(r'^[a-z_]+\(', stripped) and not stripped.startswith("def "):
            i += 1
            last_import_end = i
            continue

        # Stop: we've hit a class, function, decorator, or dataclass
        if (stripped.startswith("class ") or
            stripped.startswith("def ") or
            stripped.startswith("@")):
            break

        # If we get here, it's some other module-level code — skip it
        i += 1
        last_import_end = i

    return last_import_end


def insert_hyperdoc(source_lines, hyperdoc_text, filename):
    """Insert hyperdoc block at the appropriate position in source code."""
    insertion_point = find_insertion_point(source_lines)

    # Build the result
    result = []

    # Everything before insertion point
    result.extend(source_lines[:insertion_point])

    # Add a blank line separator if the previous line isn't blank
    if result and result[-1].strip() != "":
        result.append("\n")

    # Add the hyperdoc block
    result.append("\n")
    for line in hyperdoc_text.splitlines():
        result.append(line + "\n")
    result.append("\n")
    result.append("\n")

    # Everything after insertion point
    result.extend(source_lines[insertion_point:])

    return result


def main():
    print("Inserting hyperdocs into code file copies...")
    print(f"Source dir: {V5_CODE}")
    print(f"Blocks dir: {BLOCKS_DIR}")
    print(f"Preview dir: {PREVIEW_DIR}")
    print()

    for block_file, source_file in FILE_MAP.items():
        block_path = BLOCKS_DIR / block_file
        source_path = V5_CODE / source_file
        preview_path = PREVIEW_DIR / source_file

        if not source_path.exists():
            print(f"  SKIP {source_file}: source not found at {source_path}")
            continue
        if not block_path.exists():
            print(f"  SKIP {source_file}: hyperdoc block not found at {block_path}")
            continue

        # Read source
        with open(source_path) as f:
            source_lines = f.readlines()

        # Read hyperdoc block
        hyperdoc_text = block_path.read_text()

        # Find insertion point
        insertion_point = find_insertion_point(source_lines)

        # Insert
        result_lines = insert_hyperdoc(source_lines, hyperdoc_text, source_file)

        # Write preview
        with open(preview_path, "w") as f:
            f.writelines(result_lines)

        orig_lines = len(source_lines)
        new_lines = len(result_lines)
        hyperdoc_lines = len(hyperdoc_text.splitlines())

        print(f"  {source_file}:")
        print(f"    Original: {orig_lines} lines")
        print(f"    Hyperdoc: {hyperdoc_lines} lines inserted at line {insertion_point}")
        print(f"    Preview:  {new_lines} lines → {preview_path}")
        print(f"    Size:     {os.path.getsize(preview_path):,} bytes")
        print()

    print(f"Done. All previews in: {PREVIEW_DIR}")
    print("These are COPIES — originals are untouched.")


if __name__ == "__main__":
    main()
