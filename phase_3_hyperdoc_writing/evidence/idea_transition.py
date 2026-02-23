"""
Idea Transition renderer.

Renders idea graph state chains showing how an idea evolved through
nodes with maturity/confidence changes and edge types.

Directive: @evidence:idea_transition(chain=[N01,N02,N03])
  or:      @evidence:idea_transition(node=N16)
"""
from .base import EvidenceRenderer


class IdeaTransitionRenderer(EvidenceRenderer):

    def render(self, params: dict) -> str:
        chain = params.get("chain", [])
        node_id = params.get("node", "")

        nodes = {
            n.get("id", ""): n
            for n in self.idea_graph.get("nodes", [])
            if isinstance(n, dict)
        }
        edges = self.idea_graph.get("edges", [])

        # If single node specified, build chain from connected edges
        if node_id and not chain:
            chain = self._build_chain_from_node(node_id, nodes, edges)

        if not chain:
            return "[evidence unavailable: idea_transition requires chain=[...] or node=N##]"

        # Render the chain
        lines = []
        chain_label = "\u2192".join(chain)
        header = f"\u250c\u2500 IDEA TRANSITION [{chain_label}] \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        lines.append(header)

        for i, nid in enumerate(chain):
            node = nodes.get(nid, {})
            label = node.get("label", node.get("name", nid))
            confidence = node.get("confidence", "?")
            maturity = node.get("maturity", node.get("state", "?"))
            msg_idx = node.get("message_index", node.get("first_appearance", "?"))
            source = node.get("source", "")

            lines.append(f"\u2502 [{nid}] {label}")
            lines.append(f"\u2502   maturity:{maturity}  confidence:{confidence}  msg:{msg_idx}")
            if source:
                lines.append(f"\u2502   source: {source}")

            # Show edge to next node
            if i < len(chain) - 1:
                next_nid = chain[i + 1]
                edge = self._find_edge(nid, next_nid, edges)
                if edge:
                    etype = edge.get("type", edge.get("transition", "?"))
                    elabel = edge.get("label", "")
                    evidence = edge.get("evidence", "")
                    lines.append(f"\u2502   \u2502")
                    lines.append(f"\u2502   \u2514\u2500\u2500[{etype}]\u2500\u2500\u25b6")
                    if elabel:
                        lines.append(f"\u2502      {elabel}")
                    if evidence:
                        lines.append(f"\u2502      evidence: {evidence}")
                else:
                    lines.append(f"\u2502   \u2502")
                    lines.append(f"\u2502   \u2514\u2500\u2500[?]\u2500\u2500\u25b6")
            lines.append("\u2502")

        lines.append("\u2514" + "\u2500" * 48)
        return "\n".join(lines)

    def _build_chain_from_node(self, node_id, nodes, edges):
        """Build a chain by following edges backward then forward from node_id."""
        # Walk backward to find the root
        chain_back = [node_id]
        current = node_id
        visited = {node_id}
        for _ in range(20):  # safety limit
            found = False
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                tgt = edge.get("to", edge.get("to_node", ""))
                src = edge.get("from", edge.get("from_node", ""))
                if tgt == current and src not in visited and src in nodes:
                    chain_back.insert(0, src)
                    visited.add(src)
                    current = src
                    found = True
                    break
            if not found:
                break

        # Walk forward from the original node
        current = node_id
        for _ in range(20):
            found = False
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                src = edge.get("from", edge.get("from_node", ""))
                tgt = edge.get("to", edge.get("to_node", ""))
                if src == current and tgt not in visited and tgt in nodes:
                    chain_back.append(tgt)
                    visited.add(tgt)
                    current = tgt
                    found = True
                    break
            if not found:
                break

        return chain_back

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
