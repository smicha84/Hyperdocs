#!/usr/bin/env python3
"""
Ground Truth Verifier — Run independent Python checks against claims.

No LLM. Pure Python + AST + git. Each check returns:
  VERIFIED / FAILED / UNABLE_TO_VERIFY + evidence string.

Portable: searches for source files in multiple locations.

Usage:
    python3 ground_truth_verifier.py --session 0012ebed
    python3 ground_truth_verifier.py --dir /path/to/session_output/

Input:  ground_truth_claims.json (in session dir)
Output: ground_truth_results.json (in session dir)
"""
import ast
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import V5_SOURCE_DIR, get_session_output_dir, SESSION_ID
    V5_CODE = V5_SOURCE_DIR
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    V5_CODE = Path(__file__).resolve().parent.parent / "phase_0_prep"
    _out = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(Path(__file__).parent.parent / "output")))
    def get_session_output_dir():
        d = _out / f"session_{SESSION_ID[:8]}"
        d.mkdir(parents=True, exist_ok=True)
        return d

# Project root for searching
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks" / "hyperdoc"
HYPERDOCS_3 = Path(__file__).resolve().parent.parent

# Search paths for source files (order matters — first match wins)
SEARCH_PATHS = [
    V5_CODE,
    HOOKS_DIR,
    HYPERDOCS_3 / "phase_0_prep",
    HYPERDOCS_3 / "phase_0_prep",
    HYPERDOCS_3 / "phase_1_extraction",
    HYPERDOCS_3 / "phase_2_synthesis",
    HYPERDOCS_3 / "phase_3_hyperdoc_writing",
    HYPERDOCS_3 / "phase_4_hyperdoc_writing",
    HYPERDOCS_3 / "phase_4_insertion",
    HYPERDOCS_3,
    PROJECT_ROOT,
]


def get_source_path(filename):
    """Search for a source file across multiple known locations."""
    for search_dir in SEARCH_PATHS:
        if not search_dir.exists():
            continue
        candidate = search_dir / filename
        if candidate.exists():
            return candidate
    return None


def parse_file(filepath):
    """Parse a Python file into an AST. Returns None on failure."""
    try:
        source = filepath.read_text()
        return ast.parse(source), source
    except (SyntaxError, UnicodeDecodeError):
        return None, None


# ─── CHECK FUNCTIONS ──────────────────────────────────────────


def check_bare_excepts(filepath):
    """AST scan for bare `except:` blocks (no exception type specified)."""
    tree, source = parse_file(filepath)
    if tree is None:
        return "UNABLE_TO_VERIFY", "Could not parse file"

    bare_excepts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            bare_excepts.append(node.lineno)

    if not bare_excepts:
        return "VERIFIED", "No bare except blocks found"
    else:
        lines_str = ", ".join(str(ln) for ln in bare_excepts[:10])
        return "FAILED", f"{len(bare_excepts)} bare except blocks at lines: {lines_str}"


def check_function_exists(filepath, func_name):
    """AST scan to verify a function definition exists."""
    tree, source = parse_file(filepath)
    if tree is None:
        return "UNABLE_TO_VERIFY", "Could not parse file"

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return "VERIFIED", f"Function '{func_name}' found at line {node.lineno}"

    return "FAILED", f"Function '{func_name}' not found in file"


