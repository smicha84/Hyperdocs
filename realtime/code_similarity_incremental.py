#!/usr/bin/env python3
"""
Incremental Code Similarity — Layer 1 Real-Time Mode
=====================================================

Wraps the full-scan code_similarity.py engine with:
  - Fingerprint cache (avoids re-parsing unchanged files)
  - Single-file re-scan (on Edit/Write, only re-fingerprint the changed file)
  - Alert generation (flags new matches when a file changes)

The full scan engine compares ALL files. This module makes it incremental:
when one file changes, it re-fingerprints ONLY that file and compares it
against the cached fingerprints of everything else.

Usage:
    # As a library (called from realtime_dispatcher.py):
    from realtime.code_similarity_incremental import IncrementalSimilarity
    engine = IncrementalSimilarity("/path/to/project")
    alerts = engine.scan_file("/path/to/changed_file.py")

    # CLI for testing:
    python3 code_similarity_incremental.py --file /path/to/changed.py
    python3 code_similarity_incremental.py --rebuild-cache
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add parent for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from phase_2_synthesis.code_similarity import (
    FileFingerprint,
    compare_pair,
    classify_pattern,
)


# ── Cache Management ──────────────────────────────────────────────────────

class FingerprintCache:
    """Persistent cache of file fingerprints with mtime tracking."""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.entries: dict = {}  # {filename: {mtime, fingerprint_data}}
        self._load()

    def _load(self):
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    data = json.load(f)
                self.entries = data.get("files", {})
            except (json.JSONDecodeError, IOError):
                self.entries = {}

    def save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump({
                "updated_at": datetime.now().isoformat(),
                "file_count": len(self.entries),
                "files": self.entries,
            }, f, indent=2)

    def is_stale(self, file_path: Path) -> bool:
        """Check if cached fingerprint is older than file's mtime."""
        name = file_path.name
        if name not in self.entries:
            return True
        try:
            current_mtime = file_path.stat().st_mtime
            cached_mtime = self.entries[name].get("mtime", 0)
            return current_mtime > cached_mtime
        except (OSError, IOError):
            return True

    def get_fingerprint(self, filename: str) -> dict:
        return self.entries.get(filename, {}).get("fingerprint", {})

    def update(self, file_path: Path, fp: FileFingerprint):
        try:
            mtime = file_path.stat().st_mtime
        except (OSError, IOError):
            mtime = time.time()

        self.entries[file_path.name] = {
            "mtime": mtime,
            "path": str(file_path),
            "fingerprint": fp.to_dict(),
        }


# ── Incremental Engine ────────────────────────────────────────────────────

