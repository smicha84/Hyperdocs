#!/usr/bin/env python3
"""
Code Similarity Engine — Full Scan Mode
========================================

Compares ALL Python files against ALL others. No pre-filtering.
No genealogy input. Completely unobstructed.

Signals computed per file:
  1. Function names (AST)
  2. Class names and method signatures (AST)
  3. Import fingerprint (what modules are imported)
  4. Constants and string literals
  5. Filename stem words

Pair comparison:
  - Function overlap ratio
  - Import overlap ratio
  - Text similarity (difflib, only for pairs with initial signal)
  - Containment check (is file B a subset of file A?)

Pattern classification:
  - dead_copy:         >90% text similarity
  - evolution_pair:    60-90% text similarity
  - function_clone:    >50% shared function names
  - partial_extraction: B's functions are a subset of A's (>80% containment)
  - template_variant:  same structure, <30% text similarity (parameterized)
  - import_twin:       >70% shared imports, <30% function overlap
  - name_only:         filename stems overlap but code doesn't (<5% any signal)
  - interface_mismatch: files call each other's names but signatures diverge

Input:  Directory of Python files
Output: code_similarity_index.json

Usage:
    python3 code_similarity.py [--source-dir PATH] [--output PATH] [--threshold 0.1]
"""

import ast
import json
import os
import re
import sys
import difflib
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from itertools import combinations


# ── File Fingerprint ──────────────────────────────────────────────────────

class FileFingerprint:
    """All extractable signals from a single Python file."""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.stem = path.stem
        self.stem_words = set(re.split(r'[_\-.]', self.stem.lower())) - {'py', ''}

        self.functions: set = set()       # top-level function names
        self.classes: set = set()         # class names
        self.methods: dict = {}           # {class_name: set of method names}
        self.all_callable: set = set()    # functions + all methods (flat)
        self.imports: set = set()         # imported module names
        self.from_imports: dict = {}      # {module: set of names}
        self.constants: set = set()       # ALL_CAPS names
        self.string_literals: set = set() # unique string constants >10 chars
        self.lines: list = []             # raw lines (for text comparison)
        self.line_count: int = 0
        self.parse_error: bool = False

        self._extract(path)

    def _extract(self, path: Path):
        """Parse file and extract all signals."""
        try:
            source = path.read_text(encoding='utf-8', errors='replace')
        except (IOError, OSError):
            self.parse_error = True
            return

        self.lines = source.splitlines()
        self.line_count = len(self.lines)

        # Strip hyperdoc comment blocks for comparison (they'd create false matches)
        clean_lines = []
        in_hyperdoc = False
        for line in self.lines:
            if '#HYPERDOC:' in line or 'HYPERDOC - Auto-generated' in line:
                in_hyperdoc = True
            elif in_hyperdoc and (line.strip() == '"""' or line.strip() == "'''" or (not line.startswith('#') and line.strip() != '')):
                in_hyperdoc = False
            if not in_hyperdoc:
                clean_lines.append(line)
        self.clean_source = '\n'.join(clean_lines)

        # AST parsing
        try:
            tree = ast.parse(source)
        except SyntaxError:
            self.parse_error = True
            # Still extract what we can with regex
            self._regex_fallback(source)
            return

        for node in ast.walk(tree):
            # Functions
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                # Check if it's top-level or a method
                self.all_callable.add(node.name)
                # We'll handle methods separately below

            # Classes
            if isinstance(node, ast.ClassDef):
                self.classes.add(node.name)
                methods = set()
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.add(item.name)
                        self.all_callable.add(item.name)
                self.methods[node.name] = methods

            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.add(alias.name.split('.')[0])

            if isinstance(node, ast.ImportFrom):
                if node.module:
                    mod = node.module.split('.')[0]
                    self.imports.add(mod)
                    names = set()
                    for alias in (node.names or []):
                        if alias.name != '*':
                            names.add(alias.name)
                    if names:
                        self.from_imports[node.module] = names

            # Constants (ALL_CAPS assignments)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper() and len(target.id) > 2:
                        self.constants.add(target.id)

            # String literals >10 chars
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 10:
                # Normalize and deduplicate
                val = node.value.strip()[:100]
                if val and not val.startswith('#'):
                    self.string_literals.add(val)

        # Top-level functions (not methods)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.add(node.name)

    def _regex_fallback(self, source: str):
        """Extract basic signals when AST fails."""
        for match in re.finditer(r'^def\s+(\w+)', source, re.MULTILINE):
            self.functions.add(match.group(1))
            self.all_callable.add(match.group(1))
        for match in re.finditer(r'^class\s+(\w+)', source, re.MULTILINE):
            self.classes.add(match.group(1))
        for match in re.finditer(r'^import\s+(\w+)', source, re.MULTILINE):
            self.imports.add(match.group(1))
        for match in re.finditer(r'^from\s+(\w+)', source, re.MULTILINE):
            self.imports.add(match.group(1))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "stem_words": sorted(self.stem_words),
            "functions": sorted(self.functions),
            "classes": sorted(self.classes),
            "methods": {k: sorted(v) for k, v in self.methods.items()},
            "imports": sorted(self.imports),
            "constants": sorted(self.constants),
            "line_count": self.line_count,
            "parse_error": self.parse_error,
        }


