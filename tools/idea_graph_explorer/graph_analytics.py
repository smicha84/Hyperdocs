"""
Pure Python graph analytics for idea evolution graphs.

No external dependencies. Max graph is ~52 nodes — all algorithms run in microseconds.

Algorithms:
  - PageRank (iterative power method, damping=0.85)
  - Betweenness Centrality (Brandes' algorithm)
  - Degree Centrality (in/out/total)
  - Connected Components (BFS on undirected view)
  - Graph-level metrics (density, component count)
"""
from __future__ import annotations
from collections import deque


def compute_all(nodes: list[dict], edges: list[dict]) -> dict:
    """
    Compute all analytics for a normalized graph.

    Args:
        nodes: list of normalized node dicts (must have "id")
        edges: list of normalized edge dicts (must have "from", "to")

    Returns:
        {
            "pagerank": {node_id: float},
            "betweenness": {node_id: float},
            "degree": {node_id: {"in": int, "out": int, "total": int}},
            "components": [[node_id, ...], ...],
            "density": float,
            "component_count": int,
            "node_count": int,
            "edge_count": int,
        }
    """
    node_ids = [n["id"] for n in nodes]
    edge_list = [(e["from"], e["to"]) for e in edges]

    if not node_ids:
        return {
            "pagerank": {},
            "betweenness": {},
            "degree": {},
            "components": [],
            "density": 0.0,
            "component_count": 0,
            "node_count": 0,
            "edge_count": 0,
        }

    pr = _pagerank(node_ids, edge_list)
    bc = _betweenness(node_ids, edge_list)
    deg = _degree(node_ids, edge_list)
    comps = _components(node_ids, edge_list)

    n = len(node_ids)
    max_edges = n * (n - 1) if n > 1 else 1
    density = len(edge_list) / max_edges if max_edges > 0 else 0.0

    return {
        "pagerank": pr,
        "betweenness": bc,
        "degree": deg,
        "components": comps,
        "density": round(density, 4),
        "component_count": len(comps),
        "node_count": n,
        "edge_count": len(edge_list),
    }


# ── PageRank ────────────────────────────────────────────────────────

def _pagerank(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    damping: float = 0.85,
    iterations: int = 100,
) -> dict[str, float]:
    """Iterative power method PageRank."""
    n = len(node_ids)
    if n == 0:
        return {}

    # Build adjacency: who does each node point to?
    out_neighbors: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for src, dst in edges:
        if src in out_neighbors:
            out_neighbors[src].append(dst)

    # Initialize uniform
    rank = {nid: 1.0 / n for nid in node_ids}

    # Build reverse adjacency for efficient update
    in_neighbors: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for src, dst in edges:
        if dst in in_neighbors:
            in_neighbors[dst].append(src)

    base = (1.0 - damping) / n

    for _ in range(iterations):
        new_rank = {}
        # Collect dangling node mass (nodes with no outgoing edges)
        dangling_sum = sum(rank[nid] for nid in node_ids if not out_neighbors[nid])
        dangling_contrib = damping * dangling_sum / n

        for nid in node_ids:
            incoming_sum = 0.0
            for src in in_neighbors[nid]:
                out_deg = len(out_neighbors[src])
                if out_deg > 0:
                    incoming_sum += rank[src] / out_deg
            new_rank[nid] = base + damping * incoming_sum + dangling_contrib
        rank = new_rank

    return {k: round(v, 6) for k, v in rank.items()}


# ── Betweenness Centrality (Brandes) ───────────────────────────────

def _betweenness(
    node_ids: list[str],
    edges: list[tuple[str, str]],
) -> dict[str, float]:
    """Brandes' algorithm for betweenness centrality on a directed graph."""
    cb = {nid: 0.0 for nid in node_ids}
    node_set = set(node_ids)

    # Build adjacency
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for src, dst in edges:
        if src in adj and dst in node_set:
            adj[src].append(dst)

    for s in node_ids:
        # BFS from s
        stack = []
        pred: dict[str, list[str]] = {nid: [] for nid in node_ids}
        sigma = {nid: 0.0 for nid in node_ids}
        sigma[s] = 1.0
        dist = {nid: -1 for nid in node_ids}
        dist[s] = 0

        queue = deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adj[v]:
                # First visit?
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                # Shortest path via v?
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        # Accumulation
        delta = {nid: 0.0 for nid in node_ids}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]

    # Normalize
    n = len(node_ids)
    norm = (n - 1) * (n - 2) if n > 2 else 1.0
    return {k: round(v / norm, 6) if norm > 0 else 0.0 for k, v in cb.items()}


# ── Degree Centrality ──────────────────────────────────────────────

def _degree(
    node_ids: list[str],
    edges: list[tuple[str, str]],
) -> dict[str, dict[str, int]]:
    """Compute in-degree, out-degree, and total degree."""
    deg = {nid: {"in": 0, "out": 0, "total": 0} for nid in node_ids}
    node_set = set(node_ids)

    for src, dst in edges:
        if src in deg:
            deg[src]["out"] += 1
            deg[src]["total"] += 1
        if dst in deg:
            deg[dst]["in"] += 1
            deg[dst]["total"] += 1

    return deg


# ── Connected Components (BFS, undirected) ─────────────────────────

def _components(
    node_ids: list[str],
    edges: list[tuple[str, str]],
) -> list[list[str]]:
    """Find connected components treating the graph as undirected."""
    # Build undirected adjacency
    adj: dict[str, set[str]] = {nid: set() for nid in node_ids}
    node_set = set(node_ids)
    for src, dst in edges:
        if src in adj and dst in node_set:
            adj[src].add(dst)
            adj[dst].add(src)

    visited: set[str] = set()
    components = []

    for nid in node_ids:
        if nid in visited:
            continue
        # BFS
        comp = []
        queue = deque([nid])
        visited.add(nid)
        while queue:
            v = queue.popleft()
            comp.append(v)
            for w in adj[v]:
                if w not in visited:
                    visited.add(w)
                    queue.append(w)
        components.append(comp)

    # Sort by size descending
    components.sort(key=len, reverse=True)
    return components