def check_truncation_patterns(filepath):
    """Regex scan for hardcoded slicing limits like [:10], [:20], [:50].

    Filters out false positives:
    - Truncations inside print() calls (display-only)
    - Code preceded by return # DISABLED (dead path)
    - Variables suggesting display/example context (example, sample, preview)
    """
    try:
        source = filepath.read_text()
    except (OSError, UnicodeDecodeError):
        return "UNABLE_TO_VERIFY", "Could not read file"

    pattern = r'\[:(\d+)\]'
    source_lines = source.splitlines()
    matches = []
    for i, line in enumerate(source_lines):
        line_num = i + 1
        for m in re.finditer(pattern, line):
            limit = int(m.group(1))
            if limit >= 10:
                stripped = line.strip()
                # 1. Skip truncations inside print() calls (display-only)
                if "print(" in stripped:
                    continue
                # 2. Skip if function is disabled (return # DISABLED above)
                preceding = source_lines[max(0, i - 4):i]
                if any("# DISABLED" in pl or (pl.strip().startswith("return") and "#" in pl) for pl in preceding):
                    continue
                # 3. Skip if variable name suggests display/example context
                pre_slice = line[:line.find("[:") if "[:" in line else 0].lower()
                if any(kw in pre_slice for kw in ["example", "sample", "preview", "tier_example"]):
                    continue
                matches.append((line_num, limit, stripped[:80]))

    if not matches:
        return "VERIFIED", "No truncation patterns ([:N] where N>=10) found"
    else:
        details = "; ".join(f"line {ln}: [:{lim}]" for ln, lim, _ in matches[:5])
        return "FAILED", f"{len(matches)} truncation patterns: {details}"


def check_model_strings(filepath):
    """Check that LLM model strings specify Opus (not Sonnet/Haiku)."""
    try:
        source = filepath.read_text()
    except (OSError, UnicodeDecodeError):
        return "UNABLE_TO_VERIFY", "Could not read file"

    sonnet_refs = []
    haiku_refs = []
    opus_refs = []

    in_docstring = False
    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        lower = stripped.lower()

        if '"""' in stripped or "'''" in stripped:
            quote = '"""' if '"""' in stripped else "'''"
            count = stripped.count(quote)
            if count == 1:
                in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if stripped.startswith("#") or stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("print("):
            continue

        if "sonnet" in lower:
            sonnet_refs.append(i)
        if "haiku" in lower:
            haiku_refs.append(i)
        if "opus" in lower:
            opus_refs.append(i)

    if sonnet_refs:
        return "FAILED", f"Sonnet references at lines: {', '.join(str(l) for l in sonnet_refs[:5])}"
    if haiku_refs:
        return "FAILED", f"Haiku references at lines: {', '.join(str(l) for l in haiku_refs[:5])}"
    if opus_refs:
        return "VERIFIED", f"Opus references found at {len(opus_refs)} locations, no Sonnet/Haiku"
    return "UNABLE_TO_VERIFY", "No model string references found"


def check_unsafe_api_access(filepath):
    """AST scan for response.content[0].text without guards."""
    try:
        source = filepath.read_text()
    except (OSError, UnicodeDecodeError):
        return "UNABLE_TO_VERIFY", "Could not read file"

    access_pattern = r'\.content\[0\]\.text'
    guard_pattern = r'if\s+(not\s+)?\w+\.content'
    lines = source.splitlines()
    matches = []
    for i, line in enumerate(lines, 1):
        if re.search(access_pattern, line) and not line.strip().startswith("#"):
            # Check for guard on same line or within 3 preceding lines
            guarded = False
            if re.search(guard_pattern, line):
                guarded = True
            else:
                for lookback in range(1, 4):
                    prev_idx = i - 1 - lookback
                    if prev_idx >= 0 and re.search(guard_pattern, lines[prev_idx]):
                        guarded = True
                        break
            if not guarded:
                matches.append(i)

    if not matches:
        return "VERIFIED", "No unguarded response.content[0].text access found"
    else:
        return "FAILED", f"{len(matches)} unsafe access points at lines: {', '.join(str(l) for l in matches[:5])}"


def check_broad_exception_handlers(filepath):
    """AST scan for `except Exception` (better than bare but still broad)."""
    tree, source = parse_file(filepath)
    if tree is None:
        return "UNABLE_TO_VERIFY", "Could not parse file"

    broad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                broad.append(node.lineno)

    if not broad:
        return "VERIFIED", "No broad 'except Exception' handlers found"
    else:
        return "FAILED", f"{len(broad)} broad exception handlers at lines: {', '.join(str(l) for l in broad[:10])}"


# ─── SESSION-DATA VERIFICATION (for deleted files) ──────────────