class IncrementalSimilarity:
    """
    Incremental code similarity scanning.

    On each file change:
    1. Re-fingerprint the changed file
    2. Compare against all cached fingerprints
    3. Return alerts for new/changed matches
    """

    def __init__(self, project_dir: str = None, cache_dir: str = None):
        if project_dir:
            self.project_dir = Path(project_dir)
        else:
            self.project_dir = Path.cwd()

        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / "PERMANENT_HYPERDOCS" / "indexes"

        self.cache = FingerprintCache(self.cache_dir / "fingerprint_cache.json")
        self._fingerprint_objects: dict = {}  # In-memory FileFingerprint objects

    def _get_or_create_fingerprint(self, file_path: Path) -> FileFingerprint:
        """Get a FileFingerprint object, using cache if fresh."""
        name = file_path.name
        if name in self._fingerprint_objects and not self.cache.is_stale(file_path):
            return self._fingerprint_objects[name]

        fp = FileFingerprint(file_path)
        self._fingerprint_objects[name] = fp
        self.cache.update(file_path, fp)
        return fp

    def scan_file(self, changed_file: str, threshold: float = 0.1) -> list:
        """
        Scan a single changed file against all cached fingerprints.

        Returns list of alerts: [{file_a, file_b, patterns, signals}]
        """
        changed_path = Path(changed_file)
        if not changed_path.exists() or not changed_path.suffix == ".py":
            return []

        # Re-fingerprint the changed file
        changed_fp = FileFingerprint(changed_path)
        if changed_fp.parse_error:
            return []

        # Update cache
        self.cache.update(changed_path, changed_fp)

        # Compare against all other cached fingerprints
        alerts = []
        for name, entry in self.cache.entries.items():
            if name == changed_path.name:
                continue

            # Reconstruct a FileFingerprint-like object from cache
            cached_data = entry.get("fingerprint", {})
            cached_path = Path(entry.get("path", ""))

            if cached_path.exists():
                other_fp = self._get_or_create_fingerprint(cached_path)
            else:
                continue  # File no longer exists

            signals = compare_pair(changed_fp, other_fp, text_threshold=threshold)

            if signals["signal_score"] > threshold or signals["text_similarity"] > 0.05:
                patterns = classify_pattern(signals)
                if patterns or signals["signal_score"] > 0.5:
                    alerts.append({
                        "file_a": changed_path.name,
                        "file_b": name,
                        "patterns": patterns,
                        "signals": signals,
                        "detected_at": datetime.now().isoformat(),
                    })

        # Save updated cache
        self.cache.save()

        return sorted(alerts, key=lambda a: -a["signals"]["signal_score"])

    def rebuild_cache(self, source_dir: str = None, extensions: list = None):
        """Full cache rebuild — fingerprint all files in directory."""
        if extensions is None:
            extensions = [".py"]

        scan_dir = Path(source_dir) if source_dir else self.project_dir
        if not scan_dir.exists():
            print(f"ERROR: Directory not found: {scan_dir}")
            return

        files = []
        for ext in extensions:
            files.extend(sorted(scan_dir.glob(f"*{ext}")))

        print(f"Rebuilding cache: {len(files)} files in {scan_dir}")
        for i, path in enumerate(files):
            fp = FileFingerprint(path)
            self.cache.update(path, fp)
            self._fingerprint_objects[path.name] = fp
            if (i + 1) % 50 == 0:
                print(f"  Cached {i + 1}/{len(files)}...")

        self.cache.save()
        print(f"Cache rebuilt: {len(self.cache.entries)} files at {self.cache.cache_path}")

    def get_stats(self) -> dict:
        """Return cache statistics."""
        return {
            "cache_path": str(self.cache.cache_path),
            "cached_files": len(self.cache.entries),
            "cache_exists": self.cache.cache_path.exists(),
            "cache_size_kb": round(self.cache.cache_path.stat().st_size / 1024, 1) if self.cache.cache_path.exists() else 0,
        }


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Incremental Code Similarity")
    parser.add_argument("--file", type=str, help="Scan a single changed file")
    parser.add_argument("--rebuild-cache", action="store_true", help="Rebuild full cache")
    parser.add_argument("--source-dir", type=str, help="Source directory for cache rebuild")
    parser.add_argument("--stats", action="store_true", help="Show cache statistics")
    parser.add_argument("--threshold", type=float, default=0.1, help="Signal threshold")
    args = parser.parse_args()

    engine = IncrementalSimilarity()

    if args.stats:
        stats = engine.get_stats()
        print(json.dumps(stats, indent=2))
        return

    if args.rebuild_cache:
        engine.rebuild_cache(source_dir=args.source_dir)
        return

    if args.file:
        print(f"Scanning: {args.file}")
        start = time.time()
        alerts = engine.scan_file(args.file, threshold=args.threshold)
        elapsed = time.time() - start

        print(f"Completed in {elapsed:.2f}s")
        print(f"Alerts: {len(alerts)}")
        for a in alerts[:10]:
            patterns = ", ".join(a["patterns"]) if a["patterns"] else "unclassified"
            score = a["signals"]["signal_score"]
            print(f"  {score:5.2f} | {a['file_b']} | {patterns}")

        # Write alerts to JSONL
        alerts_path = engine.cache_dir / "similarity_alerts.jsonl"
        with open(alerts_path, "a") as f:
            for a in alerts:
                f.write(json.dumps(a) + "\n")
        if alerts:
            print(f"Alerts appended to: {alerts_path}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
