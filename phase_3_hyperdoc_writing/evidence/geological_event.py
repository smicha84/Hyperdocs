"""
Geological Event renderer.

Renders a single-message turning point from geological_notes.json:micro
combined with full message metadata from enriched_session.json.

Directive: @evidence:geological_event(msg=523)
"""
from .base import EvidenceRenderer


class GeologicalEventRenderer(EvidenceRenderer):

    def render(self, params: dict) -> str:
        msg_index = params.get("msg")
        if msg_index is None:
            return "[evidence unavailable: geological_event requires msg=INDEX]"

        msg_index = int(msg_index)

        # Find geological observation covering this message
        observation = self._find_observation(msg_index)

        # Get the actual message
        msg = self.get_message(msg_index)

        if not observation and not msg:
            return f"[evidence unavailable: no data for message {msg_index}]"

        lines = []
        header = f"\u250c\u2500 GEOLOGICAL EVENT [msg {msg_index}] \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        lines.append(header)

        # Message metadata
        if msg:
            role = msg.get("role", "?")
            ts = self.format_timestamp(msg.get("timestamp", ""))
            tier = msg.get("filter_tier", "?")
            signals = msg.get("filter_signals", [])
            content = msg.get("content", msg.get("content_preview", ""))

            lines.append(f"\u2502 {ts} [{role}] tier:{tier}")
            if signals:
                sig_str = " ".join(signals[:5])
                lines.append(f"\u2502 signals: {sig_str}")

            # Show content preview (first 3 non-empty lines)
            if isinstance(content, str):
                content_lines = [
                    l.strip() for l in content.split("\n")
                    if l.strip() and not l.strip().startswith("```")
                ][:3]
                for cl in content_lines:
                    preview = cl[:70] + "..." if len(cl) > 70 else cl
                    lines.append(f"\u2502   \"{preview}\"")

            # Behavior flags
            bflags = msg.get("behavior_flags", {})
            if isinstance(bflags, dict):
                active_flags = [k for k, v in bflags.items() if v and k != "damage_score"]
                damage = bflags.get("damage_score", 0)
                if active_flags:
                    lines.append(f"\u2502 behavior: {', '.join(active_flags)} (damage:{damage})")

            lines.append("\u2502")

        # Geological observation
        if observation:
            obs_text = observation.get("observation", "")
            evidence = observation.get("evidence", "")
            msg_range = observation.get("message_range", [])
            density = observation.get("density", "")
            obs_type = observation.get("type", "")
            significance = observation.get("significance", "")

            lines.append(f"\u2502 GEOLOGICAL OBSERVATION:")
            if density:
                lines.append(f"\u2502   density: {density}  type: {obs_type}")
            if significance:
                lines.append(f"\u2502   significance: {significance}")
            if obs_text:
                # Wrap observation text at ~70 chars
                for chunk in self._wrap(obs_text, 68):
                    lines.append(f"\u2502   {chunk}")
            if evidence:
                lines.append(f"\u2502")
                lines.append(f"\u2502   evidence: {evidence[:200]}")
        else:
            lines.append(f"\u2502 [no geological observation covers msg {msg_index}]")

        # Semantic primitives for this message
        tagged = self.get_tagged_message(msg_index)
        if tagged:
            emotion = tagged.get("emotional_tenor", "")
            confidence = tagged.get("confidence_signal", "")
            action = tagged.get("action_vector", "")
            decision = tagged.get("decision_trace", "")
            lines.append(f"\u2502")
            lines.append(f"\u2502 PRIMITIVES: emotion:{emotion} confidence:{confidence} action:{action}")
            if decision:
                lines.append(f"\u2502   decision: {decision[:100]}")

        lines.append("\u2514" + "\u2500" * 48)
        return "\n".join(lines)

    def _find_observation(self, msg_index):
        """Find a geological observation covering this message index."""
        # Check micro observations first (most specific)
        for obs in self.geological_notes.get("micro", []):
            if not isinstance(obs, dict):
                continue
            # Check by index field
            obs_idx = obs.get("index", obs.get("msg_index"))
            if obs_idx == msg_index:
                return obs
            # Check by message_range
            msg_range = obs.get("message_range", [])
            if isinstance(msg_range, list) and len(msg_range) == 2:
                if msg_range[0] <= msg_index <= msg_range[1]:
                    return obs

        # Check meso
        for obs in self.geological_notes.get("meso", []):
            if not isinstance(obs, dict):
                continue
            msg_range = obs.get("message_range", [])
            if isinstance(msg_range, list) and len(msg_range) == 2:
                if msg_range[0] <= msg_index <= msg_range[1]:
                    return obs

        return None

    def _wrap(self, text, width):
        """Simple word wrap."""
        words = text.split()
        lines = []
        current = []
        length = 0
        for word in words:
            if length + len(word) + 1 > width and current:
                lines.append(" ".join(current))
                current = [word]
                length = len(word)
            else:
                current.append(word)
                length += len(word) + 1
        if current:
            lines.append(" ".join(current))
        return lines
