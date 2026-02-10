#!/usr/bin/env python3
"""
App Level Manager — Maturity Classification for Codebases
==========================================================

Checks what Hyperdocs outputs exist for a project and classifies
its maturity level from 0 (DORMANT) to 6 (LIVE).

Apps in standby mode can't jump to real-time — they need to be
leveled up. Each level builds on the previous.

Levels:
  0: DORMANT     — No data. Fresh project.
  1: SCANNED     — Code similarity index exists. File structure known.
  2: ENRICHED    — Phase 0 complete on >= 1 session. Metadata exists.
  3: ANALYZED    — Phase 1-2 complete. Idea graph + genealogy exist.
  4: DOCUMENTED  — Phase 3-4 complete. Hyperdocs written.
  5: VERIFIED    — Phase 5 complete. Ground truth checked.
  6: LIVE        — Real-time mode active. All layers operating.

Usage:
    # CLI:
    python3 app_level_manager.py                      # Check level of default project
    python3 app_level_manager.py --project /path      # Check specific project
    python3 app_level_manager.py --requirements 4     # What's needed for Level 4

    # As library:
    from realtime.app_level_manager import AppLevelManager
    mgr = AppLevelManager()
    level = mgr.get_level()
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime


LEVELS = {
    0: {"name": "DORMANT", "description": "No data. Fresh project."},
    1: {"name": "SCANNED", "description": "Code similarity index exists. File structure known."},
    2: {"name": "ENRICHED", "description": "Phase 0 complete on >= 1 session. Metadata exists."},
    3: {"name": "ANALYZED", "description": "Phase 1-2 complete. Idea graph + genealogy exist."},
    4: {"name": "DOCUMENTED", "description": "Phase 3-4 complete. Hyperdocs written."},
    5: {"name": "VERIFIED", "description": "Phase 5 complete. Ground truth checked."},
    6: {"name": "LIVE", "description": "Real-time mode active. All layers operating."},
}


class AppLevelManager:
    """Assesses and manages project maturity levels."""

    def __init__(self, hyperdocs_dir: str = None):
        if hyperdocs_dir:
            self.base = Path(hyperdocs_dir)
        else:
            self.base = Path.home() / "PERMANENT_HYPERDOCS"

        self.sessions_dir = self.base / "sessions"
        self.indexes_dir = self.base / "indexes"
        self.hyperdocs_dir = self.base / "hyperdocs"
        self.realtime_dir = self.base / "realtime"

    def _check_similarity_index(self) -> dict:
        """Check if code similarity index exists."""
        index_path = self.indexes_dir / "code_similarity_index.json"
        cache_path = self.indexes_dir / "fingerprint_cache.json"
        return {
            "exists": index_path.exists() or cache_path.exists(),
            "index_size": index_path.stat().st_size if index_path.exists() else 0,
            "cache_size": cache_path.stat().st_size if cache_path.exists() else 0,
        }

    def _check_sessions(self) -> dict:
        """Check session processing state."""
        if not self.sessions_dir.exists():
            return {"total": 0, "with_phase0": 0, "with_phase1": 0, "with_phase2": 0, "with_phase3": 0}

        sessions = [d for d in self.sessions_dir.iterdir() if d.is_dir() and d.name.startswith("session_")]
        total = len(sessions)

        phase0 = sum(1 for s in sessions if (s / "enriched_session.json").exists())
        phase1 = sum(1 for s in sessions if (s / "thread_extractions.json").exists())
        phase2 = sum(1 for s in sessions if (s / "idea_graph.json").exists())
        phase3 = sum(1 for s in sessions if (s / "file_dossiers.json").exists())

        return {
            "total": total,
            "with_phase0": phase0,
            "with_phase1": phase1,
            "with_phase2": phase2,
            "with_phase3": phase3,
        }

    def _check_hyperdocs(self) -> dict:
        """Check hyperdoc outputs."""
        if not self.hyperdocs_dir.exists():
            return {"count": 0, "total_size": 0}

        files = list(self.hyperdocs_dir.glob("*_hyperdoc.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {"count": len(files), "total_size": total_size}

    def _check_ground_truth(self) -> dict:
        """Check if ground truth verification has been run."""
        # Look for ground truth outputs in any session
        if not self.sessions_dir.exists():
            return {"verified": False, "sessions_with_gt": 0}

        gt_sessions = 0
        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            if (session_dir / "ground_truth_verification.json").exists():
                gt_sessions += 1

        return {"verified": gt_sessions > 0, "sessions_with_gt": gt_sessions}

    def _check_realtime(self) -> dict:
        """Check if real-time hooks are active."""
        buffer_exists = False
        state_files = 0

        if self.realtime_dir.exists():
            state_files = len(list(self.realtime_dir.glob("session_*_state.json")))

        # Check for realtime buffer in any output location
        for candidate in [
            self.base / "realtime_buffer.jsonl",
            Path.home() / "PERMANENT_HYPERDOCS" / "realtime_buffer.jsonl",
        ]:
            if candidate.exists():
                buffer_exists = True
                break

        return {
            "buffer_exists": buffer_exists,
            "active_sessions": state_files,
            "hooks_installed": False,  # Would need to check settings.json
        }

    def get_level(self) -> dict:
        """Assess the current maturity level."""
        similarity = self._check_similarity_index()
        sessions = self._check_sessions()
        hyperdocs = self._check_hyperdocs()
        ground_truth = self._check_ground_truth()
        realtime = self._check_realtime()

        # Determine level
        level = 0

        if similarity["exists"]:
            level = 1

        if sessions["with_phase0"] > 0 and level >= 1:
            level = 2

        if sessions["with_phase2"] > 0 and level >= 2:
            level = 3

        if hyperdocs["count"] > 0 and sessions["with_phase3"] > 0 and level >= 3:
            level = 4

        if ground_truth["verified"] and level >= 4:
            level = 5

        if realtime["hooks_installed"] and realtime["buffer_exists"] and level >= 5:
            level = 6

        return {
            "level": level,
            "level_name": LEVELS[level]["name"],
            "level_description": LEVELS[level]["description"],
            "assessed_at": datetime.now().isoformat(),
            "evidence": {
                "similarity": similarity,
                "sessions": sessions,
                "hyperdocs": hyperdocs,
                "ground_truth": ground_truth,
                "realtime": realtime,
            },
            "all_levels": {str(k): v for k, v in LEVELS.items()},
        }

    def get_requirements(self, target_level: int) -> list:
        """Return what needs to happen to reach target level."""
        current = self.get_level()
        current_level = current["level"]
        evidence = current["evidence"]

        if target_level <= current_level:
            return [f"Already at Level {current_level} ({LEVELS[current_level]['name']}). Target {target_level} is not higher."]

        requirements = []

        if target_level >= 1 and current_level < 1:
            if not evidence["similarity"]["exists"]:
                requirements.append("Run code similarity full scan: python3 phase_2_synthesis/code_similarity.py")

        if target_level >= 2 and current_level < 2:
            if evidence["sessions"]["with_phase0"] == 0:
                requirements.append("Run Phase 0 on at least 1 session: python3 phase_0_prep/deterministic_prep.py")

        if target_level >= 3 and current_level < 3:
            if evidence["sessions"]["with_phase2"] == 0:
                requirements.append("Run Phase 1 (4 parallel agents) + Phase 2 (idea graph + synthesis) on at least 1 session")

        if target_level >= 4 and current_level < 4:
            if evidence["hyperdocs"]["count"] == 0:
                requirements.append("Run Phase 3-4 (file dossiers + hyperdoc writing)")
            if evidence["sessions"]["with_phase3"] == 0:
                requirements.append("Run Phase 3 (file mapper) on at least 1 session")

        if target_level >= 5 and current_level < 5:
            if not evidence["ground_truth"]["verified"]:
                requirements.append("Run Phase 5 (ground truth verification): python3 phase_5_ground_truth/claim_extractor.py + ground_truth_verifier.py + gap_reporter.py")

        if target_level >= 6 and current_level < 6:
            requirements.append("Install real-time hooks: python3 install.py")
            requirements.append("Activate real-time capture (requires hook wiring in settings.json)")

        return requirements


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="App Level Manager")
    parser.add_argument("--project", type=str, help="Path to PERMANENT_HYPERDOCS directory")
    parser.add_argument("--requirements", type=int, help="Show requirements for target level")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    mgr = AppLevelManager(hyperdocs_dir=args.project)
    result = mgr.get_level()

    if args.requirements is not None:
        reqs = mgr.get_requirements(args.requirements)
        print(f"Current: Level {result['level']} ({result['level_name']})")
        print(f"Target:  Level {args.requirements} ({LEVELS.get(args.requirements, {}).get('name', '?')})")
        print()
        if reqs:
            print("Requirements:")
            for r in reqs:
                print(f"  - {r}")
        else:
            print("No additional requirements.")
        return

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    # Pretty print
    level = result["level"]
    ev = result["evidence"]

    print("=" * 60)
    print(f"  APP LEVEL: {level} — {result['level_name']}")
    print(f"  {result['level_description']}")
    print("=" * 60)
    print()

    # Level progress bar
    for i in range(7):
        marker = "█" if i <= level else "░"
        name = LEVELS[i]["name"]
        status = " ← YOU ARE HERE" if i == level else ""
        print(f"  {marker} Level {i}: {name}{status}")

    print()
    print("Evidence:")
    print(f"  Similarity index:  {'YES' if ev['similarity']['exists'] else 'NO'} ({ev['similarity']['index_size'] // 1024}KB index, {ev['similarity']['cache_size'] // 1024}KB cache)")
    print(f"  Sessions total:    {ev['sessions']['total']}")
    print(f"    Phase 0:         {ev['sessions']['with_phase0']}")
    print(f"    Phase 1:         {ev['sessions']['with_phase1']}")
    print(f"    Phase 2:         {ev['sessions']['with_phase2']}")
    print(f"    Phase 3:         {ev['sessions']['with_phase3']}")
    print(f"  Hyperdocs:         {ev['hyperdocs']['count']} ({ev['hyperdocs']['total_size'] // 1024}KB)")
    print(f"  Ground truth:      {'VERIFIED' if ev['ground_truth']['verified'] else 'NOT RUN'} ({ev['ground_truth']['sessions_with_gt']} sessions)")
    print(f"  Real-time:         {'ACTIVE' if ev['realtime']['buffer_exists'] else 'INACTIVE'} ({ev['realtime']['active_sessions']} session states)")


if __name__ == "__main__":
    main()