def load_session_json(session_dir, filename):
    """Load a JSON file from the session directory."""
    path = session_dir / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def check_file_mentioned_in_session(filename, session_dir):
    """Verify this file was actually mentioned in the session."""
    summary = load_session_json(session_dir, "session_metadata.json")
    if not summary:
        return "UNABLE_TO_VERIFY", "session_metadata.json not found"

    stats = summary.get("session_stats", summary)
    mentions = stats.get("file_mention_counts", {})

    # Check exact match and stem match
    stem = filename.replace(".py", "").replace(".json", "").replace(".md", "")
    if filename in mentions:
        count = mentions[filename]
        return "VERIFIED", f"File mentioned {count} times in session"
    # Try stem match
    for key, count in mentions.items():
        if stem in key or key in stem:
            return "VERIFIED", f"File stem '{stem}' matches mention '{key}' ({count} times)"
    return "FAILED", f"File '{filename}' not found in session_metadata file_mention_counts ({len(mentions)} files tracked)"


def check_message_indices_exist(filename, claims, session_dir):
    """Verify claimed message indices actually exist in the session."""
    summary = load_session_json(session_dir, "session_metadata.json")
    if not summary:
        return "UNABLE_TO_VERIFY", "session_metadata.json not found"

    stats = summary.get("session_stats", summary)
    total_msgs = stats.get("total_messages", 0)

    # Collect all message indices from claims
    claimed_indices = []
    for claim_type in ["confidence_claims", "resolution_claims", "unresolved_warnings"]:
        for c in claims.get(claim_type, []):
            idx = c.get("msg_index") or c.get("first_discovered") or c.get("resolution_index")
            if idx is not None and isinstance(idx, (int, float)):
                claimed_indices.append(int(idx))

    if not claimed_indices:
        return "UNABLE_TO_VERIFY", "No message indices in claims to verify"

    invalid = [idx for idx in claimed_indices if idx < 0 or idx >= total_msgs]
    valid = [idx for idx in claimed_indices if 0 <= idx < total_msgs]

    if invalid:
        return "FAILED", f"{len(invalid)} claimed indices out of range (session has {total_msgs} msgs): {invalid[:5]}"
    return "VERIFIED", f"All {len(valid)} claimed message indices are within session range (0-{total_msgs-1})"


def check_confidence_consistency(filename, claims, session_dir):
    """Cross-check confidence claims between semantic_primitives and grounded_markers."""
    primitives = load_session_json(session_dir, "semantic_primitives.json")
    markers = load_session_json(session_dir, "grounded_markers.json")

    if not primitives and not markers:
        return "UNABLE_TO_VERIFY", "Neither semantic_primitives.json nor grounded_markers.json found"

    # Build confidence map from primitives
    prim_confidence = {}
    tagged = primitives.get("tagged_messages", []) if primitives else []
    if not tagged:
        raw = primitives.get("primitives", []) if primitives else []
        tagged = [item.get("primitives", item) if isinstance(item, dict) else item for item in raw]
    for msg in tagged:
        idx = msg.get("msg_index", msg.get("index", msg.get("message_index")))
        conf = msg.get("confidence_signal", "")
        if idx is not None and conf:
            prim_confidence[idx] = conf

    # Check confidence claims against primitives
    contradictions = []
    confirmations = []
    for c in claims.get("confidence_claims", []):
        claimed_conf = c.get("confidence", "")
        claimed_idx = c.get("msg_index")
        if claimed_idx in prim_confidence:
            prim_conf = prim_confidence[claimed_idx]
            if claimed_conf == prim_conf:
                confirmations.append(f"msg {claimed_idx}: {claimed_conf} matches primitives")
            else:
                contradictions.append(f"msg {claimed_idx}: claim={claimed_conf}, primitives={prim_conf}")

    if contradictions:
        return "FAILED", f"{len(contradictions)} confidence contradictions: {'; '.join(contradictions[:3])}"
    if confirmations:
        return "VERIFIED", f"{len(confirmations)} confidence claims match primitives data"
    return "UNABLE_TO_VERIFY", "No overlapping confidence data to cross-check"


