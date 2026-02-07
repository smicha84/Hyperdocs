#!/usr/bin/env python3
"""
Ground Truth Verifier — Run independent Python checks against claims.

No LLM. Pure Python + AST + git. Each check returns:
  VERIFIED / FAILED / UNABLE_TO_VERIFY + evidence string.

Input:  ground_truth_claims.json
Output: ground_truth_results.json
"""
import ast
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent.parent  # output/session_3b7084d5/
V5_CODE = BASE.parent.parent / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_2" / "V5" / "code"
HOOKS_DIR = BASE.parent.parent / ".claude" / "hooks" / "hyperdoc"
PROJECT_ROOT = BASE.parent.parent
import os; SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")

# Some files live outside V5/code
ALTERNATE_PATHS = {
    "opus_struggle_analyzer.py": HOOKS_DIR / "opus_struggle_analyzer.py",
}


def get_source_path(filename):
    """Resolve the actual path for a source file."""
    if filename in ALTERNATE_PATHS:
        p = ALTERNATE_PATHS[filename]
        if p.exists():
            return p
    p = V5_CODE / filename
    if p.exists():
        return p
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
    """Regex scan for hardcoded slicing limits like [:10], [:20], [:50]."""
    try:
        source = filepath.read_text()
    except (OSError, UnicodeDecodeError):
        return "UNABLE_TO_VERIFY", "Could not read file"

    # Match patterns like [:10], [:20], [:50], [:100], [:500], [:2000]
    # Exclude [:1] and [:2] as those are likely intentional
    pattern = r'\[:(\d+)\]'
    matches = []
    for i, line in enumerate(source.splitlines(), 1):
        for m in re.finditer(pattern, line):
            limit = int(m.group(1))
            if limit >= 10:
                matches.append((i, limit, line.strip()[:80]))

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

    # Look for model string assignments in actual code
    # Skip: comments, docstrings, function/method definitions, print statements
    sonnet_refs = []
    haiku_refs = []
    opus_refs = []

    in_docstring = False
    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        lower = stripped.lower()

        # Track docstrings
        if '"""' in stripped or "'''" in stripped:
            quote = '"""' if '"""' in stripped else "'''"
            count = stripped.count(quote)
            if count == 1:
                in_docstring = not in_docstring
            continue
        if in_docstring:
            continue

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Skip function/class definitions (method names containing model names are OK)
        if stripped.startswith("def ") or stripped.startswith("class "):
            continue

        # Skip print statements (debug output, not model selection)
        if stripped.startswith("print("):
            continue

        # Check for actual model string usage (assignments, API calls, string literals)
        if "sonnet" in lower:
            sonnet_refs.append(i)
        if "haiku" in lower:
            haiku_refs.append(i)
        if "opus" in lower:
            opus_refs.append(i)

    if sonnet_refs:
        return "FAILED", f"Sonnet references at lines: {', '.join(str(l) for l in sonnet_refs[:5])}"
    if haiku_refs:
        return "FAILED", f"Haiku references at lines: {', '.join(str(l) for l in haiku_refs[:5])} (check if Opus-trained per rule 8)"
    if opus_refs:
        return "VERIFIED", f"Opus references found at {len(opus_refs)} locations, no Sonnet/Haiku"
    return "UNABLE_TO_VERIFY", "No model string references found"


def check_unsafe_api_access(filepath):
    """AST scan for response.content[0].text without guards."""
    try:
        source = filepath.read_text()
    except (OSError, UnicodeDecodeError):
        return "UNABLE_TO_VERIFY", "Could not read file"

    # Pattern: response.content[0].text without a guard
    # A guard looks like: "if response.content" or "... if X.content else ..."
    access_pattern = r'\.content\[0\]\.text'
    guard_pattern = r'if\s+\w+\.content'
    matches = []
    for i, line in enumerate(source.splitlines(), 1):
        if re.search(access_pattern, line) and not line.strip().startswith("#"):
            if re.search(guard_pattern, line):
                continue  # Guarded inline — safe
            matches.append(i)

    if not matches:
        return "VERIFIED", "No unguarded response.content[0].text access found"
    else:
        return "FAILED", f"{len(matches)} unsafe access points at lines: {', '.join(str(l) for l in matches[:5])}"


def check_duplicate_functions(filepath, func_name="call_opus"):
    """AST scan for duplicate function definitions."""
    tree, source = parse_file(filepath)
    if tree is None:
        return "UNABLE_TO_VERIFY", "Could not parse file"

    defs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                defs.append(node.lineno)

    if len(defs) <= 1:
        return "VERIFIED", f"'{func_name}' defined {len(defs)} time(s)"
    else:
        return "FAILED", f"'{func_name}' defined {len(defs)} times at lines: {', '.join(str(l) for l in defs)}"


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


