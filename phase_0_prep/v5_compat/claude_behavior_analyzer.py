#!/usr/bin/env python3
"""
Claude Behavior Analyzer
========================

Analyzes Claude's responses and thinking to detect:
1. Context damage indicators (confusion, forgetting, contradictions)
2. Decision framework patterns (rushing, assumptions, overconfidence)
3. Pre-emergency behavior patterns (what Claude does before user explodes)

This helps understand WHY Claude enters "crazy mode" and how to prevent it.

The goal: Catch context damage BEFORE it cascades into emergency interventions.
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

# Import Claude session reader
try:
    from .claude_session_reader import ClaudeSessionReader, ClaudeSession, ClaudeMessage
except ImportError:
    from claude_session_reader import ClaudeSessionReader, ClaudeSession, ClaudeMessage


@dataclass
class ClaudeBehaviorFlags:
    """Flags indicating Claude's mental state in a response."""
    # Context damage indicators
    shows_confusion: bool = False          # "I'm not sure", "Let me re-read"
    admits_forgetting: bool = False        # "I forgot", "I missed"
    makes_assumptions: bool = False        # "I'll assume", "probably means"
    contradicts_self: bool = False         # Detected contradiction
    apologizes: bool = False               # "I apologize", "sorry"

    # Decision quality indicators
    rushes_to_solution: bool = False       # Short thinking, jumps to action
    overconfident: bool = False            # "definitely", "will work", "should fix"
    ignores_context: bool = False          # Doesn't reference recent messages
    repeats_failed_approach: bool = False  # Trying same thing again

    # Recovery attempts
    tries_to_clarify: bool = False         # "To clarify", "Let me understand"
    asks_questions: bool = False           # Actually asks user for clarification
    acknowledges_mistake: bool = False     # Explicitly says "I made a mistake"

    # Severity score (0-10)
    context_damage_score: int = 0

    def to_dict(self) -> Dict:
        return {
            "confusion": self.shows_confusion,
            "forgetting": self.admits_forgetting,
            "assumptions": self.makes_assumptions,
            "contradicts": self.contradicts_self,
            "apologizes": self.apologizes,
            "rushing": self.rushes_to_solution,
            "overconfident": self.overconfident,
            "ignores_context": self.ignores_context,
            "repeats_failed": self.repeats_failed_approach,
            "clarifying": self.tries_to_clarify,
            "asks_questions": self.asks_questions,
            "acknowledges_mistake": self.acknowledges_mistake,
            "damage_score": self.context_damage_score
        }

    def to_compact(self) -> str:
        """Compact string for Opus pre-prompt."""
        flags = []
        if self.shows_confusion:
            flags.append("CONFUSED")
        if self.admits_forgetting:
            flags.append("FORGOT")
        if self.makes_assumptions:
            flags.append("ASSUMING")
        if self.apologizes:
            flags.append("APOLOGIZING")
        if self.rushes_to_solution:
            flags.append("RUSHING")
        if self.overconfident:
            flags.append("OVERCONFIDENT")
        if self.acknowledges_mistake:
            flags.append("ADMITS_ERROR")

        if flags:
            return f"CLAUDE_STATE:[{','.join(flags)}] damage:{self.context_damage_score}/10"
        return ""


