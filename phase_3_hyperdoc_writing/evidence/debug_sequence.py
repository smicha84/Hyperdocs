"""
Debug Sequence renderer.

Renders timestamped error->fix->verify sequences from enriched_session.json
messages combined with semantic_primitives.json emotional/confidence state.

Directive: @evidence:debug_sequence(range=[start,end])
"""
from .base import EvidenceRenderer


class DebugSequenceRenderer(EvidenceRenderer):

    def render(self, params: dict) -> str:
        msg_range = params.get("range", [])
        if not msg_range or len(msg_range) < 2:
            return "[evidence unavailable: debug_sequence requires range=[start,end]]"

        start, end = int(msg_range[0]), int(msg_range[1])
        messages = self.get_messages_in_range(start, end)

        if not messages:
            return f"[evidence unavailable: no messages in range [{start},{end}]]"

        # Compute duration from first to last timestamp
        first_ts = messages[0].get("timestamp", "")
        last_ts = messages[-1].get("timestamp", "")
        duration = self._compute_duration(first_ts, last_ts)

        # Build the log lines
        lines = []
        files_touched = set()
        error_count = 0
        fix_count = 0

        for msg in messages:
            idx = msg.get("index", "?")
            role = msg.get("role", "?")
            tier = msg.get("filter_tier", 0)
            signals = msg.get("filter_signals", [])
            content = msg.get("content", msg.get("content_preview", ""))
            ts = self.format_timestamp(msg.get("timestamp", ""))

            # Skip tier-1 messages (protocol/skip)
            if tier <= 1:
                continue

            # Classify the message action
            action, signal_str = self._classify_action(signals, content)
            if action == "ERROR":
                error_count += 1
            elif action in ("EDIT", "FIX"):
                fix_count += 1

            # Get semantic primitives for this message
            tagged = self.get_tagged_message(idx)
            emotion = tagged.get("emotional_tenor", "")
            confidence = tagged.get("confidence_signal", "")

            # Extract content preview (first meaningful line, truncated)
            preview = self._extract_preview(content)

            # Track files mentioned in edits
            if action == "EDIT":
                for word in content.split():
                    if "." in word and any(word.endswith(ext) for ext in (".py", ".json", ".md", ".html", ".js")):
                        files_touched.add(word.strip("\"'`,;:()"))

            # Build the log line
            line = f"\u2502 {ts} [{role}] {action} {signal_str}"
            lines.append(line)
            if preview:
                lines.append(f"\u2502   \"{preview}\"")
            if emotion or confidence:
                parts = []
                if confidence:
                    parts.append(f"confidence:{confidence}")
                if emotion:
                    parts.append(f"emotion:{emotion}")
                arrow_joined = " \u2192 ".join(parts)
                lines.append(f"\u2502   {arrow_joined}")
            lines.append("\u2502")

        if not lines:
            return f"[evidence unavailable: no tier 2+ messages in range [{start},{end}]]"

        # Build header and footer
        files_str = ", ".join(sorted(files_touched)) if files_touched else "unknown"
        header = f"\u250c\u2500 DEBUG SEQUENCE [{start}\u2192{end}] {duration} \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        footer_stats = f"\u2502 Duration: {duration} | Errors: {error_count} Fixes: {fix_count} | Files: {files_str}"
        footer = "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"

        return "\n".join([header] + lines + [footer_stats, footer])

    def _classify_action(self, signals, content):
        """Classify message action from filter signals and content."""
        signal_str = " ".join(f"filter:{s}" for s in signals[:3]) if signals else ""

        # Check for error/failure signals
        for sig in signals:
            if "failure" in sig:
                return "ERROR", signal_str

        # Check content for edit/fix indicators
        content_lower = content.lower() if isinstance(content, str) else ""
        if any(kw in content_lower for kw in ("fix ", "fixed", "fixing", "patch")):
            return "FIX", signal_str
        if any(kw in content_lower for kw in ("edit ", "modify", "update", "change")):
            return "EDIT", signal_str
        if any(kw in content_lower for kw in ("test", "verify", "confirm", "pass")):
            return "OK", signal_str

        # Check signals for code/architecture
        for sig in signals:
            if "code" in sig:
                return "CODE", signal_str
            if "architecture" in sig:
                return "ARCH", signal_str

        return "MSG", signal_str

    def _extract_preview(self, content):
        """Extract a short preview from message content."""
        if not content or not isinstance(content, str):
            return ""
        # Take first non-empty line, truncate to 60 chars
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("```"):
                if len(line) > 60:
                    return line[:57] + "..."
                return line
        return ""

    def _compute_duration(self, ts1, ts2):
        """Compute human-readable duration between two ISO timestamps."""
        try:
            from datetime import datetime
            # Parse ISO timestamps
            def parse_ts(ts):
                # Handle "2026-01-20T15:27:25.883000+00:00"
                ts = ts.replace("+00:00", "Z").rstrip("Z")
                if "." in ts:
                    return datetime.fromisoformat(ts)
                return datetime.fromisoformat(ts)

            dt1 = parse_ts(ts1)
            dt2 = parse_ts(ts2)
            delta = abs((dt2 - dt1).total_seconds())

            if delta < 60:
                return f"{int(delta)}s"
            minutes = int(delta // 60)
            seconds = int(delta % 60)
            if minutes < 60:
                return f"{minutes}m{seconds:02d}s"
            hours = minutes // 60
            minutes = minutes % 60
            return f"{hours}h{minutes:02d}m"
        except (ValueError, TypeError, IndexError):
            return "??:??"