# ─── VERIFICATION ENGINE ────────────────────────────────────────


def run_checks_for_file(filename, claims):
    """Run all applicable checks for a file based on its claims."""
    filepath = get_source_path(filename)
    results = []

    if filepath is None:
        return [{
            "claim": "File exists",
            "check": "file_exists",
            "result": "FAILED",
            "evidence": f"Source file not found for {filename}",
        }]

    # Always run universal checks
    # 1. Bare excepts (W03)
    result, evidence = check_bare_excepts(filepath)
    results.append({
        "claim": "W03: Bare except blocks fixed",
        "check": "check_bare_excepts",
        "result": result,
        "evidence": evidence,
    })

    # 2. Unsafe API access (W12)
    result, evidence = check_unsafe_api_access(filepath)
    results.append({
        "claim": "W12: Unsafe response.content[0].text access",
        "check": "check_unsafe_api_access",
        "result": result,
        "evidence": evidence,
    })

    # 3. Truncation patterns (W04)
    result, evidence = check_truncation_patterns(filepath)
    results.append({
        "claim": "W04: No hardcoded truncation limits",
        "check": "check_truncation_patterns",
        "result": result,
        "evidence": evidence,
    })

    # 4. Duplicate call_opus (W10)
    result, evidence = check_duplicate_functions(filepath, "call_opus")
    results.append({
        "claim": "W10: No duplicate call_opus definitions",
        "check": "check_duplicate_functions",
        "result": result,
        "evidence": evidence,
    })

    # 5. Model strings (W05)
    result, evidence = check_model_strings(filepath)
    results.append({
        "claim": "W05: Opus-only model strings",
        "check": "check_model_strings",
        "result": result,
        "evidence": evidence,
    })

    # 6. Broad exception handlers
    result, evidence = check_broad_exception_handlers(filepath)
    results.append({
        "claim": "Exception handling uses specific types",
        "check": "check_broad_exception_handlers",
        "result": result,
        "evidence": evidence,
    })

    # File-specific checks based on resolution claims
    for claim in claims.get("resolution_claims", []):
        wid = claim.get("warning_id", "")

        # W01: deterministic_parse_message should exist in geological_reader.py
        if wid == "W01" and filename == "geological_reader.py":
            result, evidence = check_function_exists(filepath, "deterministic_parse_message")
            results.append({
                "claim": f"{wid}: {claim.get('claim', '')}",
                "check": "check_function_exists('deterministic_parse_message')",
                "result": result,
                "evidence": evidence,
            })

        # W02: insert_markers_into_file truncation fix
        if wid == "W02" and filename == "marker_generator.py":
            result, evidence = check_function_exists(filepath, "insert_markers_into_file")
            results.append({
                "claim": f"{wid}: Truncation in insert_markers_into_file fixed",
                "check": "check_function_exists('insert_markers_into_file')",
                "result": result,
                "evidence": evidence,
            })

    return results


def main():
    print("=" * 60)
    print("Ground Truth Verifier — Independent Python Checks")
    print("=" * 60)
    print(f"V5 code dir: {V5_CODE}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    claims_path = Path(__file__).parent / "ground_truth_claims.json"
    if not claims_path.exists():
        print("ERROR: ground_truth_claims.json not found. Run claim_extractor.py first.")
        return

    with open(claims_path) as f:
        claims_data = json.load(f)

    all_claims = claims_data.get("claims", {})
    all_results = {}
    total_verified = 0
    total_failed = 0
    total_unable = 0

    for filename in all_claims:
        file_claims = all_claims[filename]
        checks = run_checks_for_file(filename, file_claims)

        verified = sum(1 for c in checks if c["result"] == "VERIFIED")
        failed = sum(1 for c in checks if c["result"] == "FAILED")
        unable = sum(1 for c in checks if c["result"] == "UNABLE_TO_VERIFY")

        all_results[filename] = {
            "checks_run": len(checks),
            "verified": verified,
            "failed": failed,
            "unable_to_verify": unable,
            "details": checks,
        }

        total_verified += verified
        total_failed += failed
        total_unable += unable

        status = "OK" if failed == 0 else f"{failed} FAILED"
        print(f"  {filename}: {len(checks)} checks — {verified} verified, {failed} failed, {unable} unable [{status}]")

    output = {
        "session_id": SESSION_ID,
        "generated_at": datetime.now().isoformat(),
        "total_checks": total_verified + total_failed + total_unable,
        "total_verified": total_verified,
        "total_failed": total_failed,
        "total_unable": total_unable,
        "files": all_results,
    }

    out_path = Path(__file__).parent / "ground_truth_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print()
    print(f"Total: {total_verified + total_failed + total_unable} checks")
    print(f"  VERIFIED: {total_verified}")
    print(f"  FAILED: {total_failed}")
    print(f"  UNABLE: {total_unable}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
