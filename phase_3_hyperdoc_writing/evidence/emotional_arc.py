"""
Emotional Arc renderer.

Renders per-message emotional_tenor and confidence_signal changes
across a message range from semantic_primitives.json.

Directive: @evidence:emotional_arc(range=[start,end])
"""
from .base import EvidenceRenderer


class EmotionalArcRenderer(EvidenceRenderer):

    def render(self, params: dict) -> str:
        msg_range = params.get("range", [])
        if not msg_range or len(msg_range) < 2:
            return "[evidence unavailable: emotional_arc requires range=[start,end]]"

        start, end = int(msg_range[0]), int(msg_range[1])

        # Collect tagged messages in range
        tagged_msgs = []
        for tm in self.semantic_primitives.get("tagged_messages", []):
            idx = tm.get("msg_index", tm.get("index", -1))
            if start <= idx <= end:
                tagged_msgs.append(tm)

        if not tagged_msgs:
            return f"[evidence unavailable: no tagged primitives in range [{start},{end}]]"

        tagged_msgs.sort(key=lambda x: x.get("msg_index", x.get("index", 0)))

        # Build the arc visualization
        lines = []
        header = f"\u250c\u2500 EMOTIONAL ARC [{start}\u2192{end}] ({len(tagged_msgs)} tagged messages) \u2500\u2500\u2500"
        lines.append(header)

        prev_emotion = None
        prev_confidence = None
        for tm in tagged_msgs:
            idx = tm.get("msg_index", tm.get("index", "?"))
            role = tm.get("role", "?")
            emotion = tm.get("emotional_tenor", "")
            confidence = tm.get("confidence_signal", "")
            action = tm.get("action_vector", "")
            intent = tm.get("intent_marker", "")
            friction = tm.get("friction_log", "")

            # Highlight transitions
            emotion_marker = ""
            if prev_emotion and emotion != prev_emotion:
                emotion_marker = f" ({prev_emotion}\u2192{emotion})"
            conf_marker = ""
            if prev_confidence and confidence != prev_confidence:
                conf_marker = f" ({prev_confidence}\u2192{confidence})"

            line = f"\u2502 [{idx:>4}] {role:<10} {emotion:<12}{emotion_marker}"
            lines.append(line)
            detail = f"\u2502         confidence:{confidence}{conf_marker}  action:{action}  intent:{intent}"
            lines.append(detail)
            if friction:
                lines.append(f"\u2502         FRICTION: {friction}")
            lines.append("\u2502")

            prev_emotion = emotion
            prev_confidence = confidence

        # Summary stats for the range
        emotion_counts = {}
        confidence_counts = {}
        for tm in tagged_msgs:
            e = tm.get("emotional_tenor", "unknown")
            c = tm.get("confidence_signal", "unknown")
            emotion_counts[e] = emotion_counts.get(e, 0) + 1
            confidence_counts[c] = confidence_counts.get(c, 0) + 1

        emotion_summary = ", ".join(f"{k}:{v}" for k, v in sorted(emotion_counts.items(), key=lambda x: -x[1]))
        conf_summary = ", ".join(f"{k}:{v}" for k, v in sorted(confidence_counts.items(), key=lambda x: -x[1]))
        lines.append(f"\u2502 Emotions: {emotion_summary}")
        lines.append(f"\u2502 Confidence: {conf_summary}")
        lines.append("\u2514" + "\u2500" * 48)

        return "\n".join(lines)
