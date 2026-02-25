#!/usr/bin/env python3
"""
Idea Graph Explorer — HTTP server with API endpoints.

Loads all idea_graph.json files from ~/PERMANENT_HYPERDOCS/sessions/,
normalizes schemas, precomputes graph analytics, serves an interactive
HTML visualization page with Cytoscape.js.

Usage:
    python3 -m tools.idea_graph_explorer.server
    python3 -m tools.idea_graph_explorer.server --port 8099

Endpoints:
    GET  /                      → explorer.html page
    GET  /api/sessions          → list all sessions with counts
    GET  /api/graph/{session_id}→ normalized graph + analytics for one session
    GET  /api/graph/all         → combined graph from all sessions
    POST /api/explain           → send graph context to Opus, get explanation
"""

from __future__ import annotations

import os
import sys
import json
import re
import subprocess
import webbrowser
import argparse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Optional, Dict, List

# ── .env loading ───────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
from config import load_env
load_env()

# ── Imports after env setup ─────────────────────────────────────────

from tools.idea_graph_explorer.normalizer import normalize_graph
from tools.idea_graph_explorer.graph_analytics import compute_all

# ── Configuration ───────────────────────────────────────────────────

STORE_DIR = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS")))
SESSIONS_STORE_DIR = STORE_DIR / "sessions"
TEMPLATES_DIR = _REPO / "templates"
DEFAULT_PORT = 8099

# ── Data loading ────────────────────────────────────────────────────

_sessions_cache: dict | None = None
_graph_cache: dict[str, dict] = {}


def _load_all_sessions() -> dict:
    """Scan SESSIONS_STORE_DIR, return session list with metadata."""
    global _sessions_cache
    if _sessions_cache is not None:
        return _sessions_cache

    sessions = []
    total_nodes = 0
    total_edges = 0

    if not SESSIONS_STORE_DIR.exists():
        _sessions_cache = {"sessions": [], "total_nodes": 0, "total_edges": 0}
        return _sessions_cache

    for session_dir in sorted(SESSIONS_STORE_DIR.iterdir()):
        if not session_dir.is_dir():
            continue
        graph_file = session_dir / "idea_graph.json"
        if not graph_file.exists():
            continue

        sid = session_dir.name.replace("session_", "")
        try:
            with open(graph_file) as f:
                data = json.load(f)
            g = normalize_graph(data)
            nc = len(g["nodes"])
            ec = len(g["edges"])
            sc = len(g["subgraphs"])
            sessions.append({
                "id": sid,
                "node_count": nc,
                "edge_count": ec,
                "subgraph_count": sc,
            })
            total_nodes += nc
            total_edges += ec
            # Cache the normalized graph
            _graph_cache[sid] = g
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    _sessions_cache = {
        "sessions": sessions,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
    }
    return _sessions_cache


def _get_graph(session_id: str) -> dict | None:
    """Get normalized graph + analytics for a single session."""
    # Ensure sessions loaded
    _load_all_sessions()

    if session_id not in _graph_cache:
        return None

    g = _graph_cache[session_id]

    # Compute analytics if not already attached
    if "analytics" not in g:
        g["analytics"] = compute_all(g["nodes"], g["edges"])

    return g


def _get_all_graphs() -> dict:
    """Combine all sessions into one big graph with prefixed node IDs."""
    _load_all_sessions()

    all_nodes = []
    all_edges = []
    all_subgraphs = []

    for sid, g in _graph_cache.items():
        # Prefix node IDs with session ID to avoid collision
        for node in g["nodes"]:
            prefixed = dict(node)
            prefixed["id"] = f"{sid}_{node['id']}"
            prefixed["_session_id"] = sid
            all_nodes.append(prefixed)

        for edge in g["edges"]:
            prefixed = dict(edge)
            prefixed["from"] = f"{sid}_{edge['from']}"
            prefixed["to"] = f"{sid}_{edge['to']}"
            prefixed["_session_id"] = sid
            all_edges.append(prefixed)

        for sg in g.get("subgraphs", []):
            prefixed = dict(sg)
            prefixed["id"] = f"{sid}_{sg['id']}"
            prefixed["node_ids"] = [f"{sid}_{nid}" for nid in sg.get("node_ids", [])]
            prefixed["edge_ids"] = [f"{sid}_{eid}" for eid in sg.get("edge_ids", [])]
            prefixed["_session_id"] = sid
            all_subgraphs.append(prefixed)

    combined = {
        "session_id": "all",
        "nodes": all_nodes,
        "edges": all_edges,
        "subgraphs": all_subgraphs,
        "metadata": {"combined": True, "session_count": len(_graph_cache)},
        "analytics": compute_all(all_nodes, all_edges),
    }
    return combined