# ── Pair Comparison ───────────────────────────────────────────────────────

def overlap_ratio(set_a: set, set_b: set) -> float:
    """Jaccard-style overlap: |intersection| / |union|."""
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def containment_ratio(subset: set, superset: set) -> float:
    """What fraction of subset is contained in superset?"""
    if not subset:
        return 0.0
    return len(subset & superset) / len(subset)


def compare_pair(fp_a: FileFingerprint, fp_b: FileFingerprint, text_threshold: float = 0.1) -> dict:
    """Compare two file fingerprints and return similarity signals."""

    # ── Set-based comparisons (fast) ──
    func_overlap = overlap_ratio(fp_a.functions, fp_b.functions)
    callable_overlap = overlap_ratio(fp_a.all_callable, fp_b.all_callable)
    class_overlap = overlap_ratio(fp_a.classes, fp_b.classes)
    import_overlap = overlap_ratio(fp_a.imports, fp_b.imports)
    constant_overlap = overlap_ratio(fp_a.constants, fp_b.constants)
    name_overlap = overlap_ratio(fp_a.stem_words, fp_b.stem_words)

    # Containment (is one a subset of the other?)
    if fp_a.functions and fp_b.functions:
        a_in_b = containment_ratio(fp_a.functions, fp_b.functions)
        b_in_a = containment_ratio(fp_b.functions, fp_a.functions)
    else:
        a_in_b = b_in_a = 0.0

    # Shared function names (useful for interface mismatch detection)
    shared_functions = sorted(fp_a.all_callable & fp_b.all_callable - {'__init__', '__str__', '__repr__', 'main', 'to_dict'})

    # ── Composite signal score (determines if we do expensive text comparison) ──
    signal_score = (
        func_overlap * 3 +
        callable_overlap * 2 +
        class_overlap * 2 +
        import_overlap * 1 +
        constant_overlap * 1 +
        name_overlap * 1
    )

    # ── Text similarity (expensive — only if initial signals warrant it) ──
    # For large codebases, this is the bottleneck. Only compare text when
    # there's meaningful signal from the fast fingerprint comparison.
    text_similarity = 0.0
    if signal_score >= text_threshold or name_overlap > 0.3:
        # Use clean source (hyperdoc comments stripped)
        src_a = fp_a.clean_source
        src_b = fp_b.clean_source
        seq = difflib.SequenceMatcher(None, src_a, src_b, autojunk=True)
        text_similarity = seq.ratio()

    return {
        "func_overlap": round(func_overlap, 3),
        "callable_overlap": round(callable_overlap, 3),
        "class_overlap": round(class_overlap, 3),
        "import_overlap": round(import_overlap, 3),
        "constant_overlap": round(constant_overlap, 3),
        "name_overlap": round(name_overlap, 3),
        "text_similarity": round(text_similarity, 3),
        "containment_a_in_b": round(a_in_b, 3),
        "containment_b_in_a": round(b_in_a, 3),
        "shared_functions": shared_functions,
        "signal_score": round(signal_score, 3),
    }


# ── Pattern Classification ────────────────────────────────────────────────

