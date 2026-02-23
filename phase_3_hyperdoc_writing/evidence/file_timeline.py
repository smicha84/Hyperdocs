"""
File Timeline renderer.

Renders per-file chronological edit/mention history from file_evidence JSON
or by scanning thread_extractions and enriched_session for file mentions.

Directive: @evidence:file_timeline(file="config.py")
"""
import json
from pathlib import Path

from .base import EvidenceRenderer, load_json


def _safe_filename(filepath):
    """Convert a filepath to a safe filename (same pattern as collect_file_evidence.py)."""
    return filepath.replace("/", "_").replace("\\", "_").replace(".", "_").replace(" ", "_")


class FileTimelineRenderer(EvidenceRenderer):

    def render(self, params: dict) -> str:
        filename = params.get("file", "")
        if not filename:
            return "[evidence unavailable: file_timeline requires file=\"filename.py\"]"

        # Try to load pre-computed file evidence first
        evidence = self._load_file_evidence(filename)
        if evidence:
            timeline = evidence.get("chronological_timeline", {})
            events = timeline.get("events", [])
            if events:
                return self._render_from_events(filename, events)

        # Fallback: scan thread_extractions for file mentions
        events = self._scan_threads_for_file(filename)
        if events:
            return self._render_from_events(filename, events)

        return f"[evidence unavailable: no timeline data for \"{filename}\"]"

    def _load_file_evidence(self, filename):
        """Try to load file_evidence/{safe_name}_evidence.json."""
        safe = _safe_filename(filename)
        evidence_name = f"{safe}_evidence.json"

        # Check file_evidence subdirectory in search dirs
        for d in self._search_dirs:
            evidence_dir = d / "file_evidence"
            path = evidence_dir / evidence_name
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
        return None

    def _scan_threads_for_file(self, filename):
        """Scan thread_extractions for mentions of this file."""
        events = []
        threads = self.thread_extractions.get("threads", {})
        stem = Path(filename).stem.lower()

        for thread_key, thread_val in threads.items():
            if not isinstance(thread_val, dict):
                continue
            for entry in thread_val.get("entries", []):
                if not isinstance(entry, dict):
                    continue
                content = entry.get("content", "")
                if not isinstance(content, str):
                    continue
                if filename.lower() in content.lower() or stem in content.lower():
                    events.append({
                        "msg_index": entry.get("msg_index", -1),
                        "thread": thread_key,
                        "content": content[:200],
                        "significance": entry.get("significance", ""),
                    })

        events.sort(key=lambda x: x.get("msg_index", 0))
        return events

    def _render_from_events(self, filename, events):
        """Render timeline from a list of event dicts."""
        lines = []
        header = f"\u250c\u2500 FILE TIMELINE: {filename} ({len(events)} events) \u2500\u2500\u2500"
        lines.append(header)

        for event in events:
            idx = event.get("msg_index", "?")
            thread = event.get("thread", "?")
            content = event.get("content", "")
            significance = event.get("significance", "")
            marker_type = event.get("marker_type", "")

            # Determine action type from thread/content
            action = self._classify_file_action(thread, content)

            # Get timestamp if available
            msg = self.get_message(idx) if isinstance(idx, int) and idx >= 0 else None
            ts = self.format_timestamp(msg.get("timestamp", "")) if msg else ""

            ts_part = f" {ts}" if ts else ""
            lines.append(f"\u2502 [{idx:>4}]{ts_part} {action} ({thread})")

            # Show content preview
            preview = content[:70] if isinstance(content, str) else ""
            if preview:
                if len(content) > 70:
                    preview += "..."
                lines.append(f"\u2502   \"{preview}\"")

            if significance:
                lines.append(f"\u2502   significance: {significance}")
            lines.append("\u2502")

        lines.append("\u2514" + "\u2500" * 48)
        return "\n".join(lines)

    def _classify_file_action(self, thread, content):
        """Classify the file action from thread type and content."""
        content_lower = content.lower() if isinstance(content, str) else ""
        if any(kw in content_lower for kw in ("created", "new file", "wrote new")):
            return "CREATE"
        if any(kw in content_lower for kw in ("deleted", "removed", "dropped")):
            return "DELETE"
        if any(kw in content_lower for kw in ("renamed", "moved", "refactored to")):
            return "RENAME"
        if any(kw in content_lower for kw in ("modified", "edited", "updated", "changed", "fixed")):
            return "EDIT"
        if thread == "grounded_marker":
            return "MARKER"
        if thread == "software":
            return "MENTION"
        return "REF"
