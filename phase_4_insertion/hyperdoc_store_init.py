#!/usr/bin/env python3
"""
Hyperdoc Store Initialization — Versioned External Storage

Creates the versioned directory structure for hyperdocs:
  .claude/hooks/hyperdoc/hyperdocs_2/hyperdoc_store/
  ├── {filename}/
  │   ├── v1_2026-02-06.json   ← Full data (header + inline + footer + dossier)
  │   ├── current_header.txt   ← Rendered header for insertion
  │   ├── current_inline.json  ← Rendered inline mapping
  │   └── current_footer.txt   ← Rendered footer
  └── _index.json              ← Index of all files, versions, timestamps

Populates v1 from current session outputs (hyperdoc_v2/ directory).
"""
import json
import shutil
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
SESSION_ID = "3b7084d5"
HYPERDOC_V2_DIR = BASE / "hyperdoc_v2"
DOSSIERS_PATH = BASE / "file_dossiers.json"

STORE_ROOT = BASE.parent.parent / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_2" / "hyperdoc_store"

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


def load_dossier_for_file(filename):
    """Load the dossier entry for a specific file."""
    if not DOSSIERS_PATH.exists():
        return {}
    with open(DOSSIERS_PATH) as f:
        data = json.load(f)
    for entry in data.get("files", []):
        if entry.get("filename") == filename:
            return entry
    return {}


def init_file_store(filename, now_str, date_str):
    """
    Initialize the store for one file.
    Creates directory, populates v1, copies current rendered files.
    Returns dict with status info.
    """
    file_dir = STORE_ROOT / filename
    file_dir.mkdir(parents=True, exist_ok=True)

    header_src = HYPERDOC_V2_DIR / f"{filename}_header.txt"
    inline_src = HYPERDOC_V2_DIR / f"{filename}_inline.json"
    footer_src = HYPERDOC_V2_DIR / f"{filename}_footer.txt"

    # Read available parts
    header_text = header_src.read_text() if header_src.exists() else ""
    footer_text = footer_src.read_text() if footer_src.exists() else ""

    inline_data = None
    if inline_src.exists():
        try:
            inline_data = json.loads(inline_src.read_text())
        except json.JSONDecodeError:
            inline_data = None

    dossier = load_dossier_for_file(filename)

    # Build v1 JSON — full data archive
    v1_data = {
        "file": filename,
        "version": 1,
        "generated_at": now_str,
        "source_session": f"conv_{SESSION_ID}",
        "header_text": header_text,
        "inline_data": inline_data,
        "footer_text": footer_text,
        "dossier": dossier,
    }

    v1_path = file_dir / f"v1_{date_str}.json"
    with open(v1_path, "w") as f:
        json.dump(v1_data, f, indent=2)

    # Copy current rendered files
    parts_copied = 0
    if header_text:
        (file_dir / "current_header.txt").write_text(header_text)
        parts_copied += 1
    if inline_data:
        (file_dir / "current_inline.json").write_text(json.dumps(inline_data, indent=2))
        parts_copied += 1
    if footer_text:
        (file_dir / "current_footer.txt").write_text(footer_text)
        parts_copied += 1

    return {
        "filename": filename,
        "v1_path": str(v1_path),
        "v1_size": v1_path.stat().st_size,
        "parts_copied": parts_copied,
        "has_header": bool(header_text),
        "has_inline": inline_data is not None,
        "has_footer": bool(footer_text),
        "has_dossier": bool(dossier),
    }


def build_index(results, now_str):
    """Build _index.json with metadata about all stored files."""
    index = {
        "store_version": 1,
        "created_at": now_str,
        "session": f"conv_{SESSION_ID}",
        "total_files": len(results),
        "files": {},
    }

    for r in results:
        index["files"][r["filename"]] = {
            "latest_version": 1,
            "versions": [
                {
                    "version": 1,
                    "date": now_str,
                    "session": f"conv_{SESSION_ID}",
                    "has_header": r["has_header"],
                    "has_inline": r["has_inline"],
                    "has_footer": r["has_footer"],
                }
            ],
        }

    index_path = STORE_ROOT / "_index.json"
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    return index_path


def main():
    now = datetime.now()
    now_str = now.isoformat()
    date_str = now.strftime("%Y-%m-%d")

    print("=" * 60)
    print("Hyperdoc Store Initialization")
    print("=" * 60)
    print(f"Store root:    {STORE_ROOT}")
    print(f"Source dir:    {HYPERDOC_V2_DIR}")
    print(f"Session:       conv_{SESSION_ID}")
    print(f"Timestamp:     {now_str}")
    print()

    STORE_ROOT.mkdir(parents=True, exist_ok=True)

    results = []
    for filename in ALL_FILES:
        r = init_file_store(filename, now_str, date_str)
        results.append(r)
        status = "OK" if r["parts_copied"] > 0 else "EMPTY"
        print(f"  [{status}] {filename}: v1 ({r['v1_size']:,} bytes), "
              f"{r['parts_copied']} parts, dossier={'yes' if r['has_dossier'] else 'no'}")

    index_path = build_index(results, now_str)

    total_with_data = sum(1 for r in results if r["parts_copied"] > 0)
    total_empty = sum(1 for r in results if r["parts_copied"] == 0)

    print()
    print("=" * 60)
    print(f"Results: {total_with_data} files with data, {total_empty} empty")
    print(f"Index at: {index_path}")
    print(f"Store at: {STORE_ROOT}")


if __name__ == "__main__":
    main()
