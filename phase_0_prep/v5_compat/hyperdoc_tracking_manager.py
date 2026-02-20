#!/usr/bin/env python3
"""
Hyperdoc Tracking Database Manager
==================================

Manages a persistent database that tracks which chat history files have been
processed through the Hyperdocs pipeline. The database lives on the Desktop
next to the PERMANENT_ARCHIVE.

Features:
- Track processed files with metadata (markers generated, processing time, etc.)
- Track pending files
- Resume interrupted processing
- Generate progress reports

Database Location: ~/Desktop/hyperdoc_tracking_db.json

Usage:
    from hyperdoc_tracking_manager import HyperdocTracker

    tracker = HyperdocTracker()
    tracker.scan_archive()  # Discover all files
    pending = tracker.get_pending_files()
    tracker.mark_processed("history_20260126.jsonl", markers_count=150)
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

# Database location - Desktop, next to PERMANENT_ARCHIVE
DB_PATH = Path.home() / "Desktop" / "hyperdoc_tracking_db.json"
ARCHIVE_PATH = Path.home() / "Desktop" / "all chat history" / "PERMANENT_ARCHIVE"


@dataclass
class ProcessedFileRecord:
    """Record for a single processed file."""
    filename: str
    file_path: str
    file_size_bytes: int
    processed_at: str
    processing_time_seconds: float
    messages_count: int
    extractions_count: int
    markers_generated: int
    struggles_identified: int
    passes_completed: int  # 1-6 from iterative analyzer
    output_dir: str
    status: str = "completed"  # completed, failed, partial
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProcessedFileRecord":
        return cls(**data)


class HyperdocTracker:
    """
    Manages the hyperdoc tracking database.

    The database tracks:
    - Which files have been processed
    - Processing statistics for each file
    - Which files are still pending
    - Overall progress
    """

    def __init__(self, db_path: Path = DB_PATH, archive_path: Path = ARCHIVE_PATH):
        self.db_path = Path(db_path)
        self.archive_path = Path(archive_path)
        self.data = self._load_or_create()

    def _load_or_create(self) -> Dict[str, Any]:
        """Load existing database or create new one."""
        if self.db_path.exists():
            try:
                with open(self.db_path) as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print(f"  [warn] Corrupt database, creating new one")

        # Create new database
        return {
            "database_version": "1.0",
            "created_at": datetime.now().isoformat(),
            "description": "Tracks which chat history files have been processed through the Hyperdocs pipeline",
            "archive_location": str(self.archive_path),
            "stats": {
                "total_files_in_archive": 0,
                "files_processed": 0,
                "files_pending": 0,
                "last_updated": None
            },
            "processed_files": {},
            "pending_files": [],
            "processing_history": []
        }

    def save(self):
        """Save database to disk."""
        self.data["stats"]["last_updated"] = datetime.now().isoformat()
        with open(self.db_path, 'w') as f:
            json.dump(self.data, f, indent=2)

    def scan_archive(self) -> int:
        """
        Scan the PERMANENT_ARCHIVE and update pending files list.

        Returns:
            Number of new files discovered
        """
        if not self.archive_path.exists():
            print(f"  [error] Archive not found: {self.archive_path}")
            return 0

        # Find all JSONL files
        all_files = sorted([
            f.name for f in self.archive_path.glob("*.jsonl")
        ])

        # Determine which are pending (not yet processed)
        processed_set = set(self.data["processed_files"].keys())
        pending = [f for f in all_files if f not in processed_set]

        self.data["pending_files"] = pending
        self.data["stats"]["total_files_in_archive"] = len(all_files)
        self.data["stats"]["files_pending"] = len(pending)
        self.data["stats"]["files_processed"] = len(processed_set)

        self.save()

        return len(pending)

    def get_pending_files(self, limit: Optional[int] = None) -> List[str]:
        """Get list of files that haven't been processed yet."""
        pending = self.data.get("pending_files", [])
        if limit:
            return pending[:limit]
        return pending

    def get_pending_file_paths(self, limit: Optional[int] = None) -> List[Path]:
        """Get full paths to pending files."""
        pending = self.get_pending_files(limit)
        return [self.archive_path / f for f in pending]

    def mark_processing_started(self, filename: str) -> str:
        """
        Mark a file as being processed. Returns a processing_id.
        """
        processing_id = f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.data["processing_history"].append({
            "processing_id": processing_id,
            "filename": filename,
            "started_at": datetime.now().isoformat(),
            "status": "in_progress"
        })

        self.save()
        return processing_id

    def mark_processed(
        self,
        filename: str,
        processing_time_seconds: float = 0,
        messages_count: int = 0,
        extractions_count: int = 0,
        markers_generated: int = 0,
        struggles_identified: int = 0,
        passes_completed: int = 0,
        output_dir: str = "",
        status: str = "completed",
        error_message: Optional[str] = None
    ):
        """
        Mark a file as processed with its statistics.
        """
        file_path = self.archive_path / filename
        file_size = file_path.stat().st_size if file_path.exists() else 0

        record = ProcessedFileRecord(
            filename=filename,
            file_path=str(file_path),
            file_size_bytes=file_size,
            processed_at=datetime.now().isoformat(),
            processing_time_seconds=processing_time_seconds,
            messages_count=messages_count,
            extractions_count=extractions_count,
            markers_generated=markers_generated,
            struggles_identified=struggles_identified,
            passes_completed=passes_completed,
            output_dir=output_dir,
            status=status,
            error_message=error_message
        )

        self.data["processed_files"][filename] = record.to_dict()

        # Remove from pending
        if filename in self.data["pending_files"]:
            self.data["pending_files"].remove(filename)

        # Update stats
        self.data["stats"]["files_processed"] = len(self.data["processed_files"])
        self.data["stats"]["files_pending"] = len(self.data["pending_files"])

        # Update processing history
        for entry in reversed(self.data["processing_history"]):
            if entry["filename"] == filename and entry["status"] == "in_progress":
                entry["status"] = status
                entry["completed_at"] = datetime.now().isoformat()
                entry["markers_generated"] = markers_generated
                break

        self.save()

    def get_progress_report(self) -> str:
        """Generate a progress report."""
        stats = self.data["stats"]
        processed = self.data["processed_files"]

        total_markers = sum(
            rec.get("markers_generated", 0)
            for rec in processed.values()
        )
        total_struggles = sum(
            rec.get("struggles_identified", 0)
            for rec in processed.values()
        )
        total_messages = sum(
            rec.get("messages_count", 0)
            for rec in processed.values()
        )

        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║              HYPERDOC PROCESSING PROGRESS REPORT                  ║
