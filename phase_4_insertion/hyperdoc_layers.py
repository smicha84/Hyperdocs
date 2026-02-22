#!/usr/bin/env python3
"""
Hyperdoc Layer Manager
======================

Hyperdocs grow. They never shrink. Each pipeline run appends a layer.

Layer types:
  - historical:  From batch processing (the original 456 hyperdocs)
  - realtime:    From incremental/continuous processing
  - seed:        Created when a new file is born (before code is written)
  - verification: Ground truth check results

The cumulative_summary aggregates across all layers.

Usage:
    # Migrate existing hyperdoc to layered format:
    python3 hyperdoc_layers.py --migrate ~/PERMANENT_HYPERDOCS/hyperdocs/

    # Add a layer to an existing hyperdoc:
    from phase_4_insertion.hyperdoc_layers import HyperdocLayerManager
    mgr = HyperdocLayerManager()
    mgr.append_layer("gate_control.py", layer_data)

    # Generate a seed hyperdoc for a new file:
    mgr.create_seed("new_file.py", context="Created for user auth", related=["auth.py"])
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from copy import deepcopy


try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import HYPERDOCS_STORE_DIR
    HYPERDOCS_DIR = HYPERDOCS_STORE_DIR
except ImportError:
    HYPERDOCS_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "hyperdocs"


class HyperdocLayerManager:
    """Manages the layered hyperdoc format."""

    def __init__(self, hyperdocs_dir: str = None):
        self.dir = Path(hyperdocs_dir) if hyperdocs_dir else HYPERDOCS_DIR

    def _hyperdoc_path(self, filename: str) -> Path:
        """Get the path for a file's hyperdoc."""
        stem = filename.replace(".py", "").replace("/", "_").replace(".", "_")
        return self.dir / f"{stem}_hyperdoc.json"

    def load(self, filename: str) -> dict:
        """Load a hyperdoc, returning layered format."""
        path = self._hyperdoc_path(filename)
        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)

        # If already layered, return as-is
        if "layers" in data:
            return data

        # If old format, wrap as single historical layer
        return self._convert_to_layered(data)

    def save(self, filename: str, hyperdoc: dict):
        """Save a layered hyperdoc."""
        path = self._hyperdoc_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(hyperdoc, f, indent=2, default=str)

    def _convert_to_layered(self, old_format: dict) -> dict:
        """Convert old snapshot format to layered format."""
        layer = {
            "session_id": "batch_historical",
            "generated_at": old_format.get("generated_at", "unknown"),
            "type": "historical",
            "generator": old_format.get("generator", "Phase 4b Opus"),
            "header": old_format.get("header", ""),
            "inline_annotations": old_format.get("inline_annotations", []),
            "footer": old_format.get("footer", ""),
        }

        return {
            "file_path": old_format.get("file_path", ""),
            "format_version": 2,
            "migrated_at": datetime.now().isoformat(),
            "layers": [layer],
            "cumulative_summary": {
                "total_layers": 1,
                "total_sessions": old_format.get("session_count", 0),
                "total_mentions": old_format.get("cross_session_mentions", 0),
                "layer_types": {"historical": 1},
                "first_seen": old_format.get("generated_at", "unknown"),
                "last_updated": old_format.get("generated_at", "unknown"),
            },
        }

    def append_layer(self, filename: str, layer: dict) -> dict:
        """Append a new layer to an existing hyperdoc."""
        hyperdoc = self.load(filename)

        if hyperdoc is None:
            # No existing hyperdoc — create new with this layer
            hyperdoc = {
                "file_path": filename,
                "format_version": 2,
                "migrated_at": datetime.now().isoformat(),
                "layers": [],
                "cumulative_summary": {
                    "total_layers": 0,
                    "total_sessions": 0,
                    "layer_types": {},
                    "first_seen": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat(),
                },
            }

        # Ensure layer has required fields
        layer.setdefault("generated_at", datetime.now().isoformat())
        layer.setdefault("type", "realtime")

        hyperdoc["layers"].append(layer)

        # Update cumulative summary
        summary = hyperdoc["cumulative_summary"]
        summary["total_layers"] = len(hyperdoc["layers"])
        summary["total_sessions"] = summary.get("total_sessions", 0) + 1
        summary["last_updated"] = datetime.now().isoformat()

        layer_type = layer.get("type", "unknown")
        type_counts = summary.get("layer_types", {})
        type_counts[layer_type] = type_counts.get(layer_type, 0) + 1
        summary["layer_types"] = type_counts

        self.save(filename, hyperdoc)
        return hyperdoc

    def create_seed(self, filename: str, context: str, related_files: list = None,
                    alternatives: list = None, purpose: str = None) -> dict:
        """
        Create a seed hyperdoc for a file that is about to be created.
        The seed captures WHY this file exists before any code is written.
        """
        existing = self.load(filename)
        if existing and existing.get("layers"):
            # Already has a hyperdoc — don't overwrite
            return existing

        seed_layer = {
            "session_id": os.getenv("CLAUDE_SESSION_ID", "unknown"),
            "generated_at": datetime.now().isoformat(),
            "type": "seed",
            "creation_context": context,
            "purpose": purpose or "",
            "alternatives_considered": alternatives or [],
            "related_files": related_files or [],
            "header": f"@ctx:type=seed @ctx:created={datetime.now().strftime('%Y-%m-%d')} @ctx:state=new\n"
                      f"@ctx:context=\"{context}\"\n"
                      f"This file was created with documented provenance. The conversation that led to\n"
                      f"its creation has been captured before any code was written.",
            "inline_annotations": [],
            "footer": f"Seed hyperdoc. File does not yet contain code.\n"
                      f"Related files: {', '.join(related_files or ['none detected'])}\n"
                      f"Alternatives considered: {', '.join(alternatives or ['none recorded'])}",
        }

        return self.append_layer(filename, seed_layer)

    def get_layer_summary(self, filename: str) -> dict:
        """Get a summary of all layers for a file."""
        hyperdoc = self.load(filename)
        if not hyperdoc:
            return {"exists": False, "layers": 0}

        layers = hyperdoc.get("layers", [])
        return {
            "exists": True,
            "file_path": hyperdoc.get("file_path", filename),
            "layers": len(layers),
            "layer_types": [l.get("type", "unknown") for l in layers],
            "first_seen": layers[0].get("generated_at", "unknown") if layers else "unknown",
            "last_updated": layers[-1].get("generated_at", "unknown") if layers else "unknown",
            "has_seed": any(l.get("type") == "seed" for l in layers),
            "has_historical": any(l.get("type") == "historical" for l in layers),
            "has_realtime": any(l.get("type") == "realtime" for l in layers),
            "cumulative": hyperdoc.get("cumulative_summary", {}),
        }