def classify_pattern(signals: dict) -> list:
    """Classify the similarity pattern type(s) for a pair."""
    patterns = []

    text = signals["text_similarity"]
    func = signals["func_overlap"]
    callable_ = signals["callable_overlap"]
    imports = signals["import_overlap"]
    name = signals["name_overlap"]
    a_in_b = signals["containment_a_in_b"]
    b_in_a = signals["containment_b_in_a"]

    # Dead copy — near-identical files
    if text > 0.90:
        patterns.append("dead_copy")

    # Evolution pair — high text similarity, same concept different version
    elif text > 0.60:
        patterns.append("evolution_pair")

    # Function clone — shared function names regardless of text
    if func > 0.50 and text < 0.90:
        patterns.append("function_clone")

    # Partial extraction — one file's functions are a subset of the other's
    if (a_in_b > 0.80 or b_in_a > 0.80) and text < 0.60:
        patterns.append("partial_extraction")

    # Template variant — similar structure but different content
    if callable_ > 0.40 and text < 0.30:
        patterns.append("template_variant")

    # Import twin — same dependencies, different code
    if imports > 0.70 and func < 0.30:
        patterns.append("import_twin")

    # Name only — filenames overlap but code doesn't
    if name > 0.30 and text < 0.05 and func < 0.05:
        patterns.append("name_only")

    # Interface mismatch — files share callable names but low text similarity
    # (they're trying to do similar things but implementations have diverged)
    if len(signals.get("shared_functions", [])) >= 3 and text < 0.30:
        patterns.append("interface_mismatch")

    # Structural sibling — moderate overlap across multiple signals, no single dominant
    if not patterns and callable_ > 0.15 and imports > 0.30 and text < 0.40:
        patterns.append("structural_sibling")

    # Shared ecosystem — same imports, moderate callable overlap (co-evolved files)
    if not patterns and imports > 0.40 and callable_ > 0.10:
        patterns.append("shared_ecosystem")

    return patterns


# ── Main Engine ───────────────────────────────────────────────────────────

def scan_directory(source_dir: Path, threshold: float = 0.05) -> dict:
    """Full scan: compare all Python files against all others."""

    # ── Step 1: Discover and fingerprint all files ──
    py_files = sorted(source_dir.glob("*.py"))
    print(f"Found {len(py_files)} Python files in {source_dir}")

    fingerprints = {}
    errors = []
    for i, path in enumerate(py_files):
        fp = FileFingerprint(path)
        fingerprints[path.name] = fp
        if fp.parse_error:
            errors.append(path.name)
        if (i + 1) % 50 == 0:
            print(f"  Fingerprinted {i + 1}/{len(py_files)}...")

    print(f"Fingerprinted {len(fingerprints)} files ({len(errors)} with parse errors)")

    # ── Step 2: Compare all pairs ──
    names = sorted(fingerprints.keys())
    total_pairs = len(names) * (len(names) - 1) // 2
    print(f"Comparing {total_pairs:,} pairs...")

    matches = []
    text_comparisons = 0
    pair_count = 0

    for i, name_a in enumerate(names):
        fp_a = fingerprints[name_a]
        for name_b in names[i + 1:]:
            fp_b = fingerprints[name_b]
            pair_count += 1

            signals = compare_pair(fp_a, fp_b)

            if signals["text_similarity"] > 0:
                text_comparisons += 1

            # Only keep pairs with some signal
            if signals["signal_score"] > threshold or signals["text_similarity"] > 0.05 or signals["name_overlap"] > 0.3:
                patterns = classify_pattern(signals)
                if patterns or signals["signal_score"] > 0.5:
                    matches.append({
                        "file_a": name_a,
                        "file_b": name_b,
                        "signals": signals,
                        "patterns": patterns,
                    })

        if (i + 1) % 50 == 0:
            print(f"  Compared file {i + 1}/{len(names)} ({pair_count:,}/{total_pairs:,} pairs, {len(matches)} matches)...")

    print(f"Completed: {total_pairs:,} pairs, {text_comparisons:,} text comparisons, {len(matches)} non-trivial matches")

    # ── Step 3: Aggregate per-file statistics ──
    file_stats = {}
    for name in names:
        fp = fingerprints[name]
        related = [m for m in matches if m["file_a"] == name or m["file_b"] == name]
        partner_patterns = defaultdict(list)
        for m in related:
            partner = m["file_b"] if m["file_a"] == name else m["file_a"]
            for p in m["patterns"]:
                partner_patterns[p].append(partner)

        file_stats[name] = {
            "fingerprint": fp.to_dict(),
            "total_matches": len(related),
            "pattern_summary": {p: len(files) for p, files in partner_patterns.items()},
            "strongest_match": max(
                [(m["signals"]["signal_score"], m["file_b"] if m["file_a"] == name else m["file_a"])
                 for m in related], default=(0, None)
            ),
            "isolation_score": round(1.0 - min(1.0, len(related) / 10), 2),
        }

    # ── Step 4: Pattern distribution ──
    pattern_counts = defaultdict(int)
    for m in matches:
        for p in m["patterns"]:
            pattern_counts[p] += 1

    # ── Step 5: Build output ──
    return {
        "generated_at": datetime.now().isoformat(),
        "generator": "code_similarity.py — Full Scan Mode",
        "source_directory": str(source_dir),
        "total_files": len(fingerprints),
        "total_pairs_compared": total_pairs,
        "text_comparisons_performed": text_comparisons,
        "non_trivial_matches": len(matches),
        "files_with_parse_errors": errors,
        "pattern_distribution": dict(sorted(pattern_counts.items(), key=lambda x: -x[1])),
        "matches": sorted(matches, key=lambda m: -m["signals"]["signal_score"]),
        "file_stats": file_stats,
    }


