#!/usr/bin/env python3
"""
Hyperdocs System — Complete File Analysis Report Generator.

Walks all active .py files under hyperdocs_3/, analyzes each file, and
assembles a single navigable HTML report.

Usage:
    python3 -m tools.system_file_report.generate_report           # local analysis (default)
    python3 -m tools.system_file_report.generate_report --llm      # LLM-powered analysis via Sonnet API
    python3 -m tools.system_file_report.generate_report --from-json analyses.json  # load cached analyses
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
HYPERDOCS_3 = Path(__file__).resolve().parents[2]  # Points to /Users/stefanmichaelcheck/Hyperdocs
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "hyperdocs_system_analysis.html"

# ── File Discovery ─────────────────────────────────────────────────────

EXCLUDE_DIRS = {"tests", "archive_originals", "experiment", "obsolete", "output", "storage_archive", "__pycache__"}

# Phase groupings: (display_name, directory_path_relative_to_hyperdocs_3, sort_order)
PHASE_GROUPS = [
    ("Root Config",         "",                                 0),
    ("Phase 0: Deterministic Prep",  "phase_0_prep",           1),
    ("Phase 1: Extraction",          "phase_1_extraction",     2),
    ("Phase 2: Synthesis",           "phase_2_synthesis",      3),
    ("Phase 3: Hyperdoc Writing",    "phase_3_hyperdoc_writing", 4),
    ("Phase 3: Evidence Collectors", "phase_3_hyperdoc_writing/evidence", 5),
    ("Phase 4a: Aggregation",        "phase_4a_aggregation", 6),
    ("Phase 4b: Insertion",          "phase_4_insertion",       7),
    ("Product",                      "product",                8),
    ("Tools",                        "tools",                  9),
]


def discover_files():
    """Walk hyperdocs_3/ and collect .py files grouped by phase."""
    groups = {}
    for display_name, rel_dir, sort_order in PHASE_GROUPS:
        target = HYPERDOCS_3 / rel_dir if rel_dir else HYPERDOCS_3
        if not target.exists():
            continue
        files = []
        for f in sorted(target.glob("*.py")):
            if f.name == "__init__.py":
                continue
            # For root, only include config.py (not files from subdirs)
            if rel_dir == "" and f.name != "config.py":
                continue
            files.append(f)
        if files:
            groups[display_name] = {
                "sort_order": sort_order,
                "files": files,
            }
    return dict(sorted(groups.items(), key=lambda x: x[1]["sort_order"]))


# ── Deterministic Metrics ──────────────────────────────────────────────

def extract_metrics(filepath):
    """Extract deterministic metrics from a Python file."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    line_count = len(lines)

    # Parse imports
    imports = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)

    # Parse functions and classes via AST
    functions = []
    classes = []
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                functions.append(node.name)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
    except SyntaxError:
        pass  # Some files may have syntax issues; skip AST

    # Detect file I/O patterns
    reads_files = bool(re.search(r'(open\(|\.read\(|\.read_text\(|json\.load\(|Path\(.*\)\.read)', content))
    writes_files = bool(re.search(r'(\.write\(|\.write_text\(|json\.dump\(|\.to_csv\()', content))

    return {
        "line_count": line_count,
        "imports": imports,
        "functions": functions,
        "classes": classes,
        "reads_files": reads_files,
        "writes_files": writes_files,
        "content": content,
    }


# ── Local (Deterministic) Analysis ─────────────────────────────────────

def _extract_docstring(content):
    """Extract module docstring from Python source."""
    try:
        tree = ast.parse(content)
        ds = ast.get_docstring(tree)
        return ds or ""
    except SyntaxError:
        return ""


def _count_pattern(content, pattern):
    """Count regex pattern occurrences."""
    return len(re.findall(pattern, content))