class ClaudeBehaviorAnalyzer:
    """
    Analyzes Claude's responses and thinking to detect context damage
    and decision framework patterns.
    """

    # Patterns to detect in Claude's thinking/response
    PATTERNS = {
        # Confusion indicators
        'confusion': re.compile(
            r"i'?m not sure|"
            r"let me re-?read|"
            r"i need to understand|"
            r"this is confusing|"
            r"unclear what|"
            r"trying to figure out|"
            r"not entirely clear",
            re.IGNORECASE
        ),

        # Forgetting/missing things
        'forgetting': re.compile(
            r"i forgot|"
            r"i missed|"
            r"i overlooked|"
            r"i didn'?t notice|"
            r"i should have|"
            r"i failed to|"
            r"i neglected",
            re.IGNORECASE
        ),

        # Making assumptions
        'assumptions': re.compile(
            r"i'?ll assume|"
            r"i'?m assuming|"
            r"probably means|"
            r"i think they want|"
            r"most likely|"
            r"i believe this means|"
            r"my guess is",
            re.IGNORECASE
        ),

        # Apologies
        'apologies': re.compile(
            r"i apologize|"
            r"i'?m sorry|"
            r"my apologies|"
            r"sorry for|"
            r"apologies for|"
            r"i regret",
            re.IGNORECASE
        ),

        # Overconfidence
        'overconfidence': re.compile(
            r"this will definitely|"
            r"this should fix|"
            r"this will work|"
            r"guaranteed to|"
            r"certainly|"
            r"absolutely|"
            r"no doubt|"
            r"i'?m confident",
            re.IGNORECASE
        ),

        # Clarification attempts
        'clarifying': re.compile(
            r"to clarify|"
            r"let me understand|"
            r"to make sure i understand|"
            r"if i understand correctly|"
            r"just to confirm",
            re.IGNORECASE
        ),

        # Acknowledging mistakes
        'acknowledges_mistake': re.compile(
            r"i made a mistake|"
            r"that was wrong|"
            r"i was incorrect|"
            r"my error|"
            r"i messed up|"
            r"that'?s my fault|"
            r"i should not have",
            re.IGNORECASE
        ),
    }

    def analyze_message(self, msg: ClaudeMessage, prev_messages: List[ClaudeMessage] = None) -> ClaudeBehaviorFlags:
        """
        Analyze a single Claude message for behavior patterns.

        Args:
            msg: The Claude message to analyze
            prev_messages: Previous messages for context (to detect contradictions, repeats)

        Returns:
            ClaudeBehaviorFlags with detected patterns
        """
        if msg.role != "assistant":
            return ClaudeBehaviorFlags()

        flags = ClaudeBehaviorFlags()

        # Analyze thinking content (most revealing)
        thinking = msg.thinking or ""
        content = msg.content or ""
        full_text = thinking + " " + content

        # Check each pattern
        flags.shows_confusion = bool(self.PATTERNS['confusion'].search(full_text))
        flags.admits_forgetting = bool(self.PATTERNS['forgetting'].search(full_text))
        flags.makes_assumptions = bool(self.PATTERNS['assumptions'].search(full_text))
        flags.apologizes = bool(self.PATTERNS['apologies'].search(full_text))
        flags.overconfident = bool(self.PATTERNS['overconfidence'].search(full_text))
        flags.tries_to_clarify = bool(self.PATTERNS['clarifying'].search(full_text))
        flags.acknowledges_mistake = bool(self.PATTERNS['acknowledges_mistake'].search(full_text))

        # Check for rushing (short thinking relative to task complexity)
        if thinking:
            # Very short thinking might indicate rushing
            if len(thinking) < 100 and len(content) > 500:
                flags.rushes_to_solution = True

        # Check for asking questions (good behavior!)
        if '?' in content and any(q in content.lower() for q in ['would you', 'should i', 'do you want', 'which', 'what would you']):
            flags.asks_questions = True

        # Calculate context damage score
        damage = 0
        if flags.shows_confusion:
            damage += 2
        if flags.admits_forgetting:
            damage += 3
        if flags.makes_assumptions:
            damage += 1
        if flags.apologizes:
            damage += 2
        if flags.rushes_to_solution:
            damage += 2
        if flags.overconfident and not flags.tries_to_clarify:
            damage += 2

        # Positive behaviors reduce damage
        if flags.tries_to_clarify:
            damage -= 1
        if flags.asks_questions:
            damage -= 1
        if flags.acknowledges_mistake:
            damage -= 1  # Acknowledging is good, even if there was a mistake

        flags.context_damage_score = max(0, min(10, damage))

        return flags

    def analyze_session(self, session: ClaudeSession) -> Dict[str, Any]:
        """
        Analyze an entire session for Claude behavior patterns.

        Returns:
            Summary of behavior patterns across the session
        """
        total_messages = 0
        total_damage_score = 0
        pattern_counts = defaultdict(int)
        high_damage_indices = []

        assistant_messages = [m for m in session.messages if m.role == "assistant"]

        for i, msg in enumerate(assistant_messages):
            flags = self.analyze_message(msg)
            total_messages += 1
            total_damage_score += flags.context_damage_score

            if flags.shows_confusion:
                pattern_counts['confusion'] += 1
            if flags.admits_forgetting:
                pattern_counts['forgetting'] += 1
            if flags.makes_assumptions:
                pattern_counts['assumptions'] += 1
            if flags.apologizes:
                pattern_counts['apologies'] += 1
            if flags.overconfident:
                pattern_counts['overconfident'] += 1
            if flags.rushes_to_solution:
                pattern_counts['rushing'] += 1
            if flags.asks_questions:
                pattern_counts['asks_questions'] += 1
            if flags.acknowledges_mistake:
                pattern_counts['acknowledges_mistake'] += 1

            # Track high damage moments
            if flags.context_damage_score >= 5:
                high_damage_indices.append(i)

        avg_damage = total_damage_score / total_messages if total_messages > 0 else 0

        return {
            "total_assistant_messages": total_messages,
            "avg_damage_score": round(avg_damage, 2),
            "high_damage_moments": len(high_damage_indices),
            "pattern_counts": dict(pattern_counts),
            "most_common_issues": sorted(pattern_counts.items(), key=lambda x: -x[1])[:5]
        }

    def get_pre_emergency_behavior(
        self,
        session: ClaudeSession,
        emergency_indices: List[int],
        window: int = 3
    ) -> Dict[str, Any]:
        """
        Analyze Claude's behavior in the messages BEFORE emergency interventions.
        This reveals what Claude was doing right before things went wrong.

        Args:
            session: The session to analyze
            emergency_indices: Indices of user emergency intervention messages
            window: How many Claude messages to look at before each emergency

        Returns:
            Analysis of pre-emergency Claude behavior patterns
        """
        pre_emergency_patterns = defaultdict(int)
        pre_emergency_damage_scores = []

        assistant_messages = [(i, m) for i, m in enumerate(session.messages) if m.role == "assistant"]

        for emergency_idx in emergency_indices:
            # Find Claude messages in the window before this emergency
            relevant_messages = [
                (i, m) for i, m in assistant_messages
                if m.timestamp and session.messages[emergency_idx].timestamp
                and m.timestamp < session.messages[emergency_idx].timestamp
            ][-window:]

            for _, msg in relevant_messages:
                flags = self.analyze_message(msg)
                pre_emergency_damage_scores.append(flags.context_damage_score)

                if flags.shows_confusion:
                    pre_emergency_patterns['confusion'] += 1
                if flags.admits_forgetting:
                    pre_emergency_patterns['forgetting'] += 1
                if flags.makes_assumptions:
                    pre_emergency_patterns['assumptions'] += 1
                if flags.apologizes:
                    pre_emergency_patterns['apologies'] += 1
                if flags.overconfident:
                    pre_emergency_patterns['overconfident'] += 1
                if flags.rushes_to_solution:
                    pre_emergency_patterns['rushing'] += 1

        avg_pre_damage = sum(pre_emergency_damage_scores) / len(pre_emergency_damage_scores) if pre_emergency_damage_scores else 0

        return {
            "emergencies_analyzed": len(emergency_indices),
            "avg_pre_emergency_damage": round(avg_pre_damage, 2),
            "pre_emergency_patterns": dict(pre_emergency_patterns),
            "top_warning_signs": sorted(pre_emergency_patterns.items(), key=lambda x: -x[1])[:3]
        }