def main():
    parser = argparse.ArgumentParser(description="Code Similarity Engine — Full Scan")
    parser.add_argument("--source-dir", type=str, help="Directory of Python files to compare")
    parser.add_argument("--output", type=str, help="Output JSON path")
    parser.add_argument("--threshold", type=float, default=0.05, help="Minimum signal score to keep a pair")
    args = parser.parse_args()

    # Default source directory
    if args.source_dir:
        source_dir = Path(args.source_dir)
    else:
        # Default: enhanced files from the pipeline
        source_dir = (
            Path.home()
            / "PycharmProjects"
            / "pythonProject ARXIV4"
            / "pythonProjectartifact"
            / ".claude"
            / "hooks"
            / "hyperdoc"
            / "hyperdocs_3"
            / "output"
            / "enhanced_files_archive"
        )

    if not source_dir.exists():
        print(f"ERROR: Source directory not found: {source_dir}")
        sys.exit(1)

    # Default output
    if args.output:
        output_path = Path(args.output)
    else:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from config import INDEXES_DIR
            output_path = INDEXES_DIR / "code_similarity_index.json"
        except ImportError:
            output_path = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "code_similarity_index.json"

    print("=" * 60)
    print("CODE SIMILARITY ENGINE — Full Scan")
    print("=" * 60)
    print(f"Source:    {source_dir}")
    print(f"Output:    {output_path}")
    print(f"Threshold: {args.threshold}")
    print()

    results = scan_directory(source_dir, threshold=args.threshold)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    file_size = output_path.stat().st_size / 1024

    # Print summary
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Files scanned:     {results['total_files']}")
    print(f"Pairs compared:    {results['total_pairs_compared']:,}")
    print(f"Text comparisons:  {results['text_comparisons_performed']:,}")
    print(f"Non-trivial:       {results['non_trivial_matches']}")
    print(f"Parse errors:      {len(results['files_with_parse_errors'])}")
    print()
    print("Pattern distribution:")
    for pattern, count in results['pattern_distribution'].items():
        print(f"  {pattern:25s} {count:4d}")
    print()

    # Top 10 strongest matches
    print("Top 10 strongest matches:")
    for m in results['matches'][:10]:
        score = m['signals']['signal_score']
        text = m['signals']['text_similarity']
        patterns = ', '.join(m['patterns']) if m['patterns'] else 'unclassified'
        print(f"  {score:5.2f} | text:{text:.2f} | {m['file_a']} ↔ {m['file_b']}")
        print(f"        | {patterns}")

    # Most isolated files (potential disconnects)
    isolated = sorted(
        results['file_stats'].items(),
        key=lambda x: -x[1]['isolation_score']
    )[:10]
    print()
    print("Most isolated files (potential disconnects):")
    for name, stats in isolated:
        print(f"  isolation:{stats['isolation_score']:.2f} | matches:{stats['total_matches']} | {name}")

    print(f"\nOutput: {output_path} ({file_size:.0f} KB)")


if __name__ == "__main__":
    main()
