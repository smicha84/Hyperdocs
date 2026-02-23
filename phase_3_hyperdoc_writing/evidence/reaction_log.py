"""
Reaction Log renderer.

Renders raw user emotional events with caps_ratio, content preview,
and reaction type from thread_extractions.json:reactions.

Directive: @evidence:reaction_log(range=[start,end])
"""
from .base import EvidenceRenderer


class ReactionLogRenderer(EvidenceRenderer):

    def render(self, params: dict) -> str:
        msg_range = params.get("range", [])

        # Get reaction entries from thread_extractions
        threads = self.thread_extractions.get("threads", {})
        reactions = threads.get("reactions", {})
        entries = reactions.get("entries", []) if isinstance(reactions, dict) else []

        if not entries:
            return "[evidence unavailable: no reaction entries in thread_extractions]"

        # Filter by range if specified
        if msg_range and len(msg_range) >= 2:
            start, end = int(msg_range[0]), int(msg_range[1])
            filtered = [
                e for e in entries
                if isinstance(e, dict) and start <= e.get("msg_index", -1) <= end
            ]
        else:
            filtered = [e for e in entries if isinstance(e, dict)]

        if not filtered:
            range_str = f"[{msg_range[0]},{msg_range[1]}]" if msg_range else "all"
            return f"[evidence unavailable: no reactions in range {range_str}]"

        filtered.sort(key=lambda x: x.get("msg_index", 0))

        lines = []
        range_desc = f"[{msg_range[0]}\u2192{msg_range[1]}]" if msg_range and len(msg_range) >= 2 else "all"
        header = f"\u250c\u2500 REACTION LOG {range_desc} ({len(filtered)} events) \u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        lines.append(header)

        for entry in filtered:
            idx = entry.get("msg_index", "?")
            reaction_type = entry.get("type", "unknown")
            caps_ratio = entry.get("caps_ratio", 0)
            summary = entry.get("summary", "")
            context = entry.get("context", "")
            timestamp = entry.get("timestamp", "")

            # Get the actual message content from enriched_session
            msg = self.get_message(idx)
            content_preview = ""
            if msg:
                content = msg.get("content", msg.get("content_preview", ""))
                if isinstance(content, str):
                    # Show first meaningful line, up to 80 chars
                    for line in content.split("\n"):
                        line = line.strip()
                        if line:
                            content_preview = line[:80]
                            break

            ts_str = self.format_timestamp(timestamp) if timestamp else ""

            # Build the entry
            caps_bar = self._caps_bar(caps_ratio)
            type_display = reaction_type.upper().replace("_", " ")

            line = f"\u2502 [{idx:>4}] {type_display}"
            if ts_str:
                line += f"  {ts_str}"
            lines.append(line)
            lines.append(f"\u2502   caps: {caps_ratio:.0%} {caps_bar}")
            if summary:
                lines.append(f"\u2502   \"{summary}\"")
            if content_preview:
                lines.append(f"\u2502   content: \"{content_preview}\"")
            if context:
                lines.append(f"\u2502   context: {context}")
            lines.append("\u2502")

        lines.append("\u2514" + "\u2500" * 48)
        return "\n".join(lines)

    def _caps_bar(self, ratio):
        """Render a visual bar for caps ratio (0.0 to 1.0)."""
        filled = int(ratio * 10)
        return "\u2588" * filled + "\u2591" * (10 - filled)