def check_idea_graph_references(filename, claims, session_dir):
    """Verify idea graph node references exist."""
    graph = load_session_json(session_dir, "idea_graph.json")
    if not graph:
        return "UNABLE_TO_VERIFY", "idea_graph.json not found"

    nodes = graph.get("nodes", [])
    node_ids = {n.get("id", "") for n in nodes}
    node_labels = {n.get("label", n.get("name", "")).lower() for n in nodes}

    # Check if file is referenced in any idea graph node
    stem = filename.replace(".py", "").replace("_", " ").lower()
    file_nodes = [n for n in nodes if stem in n.get("description", "").lower() or
                  stem in n.get("label", n.get("name", "")).lower() or
                  filename.lower() in n.get("description", "").lower()]

    if file_nodes:
        node_list = ", ".join(n.get("id", "?") for n in file_nodes[:5])
        return "VERIFIED", f"File referenced in {len(file_nodes)} idea graph nodes: {node_list}"

    # Check idea_confidence_claims
    for c in claims.get("idea_confidence_claims", []):
        idea_label = c.get("idea_label", c.get("idea_name", "")).lower()
        if any(idea_label in nl for nl in node_labels):
            return "VERIFIED", f"Claimed idea '{idea_label}' found in idea graph"

    return "UNABLE_TO_VERIFY", f"File not directly referenced in idea graph ({len(nodes)} nodes checked)"


def check_dossier_existence(filename, session_dir):
    """Verify this file has a dossier entry."""
    dossiers = load_session_json(session_dir, "file_dossiers.json")
    if not dossiers:
        return "UNABLE_TO_VERIFY", "file_dossiers.json not found"

    d = dossiers.get("dossiers", dossiers)
    if isinstance(d, dict):
        if filename in d or any(filename in k for k in d.keys()):
            return "VERIFIED", f"File has dossier entry in file_dossiers.json"
    elif isinstance(d, list):
        for item in d:
            fp = item.get("file", item.get("filename", ""))
            if filename in fp or fp in filename:
                return "VERIFIED", f"File has dossier entry: '{fp}'"

    return "FAILED", f"No dossier entry for '{filename}' in file_dossiers.json"


def run_session_data_checks(filename, claims, session_dir):
    """Run verification against session data when file doesn't exist on disk."""
    results = []

    # 1. Was this file actually mentioned in the session?
    result, evidence = check_file_mentioned_in_session(filename, session_dir)
    results.append({
        "claim": "File was mentioned in session",
        "check": "session_data:file_mentioned",
        "result": result,
        "evidence": evidence,
    })

    # 2. Do claimed message indices exist?
    result, evidence = check_message_indices_exist(filename, claims, session_dir)
    results.append({
        "claim": "Claimed message indices exist in session",
        "check": "session_data:message_indices",
        "result": result,
        "evidence": evidence,
    })

    # 3. Are confidence claims consistent across pipeline outputs?
    result, evidence = check_confidence_consistency(filename, claims, session_dir)
    results.append({
        "claim": "Confidence claims consistent across sources",
        "check": "session_data:confidence_consistency",
        "result": result,
        "evidence": evidence,
    })

    # 4. Do idea graph references exist?
    result, evidence = check_idea_graph_references(filename, claims, session_dir)
    results.append({
        "claim": "Idea graph references exist",
        "check": "session_data:idea_graph_refs",
        "result": result,
        "evidence": evidence,
    })

    # 5. Does this file have a dossier entry?
    result, evidence = check_dossier_existence(filename, session_dir)
    results.append({
        "claim": "File has dossier entry",
        "check": "session_data:dossier_exists",
        "result": result,
        "evidence": evidence,
    })

    return results


# ─── VERIFICATION ENGINE ────────────────────────────────────────


