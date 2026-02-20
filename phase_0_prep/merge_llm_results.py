#!/usr/bin/env python3
"""
Phase 0 LLM Results Merger
============================

Merges per-pass LLM output files into enriched_session.json, producing
enriched_session_v2.json with the combined Python + LLM analysis.

Each message gets an `llm_behavior` key with structured results from
all 4 passes. Messages not analyzed by any pass get `llm_behavior: null`.

Usage:
    python3 merge_llm_results.py --session session_0012ebed
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── Path setup ────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from config import OUTPUT_DIR as DEFAULT_OUTPUT_DIR

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompts import PASS_CONFIGS


def find_session_dir(session_name: str) -> Optional[Path]:
    """Find the output directory for a session."""
    for base in [
        DEFAULT_OUTPUT_DIR,
        Path.home() / "PERMANENT_HYPERDOCS" / "sessions",
    ]:
        candidate = base / session_name
        if candidate.exists() and (candidate / "enriched_session.json").exists():
            return candidate
        if not session_name.startswith("session_"):
            candidate = base / f"session_{session_name}"
            if candidate.exists() and (candidate / "enriched_session.json").exists():
                return candidate
    return None


def load_pass_results(session_dir: Path, pass_num: int) -> Optional[Dict]:
    """Load results from a specific pass output file."""
    config = PASS_CONFIGS[pass_num]
    path = session_dir / config["output_file"]
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def build_index_lookup(pass_data: Optional[Dict]) -> Dict[int, Dict]:
    """Build a message-index → result lookup from pass output."""
    if not pass_data:
        return {}
    results = pass_data.get("results", [])
    lookup = {}
    for result in results:
        idx = result.get("index")
        if idx is not None:
            lookup[idx] = result
    return lookup


def merge_into_message(msg: Dict, p1: Optional[Dict], p2: Optional[Dict],
                       p3: Optional[Dict], p4: Optional[Dict]) -> Optional[Dict]:
    """Merge results from all 4 passes into an llm_behavior dict for one message.

    Returns None if no LLM pass analyzed this message.
    """
    if not any([p1, p2, p3, p4]):
        return None

    llm_behavior = {}

    # Pass 1: Content-referential + assumption subtypes
    if p1:
        llm_behavior["content_referential"] = p1.get("content_referential")
        llm_behavior["content_referential_reason"] = p1.get("content_referential_reason")
        llm_behavior["content_referential_confidence"] = p1.get(
            "content_referential_confidence",
            0.9 if p1.get("content_referential") is not None else None
        )
        llm_behavior["assumption_subtypes"] = {
            "code": p1.get("code_assumption", False),
            "format": p1.get("format_assumption", False),
            "direction": p1.get("direction_assumption", False),
            "scope": p1.get("scope_assumption", False),
        }
        llm_behavior["assumption_details"] = p1.get("assumption_details")
        llm_behavior["pass1_model"] = PASS_CONFIGS[1]["model"]

    # Pass 2: Silent decisions + unverified claims + overconfidence
    if p2:
        llm_behavior["silent_decisions"] = p2.get("silent_decisions", [])
        llm_behavior["unverified_claims"] = p2.get("unverified_claims", [])
        llm_behavior["overconfident"] = p2.get("overconfident", False)
        llm_behavior["overconfidence_detail"] = p2.get("overconfidence_detail")
        llm_behavior["pass2_model"] = PASS_CONFIGS[2]["model"]

    # Pass 3: Intent assumption (3-class)
    if p3:
        # Merge into assumption_subtypes
        if "assumption_subtypes" not in llm_behavior:
            llm_behavior["assumption_subtypes"] = {}
        llm_behavior["assumption_subtypes"]["intent"] = p3.get("intent_assumption", "uncertain")
        llm_behavior["intent_reasoning"] = p3.get("reasoning")

    # Pass 4: Importance score
    if p4:
        llm_behavior["importance_score"] = p4.get("importance")
        llm_behavior["importance_reason"] = p4.get("reason")

    return llm_behavior


def merge_session(session_dir: Path, write_output: bool = True) -> Dict:
    """Merge all LLM pass results into enriched_session_v2.json.

    Args:
        session_dir: Path to session output directory
        write_output: If True, write the merged file to disk

    Returns:
        Dict with merge statistics
    """
    # Load enriched session
    enriched_path = session_dir / "enriched_session.json"
    with open(enriched_path) as f:
        data = json.load(f)

    messages = data.get("messages", [])
    session_id = data.get("session_id", "unknown")

    print(f"\nMerging LLM results for session {session_id}")
    print(f"  Messages: {len(messages)}")

    # Load all pass results
    pass_results = {}
    pass_lookups = {}
    for pass_num in [1, 2, 3, 4]:
        result = load_pass_results(session_dir, pass_num)
        pass_results[pass_num] = result
        pass_lookups[pass_num] = build_index_lookup(result)
        if result:
            print(f"  Pass {pass_num}: {result.get('results_count', 0)} results "
                  f"({result.get('model', 'unknown')})")
        else:
            print(f"  Pass {pass_num}: not found")

    # Merge into messages
    merged_count = 0
    null_count = 0

    for msg in messages:
        idx = msg.get("index")
        p1 = pass_lookups[1].get(idx)
        p2 = pass_lookups[2].get(idx)
        p3 = pass_lookups[3].get(idx)
        p4 = pass_lookups[4].get(idx)

        llm_behavior = merge_into_message(msg, p1, p2, p3, p4)
        msg["llm_behavior"] = llm_behavior

        if llm_behavior:
            merged_count += 1
        else:
            null_count += 1

    # Add merge metadata
    data["llm_merge_metadata"] = {
        "merged_at": datetime.now(timezone.utc).isoformat(),
        "passes_available": [p for p in [1, 2, 3, 4] if pass_results[p]],
        "messages_with_llm_data": merged_count,
        "messages_without_llm_data": null_count,
        "total_cost": sum(
            (pass_results[p] or {}).get("total_usage", {}).get("cost", 0.0)
            for p in [1, 2, 3, 4]
        ),
    }

    # Write output
    if write_output:
        output_path = session_dir / "enriched_session_v2.json"
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"\n  Output: {output_path.name} ({size_mb:.1f} MB)")

    stats = {
        "session_id": session_id,
        "total_messages": len(messages),
        "messages_with_llm_data": merged_count,
        "messages_without_llm_data": null_count,
        "passes_merged": data["llm_merge_metadata"]["passes_available"],
        "total_cost": data["llm_merge_metadata"]["total_cost"],
    }

    print(f"  Merged: {merged_count} messages with LLM data, {null_count} without")
    return stats


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Merge LLM pass results into enriched_session_v2.json"
    )
    parser.add_argument("--session", required=True,
                       help="Session directory name (e.g., session_0012ebed)")

    args = parser.parse_args()

    session_dir = find_session_dir(args.session)
    if not session_dir:
        print(f"ERROR: Session not found: {args.session}")
        sys.exit(1)

    merge_session(session_dir)


if __name__ == "__main__":
    main()
