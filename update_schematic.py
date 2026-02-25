#!/usr/bin/env python3
"""
Auto-scan the pipeline codebase and update the manifest embedded in
hyperdocs-pipeline-schematic.html.

Run this after making pipeline changes. The HTML "Update Schematic"
button uses the embedded manifest as the source of truth for Opus.

Usage:
    python3 update_schematic.py          # scan codebase, update manifest in HTML
    python3 update_schematic.py --check  # just check if manifest is stale
"""
import ast
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
HTML_FILE = REPO / "hyperdocs-pipeline-schematic.html"

# Pipeline directories to scan
PHASE_DIRS = {
    "phase_0_prep": "Phase 0: Deterministic Prep",
    "phase_1_extraction": "Phase 1: Extraction",
    "phase_2_synthesis": "Phase 2: Synthesis",
    "phase_3_hyperdoc_writing": "Phase 3: Evidence Collection + Dossiers",
    "phase_4a_aggregation": "Phase 4a: Cross-Session Aggregation",
    "phase_4_insertion": "Phase 4b: Hyperdoc Writing + Insertion",
    "phase_4_hyperdoc_writing": "Phase 4b: Hyperdoc Writing (alt)",
    "tools": "Tools",
}

# Key pipeline scripts (the ones that appear in the schematic)
KEY_SCRIPTS = [
    "phase_0_prep/enrich_session.py",
    "phase_0_prep/prepare_agent_data.py",
    "phase_0_prep/opus_classifier.py",
    "phase_0_prep/build_opus_messages.py",
    "phase_1_extraction/opus_phase1.py",
    "phase_2_synthesis/backfill_phase2.py",
    "phase_2_synthesis/file_genealogy.py",
    "phase_2_synthesis/code_similarity.py",
    "phase_3_hyperdoc_writing/collect_file_evidence.py",
    "phase_3_hyperdoc_writing/generate_dossiers.py",
    "phase_3_hyperdoc_writing/generate_viewer.py",
    "phase_4a_aggregation/aggregate_dossiers.py",
    "phase_4_insertion/insert_hyperdocs_v2.py",
    "phase_4_insertion/hyperdoc_layers.py",
    "tools/run_pipeline.py",
]


def get_script_hash():
    """Compute a hash of all key pipeline scripts' contents."""
    h = hashlib.sha256()
    for script in sorted(KEY_SCRIPTS):
        path = REPO / script
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def extract_docstring(path):
    """Extract the first line of a Python file's module docstring."""
    try:
        tree = ast.parse(path.read_text())
        ds = ast.get_docstring(tree)
        if ds:
            return ds.split('\n')[0].strip()
    except (SyntaxError, UnicodeDecodeError):
        pass
    return ""


def scan_imports_and_outputs(path):
    """Quick scan of a script for JSON output filenames and key imports."""
    text = path.read_text()
    # Find JSON filenames written by this script
    outputs = set()
    for m in re.finditer(r'["\'](\w[\w_-]*\.json)["\']', text):
        fname = m.group(1)
        if any(kw in text[max(0, m.start()-80):m.start()] for kw in ['open(', 'write', 'dump', 'OUT_DIR', 'session_dir']):
            outputs.add(fname)
    return sorted(outputs)


def generate_manifest():
    """Generate a pipeline manifest from the actual codebase."""
    now = datetime.now(timezone.utc).strftime("%b %d, %Y %I:%M %p UTC")
    code_hash = get_script_hash()

    lines = [f"HYPERDOCS PIPELINE — AUTO-SCANNED STATE ({now})", f"Code hash: {code_hash}", ""]

    for script in KEY_SCRIPTS:
        path = REPO / script
        if path.exists():
            doc = extract_docstring(path)
            outputs = scan_imports_and_outputs(path)
            phase_dir = script.split('/')[0]
            phase_name = PHASE_DIRS.get(phase_dir, phase_dir)
            lines.append(f"  {script}")
            if doc:
                lines.append(f"    Docstring: {doc}")
            if outputs:
                lines.append(f"    Outputs: {', '.join(outputs)}")
        else:
            lines.append(f"  {script} [NOT FOUND]")

    return '\n'.join(lines), code_hash


def read_current_hash():
    """Read the MANIFEST_HASH from the HTML file."""
    if not HTML_FILE.exists():
        return None
    text = HTML_FILE.read_text()
    m = re.search(r'MANIFEST_HASH:\s*(\S+)', text)
    return m.group(1) if m else None


def update_html_manifest(manifest_text, code_hash):
    """Replace the PIPELINE_MANIFEST and MANIFEST_HASH in the HTML file."""
    html = HTML_FILE.read_text()

    # Update the hash
    html = re.sub(
        r'(MANIFEST_HASH:\s*)\S+',
        f'\\g<1>{code_hash}',
        html
    )

    # Update the manifest string (between backtick delimiters)
    # The manifest is: const PIPELINE_MANIFEST = `...`;
    pattern = r"(const PIPELINE_MANIFEST = `)([\s\S]*?)(`;)"
    replacement = f"\\g<1>{manifest_text}\\g<3>"
    html = re.sub(pattern, replacement, html)

    HTML_FILE.write_text(html)


def main():
    check_only = '--check' in sys.argv

    current_hash = read_current_hash()
    new_hash = get_script_hash()

    if check_only:
        if current_hash == new_hash:
            print(f"Manifest is current (hash: {current_hash})")
            sys.exit(0)
        else:
            print(f"Manifest is STALE (embedded: {current_hash}, code: {new_hash})")
            print("Run: python3 update_schematic.py")
            sys.exit(1)

    manifest_text, code_hash = generate_manifest()

    if current_hash == code_hash:
        print(f"No changes detected (hash: {code_hash}). Manifest is current.")
        return

    update_html_manifest(manifest_text, code_hash)
    print(f"Updated manifest in {HTML_FILE.name}")
    print(f"  Old hash: {current_hash}")
    print(f"  New hash: {code_hash}")
    print(f"\nOpen the HTML and click 'Update Schematic' to regenerate the diagram.")


if __name__ == "__main__":
    main()
