"""
Schema normalizer for idea_graph.json files.

Handles 3+ schema variants discovered across 293 sessions:

Variant A (e.g. 0012ebed): flat id, message_index, type on edges
Variant B (e.g. 0500070e): node_id, edge_id, transition, message_indices[], state, confidence as "high"/"medium"
Variant C (e.g. 5cb156c4): id, first_seen_msg/last_seen_msg, state_history[], transition on edges

All variants normalize to a canonical format. Extra fields preserved in each node/edge dict.
"""
from __future__ import annotations

# ── Confidence normalization ────────────────────────────────────────

# Numeric thresholds → string labels
_CONFIDENCE_NUMERIC = [
    (0.9, "proven"),
    (0.7, "stable"),
    (0.5, "working"),
    (0.3, "tentative"),
    (0.0, "experimental"),
]

# Alias strings → canonical
_CONFIDENCE_ALIASES = {
    "high": "stable",
    "medium": "working",
    "low": "tentative",
    "very_high": "proven",
    "very_low": "experimental",
    "none": "unknown",
}

# Canonical set
_CONFIDENCE_CANONICAL = {"proven", "stable", "working", "tentative", "experimental", "fragile", "unknown"}


def _normalize_confidence(val) -> str:
    """Normalize a confidence value to one of the canonical strings."""
    if val is None:
        return "unknown"
    if isinstance(val, (int, float)):
        for threshold, label in _CONFIDENCE_NUMERIC:
            if val >= threshold:
                return label
        return "experimental"
    s = str(val).strip().lower()
    if s in _CONFIDENCE_CANONICAL:
        return s
    return _CONFIDENCE_ALIASES.get(s, "unknown")


# ── Maturity grouping ───────────────────────────────────────────────

MATURITY_GROUPS = {
    "Early": {
        "exploration", "seed", "hypothesis", "conceptual", "discovered",
        "early", "initiated", "glimpsed", "noticed", "first_signal",
        "emergent", "proposed",
    },
    "Active": {
        "implementing", "building", "working", "implemented", "decided",
        "assigned", "accepted", "partial", "near_complete", "formulated",
        "confirmed", "crystallized", "documented", "applied", "executed",
        "researched", "debugged", "proven", "mature",
    },
    "Terminal": {
        "completed", "delivered", "abandoned", "reverted", "superseded",
        "complete", "reported", "central_finding",
    },
}


def maturity_group(maturity: str) -> str:
    """Return the group name for a maturity value."""
    m = (maturity or "").strip().lower()
    for group, values in MATURITY_GROUPS.items():
        if m in values:
            return group
    return "Unknown"


# ── Node normalization ──────────────────────────────────────────────

_NODE_CANONICAL_KEYS = {
    "id", "label", "description", "message_index", "confidence",
    "maturity", "source", "emotional_context",
}