# ── Migration ─────────────────────────────────────────────────────────────

def migrate_directory(hyperdocs_dir: Path, dry_run: bool = False):
    """Migrate all existing hyperdocs from snapshot format to layered format."""
    files = sorted(hyperdocs_dir.glob("*_hyperdoc.json"))
    print(f"Found {len(files)} hyperdoc files")

    already_layered = 0
    migrated = 0
    errors = 0

    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)

            if "layers" in data:
                already_layered += 1
                continue

            if "format_version" in data and data["format_version"] >= 2:
                already_layered += 1
                continue

            # Convert to layered format
            mgr = HyperdocLayerManager(str(hyperdocs_dir))
            layered = mgr._convert_to_layered(data)

            if dry_run:
                print(f"  [DRY RUN] Would migrate: {path.name} ({len(data.get('inline_annotations', []))} annotations)")
            else:
                with open(path, "w") as f:
                    json.dump(layered, f, indent=2, default=str)
                migrated += 1

        except (json.JSONDecodeError, IOError, KeyError) as e:
            errors += 1
            print(f"  ERROR: {path.name}: {e}")

    print(f"\nResults:")
    print(f"  Already layered: {already_layered}")
    print(f"  Migrated: {migrated}")
    print(f"  Errors: {errors}")
    print(f"  Total: {already_layered + migrated + errors}")
    return {"already_layered": already_layered, "migrated": migrated, "errors": errors}


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Hyperdoc Layer Manager")
    parser.add_argument("--migrate", type=str, help="Migrate directory to layered format")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without changing files")
    parser.add_argument("--seed", nargs=2, metavar=("FILE", "CONTEXT"), help="Create seed hyperdoc")
    parser.add_argument("--summary", type=str, help="Show layer summary for a file")
    parser.add_argument("--stats", action="store_true", help="Show stats for all hyperdocs")
    args = parser.parse_args()

    if args.migrate:
        migrate_directory(Path(args.migrate), dry_run=args.dry_run)
        return

    mgr = HyperdocLayerManager()

    if args.seed:
        filename, context = args.seed
        result = mgr.create_seed(filename, context)
        print(f"Seed hyperdoc created for {filename}")
        print(f"  Layers: {len(result['layers'])}")
        print(f"  Path: {mgr._hyperdoc_path(filename)}")
        return

    if args.summary:
        summary = mgr.get_layer_summary(args.summary)
        print(json.dumps(summary, indent=2))
        return

    if args.stats:
        files = sorted(HYPERDOCS_DIR.glob("*_hyperdoc.json"))
        layered = 0
        snapshot = 0
        for f in files:
            with open(f) as fh:
                d = json.load(fh)
            if "layers" in d:
                layered += 1
            else:
                snapshot += 1
        print(f"Total: {len(files)}")
        print(f"  Layered (v2): {layered}")
        print(f"  Snapshot (v1): {snapshot}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