@dataclass
class PreventionAlert:
    """
    Alert generated when context damage risk is detected.
    Includes the sensing (what was detected) and tactics (what to do).
    """
    level: str  # "WATCH", "CAUTION", "WARNING", "CRITICAL"
    sensing: List[str]  # What was detected
    tactics: List[str]  # What Claude should do
    message_index: int
    damage_score: int

    def to_prompt_injection(self) -> str:
        """
        Generate text that can be injected into Claude's prompt
        to make it aware of the situation and recommended actions.
        """
        lines = [
            f"⚠️ PREVENTION ALERT [{self.level}] - Message #{self.message_index}",
            "",
            "SENSING (what's happening):",
        ]
        for s in self.sensing:
            lines.append(f"  • {s}")

        lines.append("")
        lines.append("TACTICS (what to do):")
        for t in self.tactics:
            lines.append(f"  → {t}")

        return "\n".join(lines)


class PreventionSystem:
    """
    Combines user frustration metadata + Claude behavior analysis
    to generate prevention alerts before context damage cascades.
    """

    # Tactics for different situations
    TACTICS = {
        'confusion': [
            "PAUSE - Re-read the last 3 user messages before responding",
            "ASK - Request clarification instead of assuming",
            "SUMMARIZE - State your understanding and ask if correct"
        ],
        'forgetting': [
            "REVIEW - Check what files/requirements were mentioned earlier",
            "CHECKPOINT - List what you remember and verify with user",
            "SLOW DOWN - Context is complex, take time to review"
        ],
        'assumptions': [
            "STOP ASSUMING - Ask the user directly",
            "VERIFY - State your assumption and ask if correct",
            "LIST OPTIONS - Present alternatives instead of choosing"
        ],
        'rushing': [
            "SLOW DOWN - Quality over speed",
            "THINK LONGER - Expand your reasoning before acting",
            "VERIFY - Check your solution before presenting"
        ],
        'overconfidence': [
            "HEDGE - Avoid certainty language (will/definitely/should)",
            "TEST - Verify your solution works before claiming success",
            "ACKNOWLEDGE LIMITS - State what you're not sure about"
        ],
        'user_frustration_rising': [
            "ACKNOWLEDGE - Recognize the user's frustration",
            "LISTEN - Focus on understanding, not defending",
            "SIMPLIFY - Break the problem into smaller steps"
        ],
        'emergency_imminent': [
            "FULL STOP - Do not proceed with current approach",
            "ASK - What specifically is wrong?",
            "OFFER RESET - Would you like to start fresh on this?"
        ]
    }

    def generate_alert(
        self,
        claude_flags: ClaudeBehaviorFlags,
        user_frustration_level: int = 0,  # 0-10 from metadata
        user_has_profanity: bool = False,
        user_exclamations: int = 0,
        message_index: int = 0
    ) -> Optional[PreventionAlert]:
        """
        Generate a prevention alert based on combined signals.

        Args:
            claude_flags: Claude's behavior flags for this message
            user_frustration_level: User frustration (0-10) from recent messages
            user_has_profanity: Did user use profanity recently?
            user_exclamations: Number of exclamations in recent user messages
            message_index: Current message index

        Returns:
            PreventionAlert if risk detected, None otherwise
        """
        sensing = []
        tactics = []
        total_risk = claude_flags.context_damage_score

        # Add user frustration to risk
        if user_frustration_level >= 5:
            total_risk += 3
            sensing.append(f"User frustration elevated ({user_frustration_level}/10)")
            tactics.extend(self.TACTICS['user_frustration_rising'])

        if user_has_profanity:
            total_risk += 2
            sensing.append("User using profanity (frustration signal)")

        if user_exclamations >= 5:
            total_risk += 2
            sensing.append(f"User exclamation count high ({user_exclamations})")

        # Add Claude behavior signals
        if claude_flags.shows_confusion:
            sensing.append("Claude showing confusion signals")
            tactics.extend(self.TACTICS['confusion'])

        if claude_flags.admits_forgetting:
            sensing.append("Claude forgetting/missing context")
            tactics.extend(self.TACTICS['forgetting'])

        if claude_flags.makes_assumptions:
            sensing.append("Claude making assumptions without verification")
            tactics.extend(self.TACTICS['assumptions'])

        if claude_flags.rushes_to_solution:
            sensing.append("Claude rushing (short thinking, quick action)")
            tactics.extend(self.TACTICS['rushing'])

        if claude_flags.overconfident:
            sensing.append("Claude overconfident (certainty language)")
            tactics.extend(self.TACTICS['overconfidence'])

        # Determine alert level
        if total_risk >= 8:
            level = "CRITICAL"
            sensing.insert(0, "⚠️ EMERGENCY IMMINENT - Multiple high-risk signals")
            tactics = self.TACTICS['emergency_imminent'] + tactics[:3]
        elif total_risk >= 5:
            level = "WARNING"
        elif total_risk >= 3:
            level = "CAUTION"
        elif total_risk >= 1:
            level = "WATCH"
        else:
            return None  # No alert needed

        # Deduplicate tactics
        tactics = list(dict.fromkeys(tactics))[:5]

        return PreventionAlert(
            level=level,
            sensing=sensing,
            tactics=tactics,
            message_index=message_index,
            damage_score=total_risk
        )


def main():
    """CLI for testing the behavior analyzer."""
    from pathlib import Path

    print("="*70)
    print("CLAUDE BEHAVIOR ANALYZER")
    print("="*70)

    reader = ClaudeSessionReader(verbose=False)
    analyzer = ClaudeBehaviorAnalyzer()

    project = '-Users-stefanmichaelcheck-PycharmProjects-pythonProject-ARXIV4-pythonProjectartifact'
    sessions = reader.load_project_sessions(project_name=project, limit=5)

    for session in list(sessions.values())[:2]:
        print(f"\nSession: {session.session_id[:16]}...")
        analysis = analyzer.analyze_session(session)

        print(f"  Assistant messages: {analysis['total_assistant_messages']}")
        print(f"  Avg damage score: {analysis['avg_damage_score']}/10")
        print(f"  High damage moments: {analysis['high_damage_moments']}")
        print(f"  Pattern counts: {analysis['pattern_counts']}")
        print(f"  Top issues: {analysis['most_common_issues']}")


if __name__ == "__main__":
    main()