def _resolve(d: dict, *keys, default=None):
    """Return the first key found in d, or default."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def normalize_node(raw: dict) -> dict:
    """Normalize a single node dict to canonical format."""
    node = {}

    # id
    node["id"] = _resolve(raw, "id", "node_id", default="?")

    # label
    node["label"] = _resolve(raw, "label", "name", "idea", default="(unlabeled)")

    # description
    node["description"] = _resolve(raw, "description", default="")

    # message_index — pick earliest appearance
    mi = _resolve(raw, "message_index")
    if mi is None:
        mi = _resolve(raw, "first_seen_msg", "first_appearance", "first_seen")
    if mi is None:
        indices = _resolve(raw, "message_indices")
        if isinstance(indices, list) and indices:
            mi = min(indices)
    node["message_index"] = mi if mi is not None else 0

    # confidence
    conf = _resolve(raw, "confidence", "confidence_signal")
    # If there's a state_history, use latest confidence from it
    sh = raw.get("state_history")
    if isinstance(sh, list) and sh:
        last = sh[-1]
        if "confidence" in last:
            conf = last["confidence"]
    node["confidence"] = _normalize_confidence(conf)

    # maturity
    mat = _resolve(raw, "maturity", "state")
    if isinstance(sh, list) and sh:
        last = sh[-1]
        if "state" in last:
            mat = last["state"]
    node["maturity"] = mat or "unknown"
    node["maturity_group"] = maturity_group(node["maturity"])

    # source
    node["source"] = _resolve(raw, "source", "source_thread", "source_segment", default="")

    # emotional_context
    node["emotional_context"] = _resolve(raw, "emotional_context", "emotional_tenor", "emotion", default="")

    # Preserve all extra fields
    extras = {}
    for k, v in raw.items():
        if k not in _NODE_CANONICAL_KEYS and k not in (
            "node_id", "name", "idea", "first_seen_msg", "first_appearance",
            "first_seen", "message_indices", "confidence_signal", "state",
            "source_thread", "source_segment", "emotional_tenor", "emotion",
        ):
            extras[k] = v
    if extras:
        node["_extra"] = extras

    return node


# ── Edge normalization ──────────────────────────────────────────────

_EDGE_CANONICAL_KEYS = {"from", "to", "type", "label", "evidence"}


def normalize_edge(raw: dict) -> dict:
    """Normalize a single edge dict to canonical format."""
    edge = {}

    edge["from"] = _resolve(raw, "from", "from_id", "from_node", default="?")
    edge["to"] = _resolve(raw, "to", "to_id", "to_node", default="?")
    edge["type"] = _resolve(raw, "type", "transition", "transition_type", default="unknown")
    edge["label"] = _resolve(raw, "label", "description", "reason", default="")
    edge["evidence"] = _resolve(raw, "evidence", default="")

    # Preserve extras
    extras = {}
    for k, v in raw.items():
        if k not in _EDGE_CANONICAL_KEYS and k not in (
            "from_id", "from_node", "to_id", "to_node",
            "transition", "transition_type", "description", "reason",
        ):
            extras[k] = v
    if extras:
        edge["_extra"] = extras

    return edge


# ── Subgraph normalization ──────────────────────────────────────────

def normalize_subgraph(raw: dict) -> dict:
    """Normalize a subgraph dict."""
    sg = {}
    sg["id"] = _resolve(raw, "id", default="?")
    sg["name"] = _resolve(raw, "name", "label", default="(unnamed)")
    sg["description"] = _resolve(raw, "description", "summary", default="")
    sg["node_ids"] = raw.get("node_ids", [])
    sg["edge_ids"] = raw.get("edge_ids", [])
    sg["msg_range"] = raw.get("msg_range")
    sg["phase_label"] = raw.get("phase_label", "")
    return sg


# ── Full graph normalization ────────────────────────────────────────

def normalize_graph(data: dict) -> dict:
    """
    Normalize a full idea_graph.json dict to canonical format.

    Returns:
        {
            "session_id": str,
            "nodes": [normalized_node, ...],
            "edges": [normalized_edge, ...],
            "subgraphs": [normalized_subgraph, ...],
            "metadata": dict,
        }
    """
    session_id = _resolve(data, "session_id", default="unknown")

    # Nodes — may be top-level or nested in "graph"
    raw_nodes = data.get("nodes", [])
    if not raw_nodes and isinstance(data.get("graph"), dict):
        raw_nodes = data["graph"].get("nodes", [])

    # Edges — same
    raw_edges = data.get("edges", [])
    if not raw_edges and isinstance(data.get("graph"), dict):
        raw_edges = data["graph"].get("edges", [])

    # Subgraphs
    raw_subgraphs = data.get("subgraphs", [])

    nodes = [normalize_node(n) for n in raw_nodes if isinstance(n, dict)]
    edges = [normalize_edge(e) for e in raw_edges if isinstance(e, dict)]
    subgraphs = [normalize_subgraph(s) for s in raw_subgraphs if isinstance(s, dict)]

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "session_id": session_id,
        "nodes": nodes,
        "edges": edges,
        "subgraphs": subgraphs,
        "metadata": metadata,
    }
