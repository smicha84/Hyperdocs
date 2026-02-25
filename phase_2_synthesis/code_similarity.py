#!/usr/bin/env python3
"""
Code Similarity Engine — Import Shim
=====================================

This module re-exports from the canonical implementation at
phase_0_prep/code_similarity.py, which has structured logging.

The full-scan engine, FileFingerprint class, comparison functions,
and pattern classification are all defined there. This shim exists
so that existing imports like:

    from phase_2_synthesis.code_similarity import FileFingerprint

continue to work without maintaining a 500+ line duplicate.
"""

import sys
from pathlib import Path

# Ensure the repo root is on the path for the phase_0_prep import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phase_0_prep.code_similarity import (
    FileFingerprint,
    overlap_ratio,
    containment_ratio,
    compare_pair,
    classify_pattern,
    scan_directory,
    main,
)

__all__ = [
    "FileFingerprint",
    "overlap_ratio",
    "containment_ratio",
    "compare_pair",
    "classify_pattern",
    "scan_directory",
    "main",
]

if __name__ == "__main__":
    main()