╠══════════════════════════════════════════════════════════════════╣
║  Archive: {str(self.archive_path)[:50]:<50} ║
║  Database: {str(self.db_path)[:49]:<49} ║
╠══════════════════════════════════════════════════════════════════╣
║  FILES                                                            ║
║    Total in archive: {stats['total_files_in_archive']:<45} ║
║    Processed:        {stats['files_processed']:<45} ║
║    Pending:          {stats['files_pending']:<45} ║
║    Progress:         {f"{(stats['files_processed'] / max(stats['total_files_in_archive'], 1) * 100):.1f}%":<45} ║
╠══════════════════════════════════════════════════════════════════╣
║  CUMULATIVE STATS                                                 ║
║    Messages processed:  {total_messages:<42} ║
║    Markers generated:   {total_markers:<42} ║
║    Struggles identified:{total_struggles:<42} ║
╠══════════════════════════════════════════════════════════════════╣
║  Last updated: {(stats.get('last_updated') or 'Never')[:50]:<50} ║
╚══════════════════════════════════════════════════════════════════╝
"""
        return report

    def get_file_status(self, filename: str) -> Optional[Dict[str, Any]]:
        """Get processing status for a specific file."""
        return self.data["processed_files"].get(filename)

    def reset_file(self, filename: str):
        """Reset a file to pending status (for reprocessing)."""
        if filename in self.data["processed_files"]:
            del self.data["processed_files"][filename]

        if filename not in self.data["pending_files"]:
            # Re-add to pending in sorted position
            self.data["pending_files"].append(filename)
            self.data["pending_files"].sort()

        self.data["stats"]["files_processed"] = len(self.data["processed_files"])
        self.data["stats"]["files_pending"] = len(self.data["pending_files"])
        self.save()


def main():
    """CLI interface for the tracker."""
    import argparse

    parser = argparse.ArgumentParser(description="Hyperdoc Tracking Database Manager")
    parser.add_argument("command", choices=["scan", "status", "pending", "reset"],
                        help="Command to run")
    parser.add_argument("--file", type=str, help="Specific file (for reset)")
    parser.add_argument("--limit", type=int, help="Limit for pending files")

    args = parser.parse_args()

    tracker = HyperdocTracker()

    if args.command == "scan":
        new_files = tracker.scan_archive()
        print(f"Scanned archive. Found {new_files} new/pending files.")
        print(tracker.get_progress_report())

    elif args.command == "status":
        print(tracker.get_progress_report())

    elif args.command == "pending":
        pending = tracker.get_pending_files(args.limit)
        print(f"Pending files ({len(pending)}):")
        for f in pending:
            print(f"  - {f}")

    elif args.command == "reset":
        if args.file:
            tracker.reset_file(args.file)
            print(f"Reset {args.file} to pending")
        else:
            print("Error: --file required for reset command")


if __name__ == "__main__":
    main()
