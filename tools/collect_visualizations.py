#!/usr/bin/env python3
"""
Collect HTML visualization files from multiple source locations
into wrecktangle-site/public/viz-gallery/ for the curation gallery.

Source locations:
  ~/.agent/diagrams/*.html
  ~/Hyperdocs/*.html (root level only)
  ~/Hyperdocs/completed/*.html
  ~/Hyperdocs/output/*.html
  ~/Hyperdocs/tools/**/*.html
  ~/PERMANENT_HYPERDOCS/genealogy_dashboard.html
  ~/PERMANENT_HYPERDOCS/sessions/*/pipeline_viewer.html

Deduplication:
  - pipeline_viewer.html files are renamed to pipeline_viewer_<session_id>.html
  - Other duplicates: keeps the newest copy by mtime
"""

import glob
import json
import os
import shutil
from pathlib import Path

HOME = Path.home()
DEST = HOME / "wrecktangle-site" / "public" / "viz-gallery"

# Source locations: list of (glob_pattern, label)
SOURCES = [
    (str(HOME / ".agent" / "diagrams" / "*.html"), "agent-diagrams"),
    (str(HOME / "Hyperdocs" / "*.html"), "hyperdocs-root"),
    (str(HOME / "Hyperdocs" / "completed" / "*.html"), "hyperdocs-completed"),
    (str(HOME / "Hyperdocs" / "output" / "*.html"), "hyperdocs-output"),
    (str(HOME / "Hyperdocs" / "tools" / "**" / "*.html"), "hyperdocs-tools"),
    (str(HOME / "PERMANENT_HYPERDOCS" / "genealogy_dashboard.html"), "permanent"),
    (str(HOME / "PERMANENT_HYPERDOCS" / "sessions" / "*" / "pipeline_viewer.html"), "pipeline-viewers"),
]


def collect_files():
    """Scan all sources and return a list of (src_path, dest_filename, source_label)."""
    candidates = {}  # dest_filename -> (src_path, mtime, source_label)

    for pattern, label in SOURCES:
        for src in glob.glob(pattern, recursive=True):
            src_path = Path(src)
            if not src_path.is_file():
                continue

            # Pipeline viewers: namespace by session ID to avoid collisions
            if label == "pipeline-viewers":
                session_id = src_path.parent.name.replace("session_", "")
                dest_name = f"pipeline_viewer_{session_id}.html"
            else:
                dest_name = src_path.name

            mtime = src_path.stat().st_mtime
            size_kb = round(src_path.stat().st_size / 1024, 1)

            # Dedup: keep the newest copy
            if dest_name in candidates:
                existing_mtime = candidates[dest_name][1]
                if mtime <= existing_mtime:
                    continue

            candidates[dest_name] = (str(src_path), mtime, label, size_kb)

    return candidates


def main():
    # Ensure destination exists
    DEST.mkdir(parents=True, exist_ok=True)

    candidates = collect_files()
    manifest = []

    for dest_name, (src_path, mtime, label, size_kb) in sorted(candidates.items()):
        dest_path = DEST / dest_name
        shutil.copy2(src_path, dest_path)

        manifest.append({
            "filename": dest_name,
            "source": label,
            "original_path": src_path,
            "size_kb": size_kb,
        })

    # Write manifest
    manifest_path = DEST / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Collected {len(manifest)} HTML files into {DEST}")
    print(f"Manifest written to {manifest_path}")

    # Summary by source
    by_source = {}
    for entry in manifest:
        by_source.setdefault(entry["source"], []).append(entry["filename"])
    for source, files in sorted(by_source.items()):
        print(f"  {source}: {len(files)} files")


if __name__ == "__main__":
    main()