def run_checks_for_file(filename, claims, session_dir=None):
    """Run all applicable checks for a file based on its claims."""
    filepath = get_source_path(filename)
    results = []

    if filepath is None:
        # File not on disk — fall back to session-data verification
        if session_dir:
            return run_session_data_checks(filename, claims, session_dir)
        return [{
            "claim": "File exists on disk",
            "check": "file_exists",
            "result": "UNABLE_TO_VERIFY",
            "evidence": f"Source file '{filename}' not found (no session_dir for fallback)",
        }]

    # Universal checks for Python files
    if filename.endswith(".py"):
        result, evidence = check_bare_excepts(filepath)
        results.append({
            "claim": "No bare except blocks",
            "check": "check_bare_excepts",
            "result": result,
            "evidence": evidence,
        })

        result, evidence = check_unsafe_api_access(filepath)
        results.append({
            "claim": "No unsafe response.content[0].text access",
            "check": "check_unsafe_api_access",
            "result": result,
            "evidence": evidence,
        })

        result, evidence = check_truncation_patterns(filepath)
        results.append({
            "claim": "No hardcoded truncation limits",
            "check": "check_truncation_patterns",
            "result": result,
            "evidence": evidence,
        })

        result, evidence = check_broad_exception_handlers(filepath)
        results.append({
            "claim": "Exception handling uses specific types",
            "check": "check_broad_exception_handlers",
            "result": result,
            "evidence": evidence,
        })

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ground Truth Verifier — Independent Python Checks")
    parser.add_argument("--session", default="", help="Session ID")
    parser.add_argument("--dir", default="", help="Session output directory path")
    args = parser.parse_args()

    # Determine session directory
    if args.dir:
        session_dir = Path(args.dir)
    elif args.session:
        candidates = [
            Path(__file__).resolve().parent.parent / "output" / f"session_{args.session[:8]}",
            Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{args.session[:8]}",
        ]
        session_dir = next((c for c in candidates if c.exists()), candidates[0])
    else:
        session_dir = get_session_output_dir()

    print("=" * 60)
    print("Ground Truth Verifier — Independent Python Checks")
    print("=" * 60)
    print(f"Session dir: {session_dir}")
    print(f"V5 code dir: {V5_CODE}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    claims_path = session_dir / "ground_truth_claims.json"
    if not claims_path.exists():
        print("ERROR: ground_truth_claims.json not found. Run claim_extractor.py first.")
        sys.exit(1)

    with open(claims_path) as f:
        claims_data = json.load(f)

    all_claims = claims_data.get("claims", {})
    all_results = {}
    total_verified = 0
    total_failed = 0
    total_unable = 0

    for filename in all_claims:
        file_claims = all_claims[filename]
        checks = run_checks_for_file(filename, file_claims, session_dir=session_dir)

        verified = sum(1 for c in checks if c["result"] == "VERIFIED")
        failed = sum(1 for c in checks if c["result"] == "FAILED")
        unable = sum(1 for c in checks if c["result"] == "UNABLE_TO_VERIFY")

        all_results[filename] = {
            "checks_run": len(checks),
            "verified": verified,
            "failed": failed,
            "unable_to_verify": unable,
            "source_path": str(get_source_path(filename) or "NOT FOUND"),
            "details": checks,
        }

        total_verified += verified
        total_failed += failed
        total_unable += unable

        status = "OK" if failed == 0 else f"{failed} FAILED"
        found = "found" if get_source_path(filename) else "NOT FOUND"
        print(f"  {filename} [{found}]: {len(checks)} checks — {verified}V {failed}F {unable}U [{status}]")

    session_id = args.session or SESSION_ID or session_dir.name.replace("session_", "")
    output = {
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "total_checks": total_verified + total_failed + total_unable,
        "total_verified": total_verified,
        "total_failed": total_failed,
        "total_unable": total_unable,
        "files": all_results,
    }

    out_path = session_dir / "ground_truth_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print()
    print(f"Total: {total_verified + total_failed + total_unable} checks")
    print(f"  VERIFIED: {total_verified}")
    print(f"  FAILED: {total_failed}")
    print(f"  UNABLE: {total_unable}")
    credibility = total_verified / (total_verified + total_failed) if (total_verified + total_failed) > 0 else 0
    print(f"  Credibility: {credibility:.0%}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
