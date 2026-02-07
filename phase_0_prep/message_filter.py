#!/usr/bin/env python3
"""
Message Filter for Hyperdocs Pipeline
=====================================

Filters messages BEFORE sending to Opus to reduce API costs.
Uses cheap Python heuristics to identify high-value messages.

FILTERING TIERS:
  Tier 1 (SKIP):     <50 chars, no keywords, no pasted content → SKIP
  Tier 2 (BASIC):    50-100 chars with keywords → Basic extraction only
  Tier 3 (STANDARD): 100-500 chars OR has pasted content → Full 6-thread
  Tier 4 (PRIORITY): 500+ chars OR multiple struggle signals → Deep analysis

This reduces Opus calls by ~40-60% while preserving important context.
"""

import json
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
from datetime import datetime


# ============================================================================
# KEYWORD SIGNAL DEFINITIONS
# ============================================================================

# Frustration / Pain signals (weight: 3)
FRUSTRATION_KEYWORDS = [
    "frustrat", "annoying", "annoyed", "hate", "stupid", "ridiculous",
    "can't believe", "doesn't make sense", "makes no sense", "terrible",
    "awful", "horrible", "worst", "ugh", "argh", "wtf", "what the",
]

# Error / Failure signals (weight: 3)
FAILURE_KEYWORDS = [
    "error", "fail", "broken", "crash", "exception", "traceback",
    "doesn't work", "not working", "won't work", "bug", "issue",
    "wrong", "incorrect", "invalid", "unexpected",
]

# Direction change signals (weight: 2)
PIVOT_KEYWORDS = [
    "actually", "wait", "stop", "no,", "forget", "instead", "nevermind",
    "scratch that", "change of plans", "different approach", "pivot",
    "let's try", "what if we", "on second thought",
]

# Architecture / Design signals (weight: 2)
ARCHITECTURE_KEYWORDS = [
    "design", "architect", "structure", "pattern", "approach", "strategy",
    "system", "framework", "module", "component", "interface", "api",
    "should we", "how should", "best way", "trade-off", "tradeoff",
]

# Code artifact signals (weight: 1)
CODE_KEYWORDS = [
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json",
    "function", "class", "import", "export", "def ", "async ", "await ",
    "file", "folder", "directory", "module", "package",
]

# Success / Breakthrough signals (weight: 2)
BREAKTHROUGH_KEYWORDS = [
    "perfect", "works", "finally", "got it", "success", "great job",
    "exactly what", "that's it", "brilliant", "excellent", "amazing",
    "love it", "this is great", "well done",
]

# Plan / Strategy signals (weight: 2)
PLAN_KEYWORDS = [
    "plan", "phase", "step", "milestone", "goal", "objective",
    "roadmap", "timeline", "priority", "first we", "then we", "next we",
]


@dataclass
class FilterResult:
    """Result of message filtering."""
    tier: int  # 1=skip, 2=basic, 3=standard, 4=priority
    tier_name: str
    score: int  # Importance score (higher = more important)
    signals: List[str]  # Which signals triggered
    should_process: bool
    explanation: str


