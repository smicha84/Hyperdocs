"""
Decision Trace renderer.

Renders a chain of decisions leading to an outcome, with alternatives
rejected, from grounded_markers.json + idea_graph.json.

Directive: @evidence:decision_trace(marker="GM-001")
  or:      @evidence:decision_trace(chain=[N01,N02,N03])
"""
from .base import EvidenceRenderer


class DecisionTraceRenderer(EvidenceRenderer):

    def render(self, params: dict) -> str:
        marker_id = params.get("marker", "")
        chain = params.get("chain", [])

        if marker_id:
            return self._render_from_marker(marker_id)
        elif chain:
            return self._render_from_chain(chain)
        else:
            return "[evidence unavailable: decision_trace requires marker=\"ID\" or chain=[...]]"

    def _render_from_marker(self, marker_id):
        """Render decision trace starting from a grounded marker."""
        markers = self.grounded_markers.get("markers", [])
        target = None
        for m in markers:
            if not isinstance(m, dict):
                continue
            mid = m.get("marker_id", m.get("id", ""))
            if mid == marker_id:
                target = m
                break

        if not target:
            return f"[evidence unavailable: marker \"{marker_id}\" not found]"

        lines = []
        header = f"\u250c\u2500 DECISION TRACE [{marker_id}] \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        lines.append(header)

        # Marker details
        category = target.get("category", "?")
        claim = target.get("claim", target.get("warning", target.get("title", "")))
        evidence = target.get("evidence", "")
        confidence = target.get("confidence", "?")
        guidance = target.get("actionable_guidance", "")

        lines.append(f"\u2502 Category: {category}")
        lines.append(f"\u2502 Confidence: {confidence}")
        lines.append(f"\u2502")

        if claim:
            lines.append(f"\u2502 CLAIM:")
            for chunk in self._wrap(claim, 66):
                lines.append(f"\u2502   {chunk}")
            lines.append(f"\u2502")

        if evidence:
            lines.append(f"\u2502 EVIDENCE:")
            for chunk in self._wrap(evidence, 66):
                lines.append(f"\u2502   {chunk}")
            lines.append(f"\u2502")

        if guidance:
            lines.append(f"\u2502 GUIDANCE:")
            for chunk in self._wrap(guidance, 66):
                lines.append(f"\u2502   {chunk}")
            lines.append(f"\u2502")

        # Find related idea graph nodes (by searching for marker references)
        related_nodes = self._find_related_nodes(marker_id, claim)
        if related_nodes:
            lines.append(f"\u2502 RELATED IDEA GRAPH NODES:")
            for node in related_nodes:
                nid = node.get("id", "?")
                label = node.get("label", "")
                maturity = node.get("maturity", node.get("state", "?"))
                conf = node.get("confidence", "?")
                lines.append(f"\u2502   [{nid}] {label}")
                lines.append(f"\u2502     maturity:{maturity}  confidence:{conf}")

        lines.append("\u2514" + "\u2500" * 48)
        return "\n".join(lines)

    def _render_from_chain(self, chain):
        """Render decision trace from an idea graph node chain."""
        nodes = {
            n.get("id", ""): n
            for n in self.idea_graph.get("nodes", [])
            if isinstance(n, dict)
        }
        edges = self.idea_graph.get("edges", [])

        chain_label = "\u2192".join(chain)
        lines = []
        header = f"\u250c\u2500 DECISION TRACE [{chain_label}] \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        lines.append(header)

        for i, nid in enumerate(chain):
            node = nodes.get(nid, {})
            label = node.get("label", nid)
            maturity = node.get("maturity", node.get("state", "?"))
            confidence = node.get("confidence", "?")
            desc = node.get("description", "")

            lines.append(f"\u2502 [{nid}] {label}")
            lines.append(f"\u2502   maturity:{maturity}  confidence:{confidence}")
            if desc:
                for chunk in self._wrap(desc, 64):
                    lines.append(f"\u2502   {chunk}")

            # Show transition to next
            if i < len(chain) - 1:
                next_nid = chain[i + 1]
                edge = self._find_edge(nid, next_nid, edges)
                if edge:
                    etype = edge.get("type", "?")
                    elabel = edge.get("label", "")
                    lines.append(f"\u2502   \u2514\u2500\u2500[{etype}]\u2500\u2500\u25b6 {next_nid}")
                    if elabel:
                        lines.append(f"\u2502      {elabel}")
                lines.append(f"\u2502")

        lines.append("\u2514" + "\u2500" * 48)
        return "\n".join(lines)

    def _find_related_nodes(self, marker_id, claim_text):
        """Find idea graph nodes related to this marker."""
        related = []
        for node in self.idea_graph.get("nodes", []):
            if not isinstance(node, dict):
                continue
            source = node.get("source", "")
            desc = node.get("description", "")
            label = node.get("label", "")
            # Check if marker is referenced in the node
            if marker_id in str(source) or marker_id in str(desc):
                related.append(node)
            # Also check for keyword overlap with claim text
            elif claim_text and len(claim_text) > 20:
                claim_words = set(claim_text.lower().split()[:8])
                node_words = set(f"{label} {desc}".lower().split())
                if len(claim_words & node_words) >= 3:
                    related.append(node)
        return related[:5]  # Cap at 5

    def _find_edge(self, from_id, to_id, edges):
        """Find edge between two nodes."""
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = edge.get("from", edge.get("from_node", ""))
            tgt = edge.get("to", edge.get("to_node", ""))
            if src == from_id and tgt == to_id:
                return edge
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