def _explain(payload: dict) -> dict:
    """Send graph context + question to Opus, return explanation."""
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception as e:
        return {"explanation": f"Opus unavailable: {e}", "referenced_nodes": [], "model": "none"}

    session_id = payload.get("session_id", "")
    question = payload.get("question", "")
    selected_nodes = payload.get("selected_nodes", [])

    if not question:
        return {"explanation": "No question provided.", "referenced_nodes": [], "model": "none"}

    # Build context
    g = None
    if session_id and session_id != "all":
        g = _get_graph(session_id)
    elif session_id == "all":
        g = _get_all_graphs()

    if not g:
        return {"explanation": "Session not found.", "referenced_nodes": [], "model": "none"}

    # Build compact graph representation
    context_parts = []
    context_parts.append(f"Session: {session_id}")
    context_parts.append(f"Nodes ({len(g['nodes'])}):")
    for n in g["nodes"]:
        conf = n.get("confidence", "?")
        mat = n.get("maturity", "?")
        mi = n.get("message_index", "?")
        context_parts.append(f"  {n['id']}: {n['label']} [conf={conf}, mat={mat}, msg={mi}]")

    context_parts.append(f"\nEdges ({len(g['edges'])}):")
    for e in g["edges"]:
        context_parts.append(f"  {e['from']} --[{e['type']}]--> {e['to']}: {e.get('label', '')[:80]}")

    # Analytics summary
    analytics = g.get("analytics", {})
    if analytics:
        pr = analytics.get("pagerank", {})
        bc = analytics.get("betweenness", {})
        if pr:
            top_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:5]
            context_parts.append("\nTop PageRank: " + ", ".join(f"{k}={v:.4f}" for k, v in top_pr))
        if bc:
            top_bc = sorted(bc.items(), key=lambda x: x[1], reverse=True)[:5]
            context_parts.append("Top Betweenness: " + ", ".join(f"{k}={v:.4f}" for k, v in top_bc))

    # Subgraphs
    if g.get("subgraphs"):
        context_parts.append(f"\nSubgraphs ({len(g['subgraphs'])}):")
        for sg in g["subgraphs"]:
            context_parts.append(f"  {sg['name']}: {sg['description'][:80]} nodes={sg['node_ids']}")

    # Selected node detail
    if selected_nodes:
        context_parts.append(f"\nSelected nodes for focus: {selected_nodes}")
        for n in g["nodes"]:
            if n["id"] in selected_nodes:
                context_parts.append(f"  Detail {n['id']}: {n.get('description', '')}")

    context = "\n".join(context_parts)

    prompt = f"""You are analyzing an idea evolution graph from a coding session. The graph tracks how ideas emerged, evolved, split, merged, were abandoned, or pivoted during a development session.

{context}

User question: {question}

Provide a clear, insightful answer. Reference specific node IDs (like N01, N05) when discussing ideas. Format your response as plain text with node IDs in brackets like [N01] when referencing them."""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # Extract referenced node IDs
        referenced = list(set(re.findall(r'\[?(N\d+)\]?', text)))
        referenced.sort()

        return {
            "explanation": text,
            "referenced_nodes": referenced,
            "model": "claude-opus-4-6",
        }
    except Exception as e:
        return {"explanation": f"Error calling Opus: {e}", "referenced_nodes": [], "model": "error"}


# ── HTTP Handler ────────────────────────────────────────────────────

class GraphExplorerHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the Idea Graph Explorer."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/sessions":
            self._json_response(_load_all_sessions())
        elif path.startswith("/api/graph/all"):
            self._json_response(_get_all_graphs())
        elif path.startswith("/api/graph/"):
            session_id = path.split("/api/graph/")[1]
            g = _get_graph(session_id)
            if g:
                self._json_response(g)
            else:
                self._json_response({"error": f"Session {session_id} not found"}, status=404)
        else:
            self._json_response({"error": "Not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/explain":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self._json_response({"error": "Invalid JSON"}, status=400)
                return
            result = _explain(payload)
            self._json_response(result)
        else:
            self._json_response({"error": "Not found"}, status=404)

    def _serve_html(self):
        html_path = TEMPLATES_DIR / "explorer.html"
        if not html_path.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"explorer.html not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_path.read_bytes())

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default request logging clutter."""
        pass


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Idea Graph Explorer server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to serve on")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    port = args.port

    # Preload all sessions
    print(f"Loading sessions from {SESSIONS_STORE_DIR}...")
    info = _load_all_sessions()
    print(f"Loaded {len(info['sessions'])} sessions ({info['total_nodes']} nodes, {info['total_edges']} edges)")

    server = HTTPServer(("127.0.0.1", port), GraphExplorerHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"Serving at {url}")

    # Auto-open browser
    if not args.no_open:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url])
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", url])
        else:
            webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