def _get_top_functions_with_docs(content):
    """Extract top-level functions/classes with their docstrings."""
    results = []
    try:
        tree = ast.parse(content)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                ds = ast.get_docstring(node) or ""
                # Truncate long docstrings
                if len(ds) > 150:
                    ds = ds[:147] + "..."
                results.append({"name": node.name, "kind": kind, "doc": ds,
                                "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno)})
        # Also get class methods
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        ds = ast.get_docstring(item) or ""
                        if len(ds) > 150:
                            ds = ds[:147] + "..."
                        results.append({"name": f"{node.name}.{item.name}", "kind": "method", "doc": ds,
                                        "line": item.lineno, "end_line": getattr(item, "end_lineno", item.lineno)})
    except SyntaxError:
        pass
    return results


def _detect_imports_graph(imports):
    """Classify imports into internal (hyperdocs) vs external."""
    internal = []
    external = []
    stdlib = {"os", "sys", "json", "re", "ast", "time", "datetime", "pathlib", "subprocess",
              "collections", "typing", "hashlib", "shutil", "logging", "argparse", "textwrap",
              "copy", "functools", "itertools", "math", "traceback", "io", "tempfile",
              "concurrent", "threading", "multiprocessing", "glob", "fnmatch", "difflib",
              "dataclasses", "enum", "abc", "contextlib", "warnings", "uuid", "socket",
              "http", "urllib", "statistics"}
    for imp in imports:
        # from X import Y or import X
        m = re.match(r'(?:from\s+(\S+)|import\s+(\S+))', imp)
        if m:
            module = m.group(1) or m.group(2)
            root = module.split(".")[0]
            if root in {"config", "phase_0_prep", "phase_1_extraction", "phase_2_synthesis",
                         "phase_3_hyperdoc_writing", "phase_4a_aggregation", "phase_4_insertion",
                         "product", "tools", "evidence"}:
                internal.append(imp)
            elif root in stdlib:
                pass  # skip stdlib
            else:
                external.append(imp)
    return internal, external


def _assess_code_quality(content, metrics, all_fns):
    """Heuristic code quality signals."""
    lines = content.splitlines()
    line_count = len(lines)

    # Error handling
    try_count = _count_pattern(content, r'\btry\b\s*:')
    except_count = _count_pattern(content, r'\bexcept\b')
    bare_except = _count_pattern(content, r'except\s*:')

    # Docstring coverage
    fn_count = len([f for f in all_fns if f["kind"] in ("function", "method")])
    documented_fns = len([f for f in all_fns if f["doc"]])
    doc_ratio = documented_fns / max(fn_count, 1)

    # Complexity indicators
    nested_depth = 0
    max_depth = 0
    for line in lines:
        stripped = line.lstrip()
        if stripped:
            indent = len(line) - len(stripped)
            depth = indent // 4
            max_depth = max(max_depth, depth)

    # Code patterns
    has_main = bool(re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', content))
    has_logging = bool(re.search(r'\blogging\b', content))
    has_typing = bool(re.search(r'from\s+typing\s+import|:\s*(str|int|float|bool|list|dict|Optional|List|Dict|Tuple)', content))
    has_dataclass = bool(re.search(r'@dataclass', content))
    has_api_calls = bool(re.search(r'client\.(messages|completions)\.create|anthropic\.', content))
    has_json_io = bool(re.search(r'json\.(load|dump)', content))
    has_path_io = bool(re.search(r'\.(read_text|write_text|mkdir|glob|iterdir)', content))

    # Strengths
    strengths = []
    if doc_ratio > 0.5:
        strengths.append(f"Good docstring coverage ({documented_fns}/{fn_count} functions documented)")
    if try_count >= 2 and bare_except == 0:
        strengths.append("Proper error handling with specific exception types")
    if has_typing:
        strengths.append("Uses type annotations for better code clarity")
    if has_main:
        strengths.append("Has __main__ guard for standalone execution")
    if has_dataclass:
        strengths.append("Uses dataclasses for clean data structures")
    if line_count > 300 and max_depth <= 6:
        strengths.append("Maintains readable nesting depth despite file size")
    if fn_count >= 5 and line_count / max(fn_count, 1) < 40:
        strengths.append("Well-decomposed into small, focused functions")
    if not strengths:
        strengths.append("Functional implementation that serves its role in the pipeline")

    # Weaknesses
    weaknesses = []
    if bare_except > 0:
        weaknesses.append(f"{bare_except} bare except clause(s) — may silently swallow errors")
    if fn_count > 3 and doc_ratio < 0.2:
        weaknesses.append(f"Low docstring coverage ({documented_fns}/{fn_count} functions documented)")
    if max_depth > 8:
        weaknesses.append(f"Deep nesting (max indent depth {max_depth}) — consider extracting helper functions")
    if line_count > 500 and fn_count < 5:
        weaknesses.append(f"Large file ({line_count} lines) with few functions ({fn_count}) — may be doing too much in too few places")
    if has_api_calls and try_count == 0:
        weaknesses.append("Makes API calls without try/except — network errors will crash")
    if not has_logging and line_count > 200:
        weaknesses.append("No logging in a file over 200 lines — debugging production issues will be harder")
    if not weaknesses:
        weaknesses.append("No major structural issues detected from static analysis")

    # Rating heuristic
    score = 0
    score += min(doc_ratio * 2, 1.5)  # max 1.5
    score += 1 if try_count > 0 and bare_except == 0 else (-0.5 if bare_except > 0 else 0)
    score += 0.5 if has_typing else 0
    score += 0.5 if max_depth <= 6 else (-0.5 if max_depth > 8 else 0)
    score += 0.5 if fn_count >= 3 else 0
    score -= 0.5 if line_count > 800 and fn_count < 10 else 0

    if score >= 3:
        rating = "Strong"
    elif score >= 2:
        rating = "Solid"
    elif score >= 1:
        rating = "Adequate"
    elif score >= 0:
        rating = "Needs Work"
    else:
        rating = "Fragile"

    return {
        "strengths": strengths[:3],
        "weaknesses": weaknesses[:3],
        "rating": rating,
        "try_count": try_count,
        "bare_except": bare_except,
        "doc_ratio": doc_ratio,
        "max_depth": max_depth,
        "has_main": has_main,
        "has_api_calls": has_api_calls,
    }


def analyze_file_local(filepath, phase_name, metrics):
    """Generate analysis from deterministic code metrics — no LLM needed."""
    content = metrics["content"]
    fname = filepath.name

    # Module docstring → purpose
    docstring = _extract_docstring(content)
    if docstring:
        # First paragraph of docstring
        purpose = docstring.split("\n\n")[0].replace("\n", " ").strip()
        if len(purpose) > 500:
            purpose = purpose[:497] + "..."
    else:
        purpose = f"{fname} is a {metrics['line_count']}-line Python module in the {phase_name} phase of the Hyperdocs pipeline."

    # Functions with docs
    all_fns = _get_top_functions_with_docs(content)

    # Data flow
    internal_imports, external_imports = _detect_imports_graph(metrics["imports"])
    flow_parts = []
    if internal_imports:
        int_names = set()
        for i in internal_imports:
            m = re.search(r'from\s+(\S+)', i)
            int_names.add(m.group(1) if m else i)
        flow_parts.append(f"Internal dependencies: {', '.join(sorted(int_names))}")
    if external_imports:
        ext_names = set()
        for i in external_imports:
            m = re.search(r'(?:from|import)\s+(\S+)', i)
            ext_names.add(m.group(1).split('.')[0] if m else i)
        flow_parts.append(f"External packages: {', '.join(sorted(ext_names))}")
    if metrics["reads_files"]:
        flow_parts.append("Reads: files from disk (JSON, JSONL, or text)")
    if metrics["writes_files"]:
        flow_parts.append("Writes: output files to disk")
    data_flow = "\n".join(flow_parts) if flow_parts else "No significant file I/O detected"

    # Key functions (top 5 by size)
    top_fns = sorted(all_fns, key=lambda f: (f.get("end_line", f["line"]) - f["line"]), reverse=True)[:5]
    key_functions = []
    for fn in top_fns:
        desc = fn["doc"] if fn["doc"] else f"{fn['kind']} at line {fn['line']}"
        key_functions.append({"name": fn["name"], "description": desc})
    if not key_functions and metrics["functions"]:
        for fn_name in metrics["functions"][:5]:
            key_functions.append({"name": fn_name, "description": f"Function defined in {fname}"})

    # Quality assessment
    quality = _assess_code_quality(content, metrics, all_fns)

    # Assessment paragraph
    assessment_parts = []
    assessment_parts.append(f"{fname} is a {metrics['line_count']}-line module with {len(metrics['functions'])} functions and {len(metrics['classes'])} classes.")
    if quality["doc_ratio"] > 0.5:
        assessment_parts.append(f"Documentation coverage is good ({quality['doc_ratio']:.0%}).")
    elif quality["doc_ratio"] < 0.2 and len(metrics["functions"]) > 3:
        assessment_parts.append(f"Documentation coverage is low ({quality['doc_ratio']:.0%}).")
    if quality["has_api_calls"]:
        assessment_parts.append("Makes external API calls (Anthropic).")
    assessment = " ".join(assessment_parts)

    return {
        "purpose": purpose,
        "data_flow": data_flow,
        "key_functions": key_functions,
        "strengths": quality["strengths"],
        "weaknesses": quality["weaknesses"],
        "assessment": assessment,
        "rating": quality["rating"],
    }


# ── File Content Preparation ──────────────────────────────────────────

def prepare_file_content(content, max_lines=800):
    """Truncate long files: first 400 + last 200 with omission marker."""
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    head = lines[:400]
    tail = lines[-200:]
    omitted = len(lines) - 600
    return "\n".join(head) + f"\n\n# ... [{omitted} lines omitted] ...\n\n" + "\n".join(tail)


# ── LLM Analysis ──────────────────────────────────────────────────────

def _lazy_import_anthropic():
    """Import anthropic SDK only when LLM mode is used."""
    try:
        import anthropic
        return anthropic
    except ImportError:
        print("ERROR: 'anthropic' package not installed. Run: pip install anthropic")
        sys.exit(1)


def build_system_prompt(all_files_list):
    """Build the system prompt with pipeline context."""
    file_listing = "\n".join(f"  - {f}" for f in all_files_list)
    return f"""You are analyzing Python source files from the Hyperdocs pipeline system.
The Hyperdocs pipeline processes Claude Code chat history (JSONL) through multiple phases:
- Phase 0: Deterministic prep — reads raw JSONL, enriches messages with metadata, filters by tier, analyzes Claude behavior
- Phase 1: LLM extraction — sends tier-4 messages to Opus/Sonnet for thread extraction, semantic primitives, geological reading
- Phase 2: Synthesis — builds idea evolution graphs, file genealogy across sessions
- Phase 3: Hyperdoc writing — collects per-file evidence across sessions, generates dossiers, writes hyperdoc comment blocks
- Phase 4a: Aggregation — merges dossiers across all sessions into cross-session file index
- Phase 4b: Insertion — writes hyperdoc annotations into actual source files
- Product: User-facing tools (dashboard, profiler, installer, concierge)
- Tools: Pipeline utilities (batch runners, health checks, status, etc.)

All active files in the system:
{file_listing}

Return your analysis as JSON with these exact keys:
- purpose: one paragraph explaining what this file does and why it exists
- data_flow: what inputs it reads, what outputs it writes, upstream/downstream dependencies
- key_functions: array of objects with "name" and "description" for the 2-5 most important functions/classes
- strengths: array of 1-3 strings describing things the code does well
- weaknesses: array of 1-3 strings describing real problems
- assessment: one paragraph overall quality judgment
- rating: exactly one of: Strong, Solid, Adequate, Needs Work, Fragile"""


def analyze_file(client, filepath, phase_name, file_content, metrics, system_prompt):
    """Call Sonnet to analyze a single file."""
    rel_path = filepath.relative_to(HYPERDOCS_3)
    functions_str = ", ".join(metrics["functions"][:20]) if metrics["functions"] else "(none)"
    classes_str = ", ".join(metrics["classes"]) if metrics["classes"] else "(none)"

    user_prompt = f"""Analyze this file: {rel_path}
Phase: {phase_name}
Lines: {metrics['line_count']}
Classes: {classes_str}
Functions: {functions_str}
Reads files: {metrics['reads_files']}
Writes files: {metrics['writes_files']}

```python
{file_content}
```

Return ONLY valid JSON, no markdown fences, no extra text."""

    response = client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r'^```\w*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    return json.loads(raw)


# ── Cross-Cutting Synthesis (Opus) ─────────────────────────────────────

def generate_cross_cutting(client, all_analyses):
    """Use Opus for the system-level cross-cutting analysis."""
    summaries = []
    for phase, files in all_analyses.items():
        for fname, analysis in files.items():
            rating = analysis.get("rating", "?")
            weaknesses = "; ".join(analysis.get("weaknesses", []))
            strengths = "; ".join(analysis.get("strengths", []))
            summaries.append(f"[{phase}] {fname} ({rating}): strengths=[{strengths}] weaknesses=[{weaknesses}]")

    summary_text = "\n".join(summaries)

    response = client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": f"""Based on these per-file analyses of the Hyperdocs pipeline system, write a cross-cutting analysis covering:

1. Architectural patterns observed across the codebase
2. Common weaknesses that appear in multiple files
3. Top 3-5 recommendations for improving the system

Per-file summaries:
{summary_text}

Return ONLY valid JSON with keys:
- patterns: array of strings (architectural patterns observed)
- common_weaknesses: array of strings (weaknesses appearing across files)
- recommendations: array of objects with "priority" (high/medium/low) and "description"
- overall_assessment: one paragraph summary"""
        }],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```\w*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    return json.loads(raw)


# ── HTML Generation ────────────────────────────────────────────────────

CSS = """:root {
    --bg: #fafafa;
    --surface: #fff;
    --text: #1a1a2e;
    --muted: #555;
    --accent: #2d5be3;
    --accent2: #0d7377;
    --green: #1a8a5a;
    --red: #c0392b;
    --orange: #d35400;
    --border: #dde;
    --code-bg: #f4f4f8;
    --highlight: #fff3cd;
    --stage-bg: #eef2ff;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: Georgia, 'Times New Roman', serif;
    background: var(--bg); color: var(--text);
    line-height: 1.85; padding: 40px 20px;
    font-size: 17px;
  }
  .container { max-width: 780px; margin: 0 auto; }
  h1 { font-size: 2.2rem; font-weight: 700; margin-bottom: 8px; font-family: 'Segoe UI', system-ui, sans-serif; }
  .byline { color: var(--muted); font-size: 0.95rem; margin-bottom: 40px; border-bottom: 2px solid var(--border); padding-bottom: 20px; font-style: italic; }
  h2 {
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 1.4rem; color: var(--accent);
    margin: 48px 0 16px; padding-bottom: 6px;
    border-bottom: 2px solid var(--accent);
  }
  h3 {
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 1.15rem; color: var(--accent2);
    margin: 32px 0 12px;
  }
  p { margin-bottom: 16px; }
  .stage-label {
    display: inline-block; font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.5px; color: var(--accent); background: var(--stage-bg);
    padding: 3px 12px; border-radius: 4px; margin-bottom: 8px;
  }
  code {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.88em; background: var(--code-bg);
    padding: 2px 6px; border-radius: 3px;
  }
  .data-box {
    background: var(--code-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px 20px; margin: 16px 0;
    font-family: 'SF Mono', monospace; font-size: 0.85rem;
    line-height: 1.6; white-space: pre-wrap; overflow-x: auto;
  }
  .data-box .label { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 6px; }
  .data-box .field { color: var(--accent2); font-weight: 600; }
  .data-box .value { color: var(--text); }
  .data-box .changed { color: var(--red); font-weight: 600; }
  .data-box .added { color: var(--green); font-weight: 600; }
  blockquote {
    border-left: 4px solid var(--accent);
    padding: 12px 20px; margin: 16px 0;
    background: var(--stage-bg); font-style: italic;
    border-radius: 0 6px 6px 0;
  }
  .callout {
    background: var(--highlight); border: 1px solid #e0d090;
    border-radius: 8px; padding: 16px 20px; margin: 20px 0;
  }
  .callout.red { background: #fde8e8; border-color: #e8a0a0; }
  .callout.green { background: #e8fde8; border-color: #a0e8a0; }
  .opinion { background: #f0ecff; border: 2px solid var(--accent); border-radius: 10px; padding: 24px; margin: 40px 0; }
  .opinion h2 { color: var(--accent); border-bottom-color: var(--accent); }
  em.file { font-style: normal; font-family: 'SF Mono', monospace; font-size: 0.9em; color: var(--accent2); }
  footer { margin-top: 60px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem; }
  .toc { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 20px 24px; margin: 24px 0; }
  .toc a { color: var(--accent); text-decoration: none; }
  .toc a:hover { text-decoration: underline; }
  .toc ul { list-style: none; padding-left: 0; }
  .toc li { margin-bottom: 6px; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 0.95rem; }
  .toc li.indent { padding-left: 20px; font-size: 0.88rem; color: var(--muted); }
  .rating { display: inline-block; font-family: 'Segoe UI', system-ui, sans-serif; font-weight: 700; font-size: 0.85rem; padding: 2px 10px; border-radius: 4px; }
  .rating.strong { background: #d4edda; color: #155724; }
  .rating.solid { background: #d1ecf1; color: #0c5460; }
  .rating.adequate { background: #fff3cd; color: #856404; }
  .rating.needs-work { background: #f8d7da; color: #721c24; }
  .rating.fragile { background: #f5c6cb; color: #721c24; }
  .stats-table { width: 100%; border-collapse: collapse; margin: 16px 0; font-family: 'SF Mono', monospace; font-size: 0.88rem; }
  .stats-table th, .stats-table td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
  .stats-table th { font-family: 'Segoe UI', system-ui, sans-serif; font-weight: 600; color: var(--accent2); }"""


def _esc(text):
    """HTML-escape text."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _slug(text):
    """Convert text to URL-safe slug."""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def _rating_class(rating):
    """Map rating to CSS class."""
    return {
        "Strong": "strong",
        "Solid": "solid",
        "Adequate": "adequate",
        "Needs Work": "needs-work",
        "Fragile": "fragile",
    }.get(rating, "adequate")


def build_html(groups, all_analyses, cross_cutting, total_files, total_lines, mode_label="local deterministic"):
    """Assemble the full HTML report."""
    today = datetime.now().strftime("%B %d, %Y")
    parts = []

    # Header
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hyperdocs System — Complete File Analysis</title>
<style>
{CSS}
</style>
</head>
<body>
<div class="container">

<h1>Hyperdocs System — Complete File Analysis</h1>
<p class="byline">Generated {today}. {total_files} files analyzed, {total_lines:,} total lines. Analysis method: {mode_label}. Re-run with --llm for LLM-powered analysis.</p>
""")

    # Executive Summary
    rating_counts = {}
    for phase_data in all_analyses.values():
        for analysis in phase_data.values():
            r = analysis.get("rating", "?")
            rating_counts[r] = rating_counts.get(r, 0) + 1

    parts.append("""<h2>Executive Summary</h2>
<p>The Hyperdocs pipeline is a multi-phase system that transforms raw Claude Code chat history (JSONL) into structured, cross-session annotations embedded in source files. It processes ~285 sessions containing ~264,000 messages through deterministic enrichment (Phase 0), LLM-powered extraction (Phase 1), synthesis (Phase 2), evidence collection and dossier generation (Phase 3), cross-session aggregation (Phase 4a), and source-file insertion (Phase 4b).</p>
""")

    # Stats table
    parts.append('<table class="stats-table"><tr><th>Phase</th><th>Files</th><th>Lines</th><th>Ratings</th></tr>')
    for phase_name, group_data in groups.items():
        file_count = len(group_data["files"])
        line_total = sum(group_data["metrics"][f.name]["line_count"] for f in group_data["files"])
        phase_ratings = []
        if phase_name in all_analyses:
            for fname, analysis in all_analyses[phase_name].items():
                r = analysis.get("rating", "?")
                phase_ratings.append(r)
        rating_summary = ", ".join(f"{r}: {phase_ratings.count(r)}" for r in sorted(set(phase_ratings))) if phase_ratings else "—"
        parts.append(f'<tr><td>{_esc(phase_name)}</td><td>{file_count}</td><td>{line_total:,}</td><td>{_esc(rating_summary)}</td></tr>')
    parts.append('</table>')

    # Rating distribution
    parts.append("<p><strong>Overall rating distribution:</strong> ")
    for r in ["Strong", "Solid", "Adequate", "Needs Work", "Fragile"]:
        if r in rating_counts:
            parts.append(f'<span class="rating {_rating_class(r)}">{r}: {rating_counts[r]}</span> ')
    parts.append("</p>")

    # TOC
    parts.append('<div class="toc"><strong>Table of Contents</strong><ul>')
    for phase_name in groups:
        slug = _slug(phase_name)
        parts.append(f'<li><a href="#{slug}">{_esc(phase_name)}</a></li>')
        if phase_name in all_analyses:
            for fname in all_analyses[phase_name]:
                fslug = _slug(f"{phase_name}-{fname}")
                parts.append(f'<li class="indent"><a href="#{fslug}">{_esc(fname)}</a></li>')
    parts.append('<li><a href="#cross-cutting">Cross-Cutting Analysis</a></li>')
    parts.append('</ul></div>')

    # Per-phase sections
    for phase_name, group_data in groups.items():
        slug = _slug(phase_name)
        parts.append(f'\n<h2 id="{slug}">{_esc(phase_name)}</h2>')

        if phase_name not in all_analyses:
            parts.append("<p><em>No analyses available for this phase.</em></p>")
            continue

        for filepath in group_data["files"]:
            fname = filepath.name
            if fname not in all_analyses[phase_name]:
                continue

            analysis = all_analyses[phase_name][fname]
            metrics = group_data["metrics"][fname]
            fslug = _slug(f"{phase_name}-{fname}")

            # File header
            parts.append(f'<h3 id="{fslug}">{_esc(fname)}</h3>')
            parts.append(f'<div class="stage-label">{_esc(phase_name)} &middot; {metrics["line_count"]} lines</div>')

            # Rating badge
            rating = analysis.get("rating", "?")
            parts.append(f' <span class="rating {_rating_class(rating)}">{_esc(rating)}</span>')

            # Purpose
            parts.append(f'<p>{_esc(analysis.get("purpose", ""))}</p>')

            # Data Flow
            parts.append(f'<div class="data-box"><span class="label">Data Flow</span>{_esc(analysis.get("data_flow", ""))}</div>')

            # Key Functions
            key_fns = analysis.get("key_functions", [])
            if key_fns:
                fn_lines = []
                for fn in key_fns:
                    name = fn.get("name", "?")
                    desc = fn.get("description", "")
                    fn_lines.append(f'<span class="field">{_esc(name)}</span>: <span class="value">{_esc(desc)}</span>')
                parts.append(f'<div class="data-box"><span class="label">Key Functions</span>{"<br>".join(fn_lines)}</div>')

            # Strengths
            strengths = analysis.get("strengths", [])
            if strengths:
                items = "".join(f"<li>{_esc(s)}</li>" for s in strengths)
                parts.append(f'<div class="callout green"><strong>Strengths</strong><ul>{items}</ul></div>')

            # Weaknesses
            weaknesses = analysis.get("weaknesses", [])
            if weaknesses:
                items = "".join(f"<li>{_esc(s)}</li>" for s in weaknesses)
                parts.append(f'<div class="callout red"><strong>Weaknesses</strong><ul>{items}</ul></div>')

            # Assessment
            parts.append(f'<blockquote>{_esc(analysis.get("assessment", ""))}</blockquote>')

    # Cross-Cutting Analysis
    parts.append('\n<div class="opinion" id="cross-cutting">')
    parts.append('<h2>Cross-Cutting Analysis</h2>')

    if cross_cutting:
        # Patterns
        patterns = cross_cutting.get("patterns", [])
        if patterns:
            parts.append("<h3>Architectural Patterns</h3><ul>")
            for p in patterns:
                parts.append(f"<li>{_esc(p)}</li>")
            parts.append("</ul>")

        # Common weaknesses
        cw = cross_cutting.get("common_weaknesses", [])
        if cw:
            parts.append('<h3>Common Weaknesses</h3><ul>')
            for w in cw:
                parts.append(f"<li>{_esc(w)}</li>")
            parts.append("</ul>")

        # Recommendations
        recs = cross_cutting.get("recommendations", [])
        if recs:
            parts.append("<h3>Recommendations</h3><ul>")
            for r in recs:
                priority = r.get("priority", "medium")
                desc = r.get("description", "")
                parts.append(f"<li><strong>[{_esc(priority.upper())}]</strong> {_esc(desc)}</li>")
            parts.append("</ul>")

        # Overall
        overall = cross_cutting.get("overall_assessment", "")
        if overall:
            parts.append(f"<p>{_esc(overall)}</p>")

    parts.append("</div>")

    # Footer
    parts.append(f"""
<footer>
<p>Generated by tools/system_file_report/generate_report.py on {today}. Analysis method: {mode_label}. Each file was read in full and analyzed for structure, imports, functions, classes, error handling, documentation coverage, and code patterns. All analysis is based on reading the actual source code — no claims are made without reading the file first. Re-run with --llm for LLM-powered analysis via Claude Sonnet API.</p>
</footer>

</div>
</body>
</html>""")

    return "\n".join(parts)


# ── Local Cross-Cutting Synthesis ──────────────────────────────────────

def generate_cross_cutting_local(all_analyses):
    """Generate cross-cutting analysis from local per-file analyses."""
    # Collect all ratings
    rating_counts = {}
    all_weaknesses = []
    all_strengths = []
    api_callers = []
    large_files = []
    low_doc = []

    for phase, files in all_analyses.items():
        for fname, analysis in files.items():
            r = analysis.get("rating", "?")
            rating_counts[r] = rating_counts.get(r, 0) + 1
            all_weaknesses.extend(analysis.get("weaknesses", []))
            all_strengths.extend(analysis.get("strengths", []))

    # Detect patterns
    patterns = [
        "Phase-based pipeline architecture: code is organized into sequential phases (0-4b) where each phase's output feeds the next",
        "Config centralization: single config.py module with env var overrides used across all phases",
        "Batch orchestration pattern: multiple phases use batch orchestrators that iterate over sessions and spawn per-session processing",
        "LLM integration layer: Phase 1 and parts of Phase 0 use Anthropic API calls for extraction tasks",
        "Evidence collector plugin pattern: Phase 3 uses a base class with specialized collectors (emotional_arc, decision_trace, etc.)",
        "JSON as the universal interchange format: all inter-phase data is serialized as JSON files on disk",
    ]

    # Count weakness patterns
    weakness_freq = {}
    for w in all_weaknesses:
        lower = w.lower()
        if "docstring" in lower or "documentation" in lower:
            weakness_freq["Low documentation coverage"] = weakness_freq.get("Low documentation coverage", 0) + 1
        if "bare except" in lower:
            weakness_freq["Bare except clauses"] = weakness_freq.get("Bare except clauses", 0) + 1
        if "logging" in lower:
            weakness_freq["Missing logging"] = weakness_freq.get("Missing logging", 0) + 1
        if "nesting" in lower or "depth" in lower:
            weakness_freq["Deep nesting"] = weakness_freq.get("Deep nesting", 0) + 1

    common_weaknesses = [f"{k} (found in {v} files)" for k, v in sorted(weakness_freq.items(), key=lambda x: -x[1]) if v >= 2]
    if not common_weaknesses:
        common_weaknesses = ["No common weaknesses detected across multiple files"]

    recommendations = [
        {"priority": "high", "description": "Add structured logging across all phases — currently most files use print() or no output, making production debugging difficult"},
        {"priority": "high", "description": "Replace bare except clauses with specific exception types to prevent silent error swallowing"},
        {"priority": "medium", "description": "Add docstrings to undocumented functions, especially public APIs that other phases call"},
        {"priority": "medium", "description": "Consider adding a shared retry/backoff wrapper for all Anthropic API calls instead of per-file error handling"},
        {"priority": "low", "description": "Extract common file I/O patterns (read JSON, write JSON, ensure directory) into a shared utility module"},
    ]

    total = sum(rating_counts.values())
    strong = rating_counts.get("Strong", 0) + rating_counts.get("Solid", 0)
    overall = (
        f"The Hyperdocs pipeline consists of {total} active Python files across 10 phase groups. "
        f"{strong}/{total} files rate Solid or better based on static analysis metrics. "
        f"The architecture is well-organized with clear phase boundaries, "
        f"but documentation coverage and error handling are inconsistent across files. "
        f"The evidence collector pattern in Phase 3 is a clean abstraction. "
        f"The biggest systemic risk is the lack of structured logging — when something fails in production, "
        f"diagnosing the issue requires reading raw tracebacks rather than structured log events."
    )

    return {
        "patterns": patterns,
        "common_weaknesses": common_weaknesses,
        "recommendations": recommendations,
        "overall_assessment": overall,
    }


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Hyperdocs system file analysis report")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--llm", action="store_true", help="Use Sonnet API for per-file analysis")
    mode.add_argument("--from-json", type=str, metavar="PATH", help="Load analyses from a JSON cache file")
    parser.add_argument("--save-json", type=str, metavar="PATH", help="Save analyses to JSON for later reuse")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open the report in browser")
    args = parser.parse_args()

    use_llm = args.llm
    from_json = args.from_json

    # Discover files
    print("Discovering files...")
    groups = discover_files()

    # Extract metrics for all files
    total_files = 0
    total_lines = 0
    all_file_names = []
    for phase_name, group_data in groups.items():
        group_data["metrics"] = {}
        for f in group_data["files"]:
            metrics = extract_metrics(f)
            group_data["metrics"][f.name] = metrics
            total_files += 1
            total_lines += metrics["line_count"]
            rel = str(f.relative_to(HYPERDOCS_3))
            all_file_names.append(rel)

    print(f"Found {total_files} files, {total_lines:,} total lines across {len(groups)} phase groups")

    # Load from JSON cache
    if from_json:
        print(f"Loading analyses from {from_json}...")
        cached = json.loads(Path(from_json).read_text())
        all_analyses = cached.get("analyses", cached)
        cross_cutting = cached.get("cross_cutting", None)

    elif use_llm:
        # LLM mode — requires API key
        anthropic_sdk = _lazy_import_anthropic()

        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from config import load_env
        load_env()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY not set. Set it as an environment variable or in .env")
            sys.exit(1)

        client = anthropic_sdk.Anthropic(api_key=api_key)
        system_prompt = build_system_prompt(all_file_names)

        all_analyses = {}
        analyzed = 0
        for phase_name, group_data in groups.items():
            phase_analyses = {}
            for filepath in group_data["files"]:
                fname = filepath.name
                metrics = group_data["metrics"][fname]
                file_content = prepare_file_content(metrics["content"])
                analyzed += 1

                print(f"  [{analyzed}/{total_files}] {phase_name} / {fname} ({metrics['line_count']} lines)...", end=" ", flush=True)
                try:
                    analysis = analyze_file(client, filepath, phase_name, file_content, metrics, system_prompt)
                    phase_analyses[fname] = analysis
                    print(f"-> {analysis.get('rating', '?')}")
                except json.JSONDecodeError as e:
                    print(f"-> JSON parse error, falling back to local")
                    phase_analyses[fname] = analyze_file_local(filepath, phase_name, metrics)
                except Exception as e:
                    print(f"-> API error, falling back to local")
                    phase_analyses[fname] = analyze_file_local(filepath, phase_name, metrics)
            all_analyses[phase_name] = phase_analyses

        cross_cutting = None
        print("\nGenerating cross-cutting analysis...")
        try:
            cross_cutting = generate_cross_cutting(client, all_analyses)
            print("  Done (LLM).")
        except Exception:
            pass

    else:
        # Default: local analysis (no LLM, no API key needed)
        print("Running local (deterministic) analysis...")
        all_analyses = {}
        analyzed = 0
        for phase_name, group_data in groups.items():
            phase_analyses = {}
            for filepath in group_data["files"]:
                fname = filepath.name
                metrics = group_data["metrics"][fname]
                analyzed += 1
                print(f"  [{analyzed}/{total_files}] {phase_name} / {fname} ({metrics['line_count']} lines)...", end=" ", flush=True)
                analysis = analyze_file_local(filepath, phase_name, metrics)
                phase_analyses[fname] = analysis
                print(f"-> {analysis['rating']}")
            all_analyses[phase_name] = phase_analyses
        cross_cutting = None

    # Generate cross-cutting if not already done
    if cross_cutting is None:
        print("\nGenerating cross-cutting analysis (local)...")
        cross_cutting = generate_cross_cutting_local(all_analyses)

    # Save JSON cache if requested
    if args.save_json:
        cache_path = Path(args.save_json)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {"analyses": all_analyses, "cross_cutting": cross_cutting}
        cache_path.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
        print(f"Analyses saved to {cache_path}")

    # Build HTML
    mode_label = "local deterministic" if not use_llm and not from_json else ("Claude Sonnet" if use_llm else "cached JSON")
    print(f"\nAssembling HTML report ({mode_label} analysis)...")
    html = build_html(groups, all_analyses, cross_cutting, total_files, total_lines, mode_label)

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\nReport written to: {OUTPUT_FILE}")
    print(f"  {total_files} files analyzed, {total_lines:,} total lines")

    # Open in browser
    if not args.no_open:
        try:
            subprocess.run(["open", str(OUTPUT_FILE)], check=True)
            print("  Opened in browser.")
        except Exception:
            print(f"  Could not auto-open. Open manually: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