class MessageFilter:
    """
    Filters messages based on length, keywords, and context signals.

    Usage:
        filter = MessageFilter()
        result = filter.classify(message_text, has_pasted_content=False)
        if result.should_process:
            # Send to Opus
    """

    def __init__(self, min_length: int = 50, verbose: bool = False):
        self.min_length = min_length
        self.verbose = verbose

        # Compile keyword patterns for efficiency
        self._patterns = {
            'frustration': self._compile_patterns(FRUSTRATION_KEYWORDS),
            'failure': self._compile_patterns(FAILURE_KEYWORDS),
            'pivot': self._compile_patterns(PIVOT_KEYWORDS),
            'architecture': self._compile_patterns(ARCHITECTURE_KEYWORDS),
            'code': self._compile_patterns(CODE_KEYWORDS),
            'breakthrough': self._compile_patterns(BREAKTHROUGH_KEYWORDS),
            'plan': self._compile_patterns(PLAN_KEYWORDS),
        }

        # Weights for each signal type
        self._weights = {
            'frustration': 3,
            'failure': 3,
            'pivot': 2,
            'architecture': 2,
            'code': 1,
            'breakthrough': 2,
            'plan': 2,
        }

        # Stats tracking
        self.stats = {
            'total': 0,
            'tier_1_skipped': 0,
            'tier_2_basic': 0,
            'tier_3_standard': 0,
            'tier_4_priority': 0,
        }

    def _compile_patterns(self, keywords: List[str]) -> re.Pattern:
        """Compile keywords into a single regex pattern for efficiency."""
        escaped = [re.escape(kw) for kw in keywords]
        pattern = '|'.join(escaped)
        return re.compile(pattern, re.IGNORECASE)

    def _find_signals(self, text: str) -> Tuple[List[str], int]:
        """Find all signal keywords in text and calculate score."""
        signals = []
        score = 0
        text_lower = text.lower()

        for signal_type, pattern in self._patterns.items():
            matches = pattern.findall(text_lower)
            if matches:
                signals.append(f"{signal_type}:{len(matches)}")
                score += self._weights[signal_type] * len(matches)

        return signals, score

    def classify(self, text: str, has_pasted_content: bool = False) -> FilterResult:
        """
        Classify a message into a processing tier.

        Args:
            text: The message text
            has_pasted_content: Whether the message has associated pasted content

        Returns:
            FilterResult with tier, score, and processing recommendation
        """
        self.stats['total'] += 1
        length = len(text)
        signals, score = self._find_signals(text)

        # Add bonus for pasted content (likely code/errors)
        if has_pasted_content:
            signals.append("pasted_content")
            score += 5

        # Add length bonus for detailed messages
        if length >= 500:
            score += 3
        elif length >= 200:
            score += 1

        # ================================================================
        # TIER CLASSIFICATION
        # ================================================================

        # Tier 1: SKIP - Very short with no signals
        if length < self.min_length and score == 0 and not has_pasted_content:
            self.stats['tier_1_skipped'] += 1
            return FilterResult(
                tier=1,
                tier_name="SKIP",
                score=score,
                signals=signals,
                should_process=False,
                explanation=f"Too short ({length} chars) with no importance signals"
            )

        # Tier 4: PRIORITY - Long messages OR high signal density
        if length >= 500 or score >= 6 or (has_pasted_content and score >= 3):
            self.stats['tier_4_priority'] += 1
            return FilterResult(
                tier=4,
                tier_name="PRIORITY",
                score=score,
                signals=signals,
                should_process=True,
                explanation=f"High value: {length} chars, score={score}, signals={signals}"
            )

        # Tier 3: STANDARD - Medium length OR moderate signals
        if length >= 100 or score >= 3 or has_pasted_content:
            self.stats['tier_3_standard'] += 1
            return FilterResult(
                tier=3,
                tier_name="STANDARD",
                score=score,
                signals=signals,
                should_process=True,
                explanation=f"Standard value: {length} chars, score={score}"
            )

        # Tier 2: BASIC - Short but has some signals
        if score >= 1:
            self.stats['tier_2_basic'] += 1
            return FilterResult(
                tier=2,
                tier_name="BASIC",
                score=score,
                signals=signals,
                should_process=True,  # Process but with simpler extraction
                explanation=f"Basic value: {length} chars with signals {signals}"
            )

        # Default: SKIP
        self.stats['tier_1_skipped'] += 1
        return FilterResult(
            tier=1,
            tier_name="SKIP",
            score=score,
            signals=signals,
            should_process=False,
            explanation=f"Low value: {length} chars, no significant signals"
        )

    def get_stats_summary(self) -> str:
        """Get a summary of filtering statistics."""
        total = self.stats['total']
        if total == 0:
            return "No messages processed yet"

        skipped = self.stats['tier_1_skipped']
        processed = total - skipped

        return f"""
=== MESSAGE FILTER STATS ===
Total messages:    {total:,}
Skipped (Tier 1):  {skipped:,} ({skipped/total*100:.1f}%)
Processed:         {processed:,} ({processed/total*100:.1f}%)

Breakdown:
  Tier 2 (Basic):    {self.stats['tier_2_basic']:,}
  Tier 3 (Standard): {self.stats['tier_3_standard']:,}
  Tier 4 (Priority): {self.stats['tier_4_priority']:,}

Estimated Opus cost savings: ~{skipped/total*100:.0f}%
"""


def profile_archive(archive_path: str, sample_files: int = 10) -> Dict[str, Any]:
    """
    Profile an archive to estimate filtering effectiveness.

    Args:
        archive_path: Path to PERMANENT_ARCHIVE directory
        sample_files: Number of files to sample

    Returns:
        Dictionary with profiling results
    """
    archive_dir = Path(archive_path)
    files = sorted(archive_dir.glob("*.jsonl"))[:sample_files]

    filter = MessageFilter()
    tier_examples = {1: [], 2: [], 3: [], 4: []}

    for f in files:
        with open(f, 'r', errors='ignore') as fh:
            for line in fh:
                try:
                    msg = json.loads(line.strip())
                    display = msg.get('display', '')
                    has_pasted = bool(msg.get('pastedContents'))

                    result = filter.classify(display, has_pasted)

                    # Keep a few examples of each tier
                    if len(tier_examples[result.tier]) < 3:
                        tier_examples[result.tier].append({
                            'text': display,
                            'tier': result.tier_name,
                            'score': result.score,
                            'signals': result.signals,
                        })
                except (ValueError, KeyError, TypeError):
                    pass

    return {
        'stats': filter.stats,
        'summary': filter.get_stats_summary(),
        'examples': tier_examples,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("MESSAGE FILTER - Profiling PERMANENT_ARCHIVE")
    print("=" * 60)

    archive_path = "" + os.getenv("HYPERDOCS_ARCHIVE_PATH", "") + ""
    results = profile_archive(archive_path, sample_files=10)

    print(results['summary'])

    print("\n=== EXAMPLE MESSAGES BY TIER ===")
    for tier in [1, 2, 3, 4]:
        tier_name = {1: "SKIP", 2: "BASIC", 3: "STANDARD", 4: "PRIORITY"}[tier]
        print(f"\n--- Tier {tier} ({tier_name}) ---")
        for ex in results['examples'].get(tier, []):
            print(f"  Score: {ex['score']}, Signals: {ex['signals']}")
            print(f"  Text: {ex['text']}")
            print()
