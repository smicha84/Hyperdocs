#!/usr/bin/env python3
"""
Claude Behavior Analyzer
========================

Analyzes Claude's responses and thinking to detect behavioral patterns
identified by the Idea Evolution Analysis (1,668 ideas across 216 sessions).

Detects 20 behaviors in 4 categories:

CONTEXT DAMAGE (original 7):
  1. confusion          — "I'm not sure", "let me re-read"
  2. forgetting         — "I forgot", "I missed"
  3. assumptions        — "I'll assume", "probably means"
  4. contradicts_self   — Says something that conflicts with a prior statement (H)
  5. apologizes         — "I apologize", "sorry"
  6. rushing            — Short thinking, jumps to action
  7. overconfident      — "definitely", "will work", "should fix"

IDEA EVOLUTION PATTERNS (new, from analysis):
  8. unsolicited_addition   — Adds features/defaults/fallbacks not requested (A)
  9. premature_completion   — "done", "complete", "finished" without evidence (B)
  10. batch_without_verify  — Creates/modifies multiple files without testing (C)
  11. silent_decision       — Sets values/defaults without presenting options (D)
  12. hollow_fulfillment    — Output structurally matches request but content is generic (E)
  13. unverified_claim      — States facts without showing evidence (F)
  14. scope_creep           — Expands beyond what was asked (G)
  15. repeats_failed        — Tries same approach that already failed (I)

RECOVERY BEHAVIORS (positive):
  16. tries_to_clarify      — "To clarify", "let me understand"
  17. asks_questions        — Actually asks user for clarification
  18. acknowledges_mistake  — "I made a mistake", "that was wrong"

META:
  19. ignores_context       — Doesn't reference recent messages
  20. user_upset_score     — How upsetting this message is (scored by user, no cap)

Evidence: Idea Evolution Analysis found 14.6% verification rate, 5.7:1 confidence-
evidence mismatch, 30:1 evolution-to-abandonment ratio, "Helpful Saboteur" pattern
across 8 sessions, and the "You Lied" pivot where 4 templates were presented as 33
custom visualizations.
"""

import os
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
    """Flags indicating Claude's behavioral state in a response."""
    # Context damage indicators (original)
    shows_confusion: bool = False
    admits_forgetting: bool = False
    makes_assumptions: bool = False
    contradicts_self: bool = False
    apologizes: bool = False
    rushes_to_solution: bool = False
    overconfident: bool = False
    ignores_context: bool = False
    repeats_failed_approach: bool = False

    # Idea Evolution patterns (new — from the analysis)
    unsolicited_addition: bool = False
    premature_completion: bool = False
    batch_without_verify: bool = False
    silent_decision: bool = False
    hollow_fulfillment: bool = False
    unverified_claim: bool = False
    scope_creep: bool = False

    # Recovery attempts (positive behaviors)
    tries_to_clarify: bool = False
    asks_questions: bool = False
    acknowledges_mistake: bool = False

    # User upset score — how upsetting this behavior would be (scored by user)
    # No cap. ignores_context alone scores 20. Multiple bad behaviors stack.
    user_upset_score: int = 0

    # Detail strings for flagged behaviors (what specifically was detected)
    details: Dict[str, str] = field(default_factory=dict)

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
            "unsolicited_addition": self.unsolicited_addition,
            "premature_completion": self.premature_completion,
            "batch_without_verify": self.batch_without_verify,
            "silent_decision": self.silent_decision,
            "hollow_fulfillment": self.hollow_fulfillment,
            "unverified_claim": self.unverified_claim,
            "scope_creep": self.scope_creep,
            "clarifying": self.tries_to_clarify,
            "asks_questions": self.asks_questions,
            "acknowledges_mistake": self.acknowledges_mistake,
            "user_upset_score": self.user_upset_score,
            "details": self.details,
        }

    def to_compact(self) -> str:
        """Compact string for Opus pre-prompt."""
        flags = []
        if self.shows_confusion: flags.append("CONFUSED")
        if self.admits_forgetting: flags.append("FORGOT")
        if self.makes_assumptions: flags.append("ASSUMING")
        if self.contradicts_self: flags.append("CONTRADICTS")
        if self.apologizes: flags.append("APOLOGIZING")
        if self.rushes_to_solution: flags.append("RUSHING")
        if self.overconfident: flags.append("OVERCONFIDENT")
        if self.repeats_failed_approach: flags.append("REPEATING_FAILURE")
        if self.unsolicited_addition: flags.append("UNSOLICITED_ADD")
        if self.premature_completion: flags.append("PREMATURE_DONE")
        if self.batch_without_verify: flags.append("BATCH_NO_VERIFY")
        if self.silent_decision: flags.append("SILENT_DECISION")
        if self.hollow_fulfillment: flags.append("HOLLOW")
        if self.unverified_claim: flags.append("UNVERIFIED_CLAIM")
        if self.scope_creep: flags.append("SCOPE_CREEP")
        if self.acknowledges_mistake: flags.append("ADMITS_ERROR")

        if flags:
            return f"CLAUDE_STATE:[{','.join(flags)}] upset_score:{self.user_upset_score}"
        return ""


class ClaudeBehaviorAnalyzer:
    """
    Analyzes Claude's responses and thinking to detect behavioral patterns.

    Uses all previous assistant messages as context (falls back to 10 if
    processing the full history causes pipeline performance issues).
    """

    # ── Regex patterns for text-based detection ──

    PATTERNS = {
        # Original patterns
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
        'apologies': re.compile(
            r"i apologize|"
            r"i'?m sorry|"
            r"my apologies|"
            r"sorry for|"
            r"apologies for|"
            r"i regret",
            re.IGNORECASE
        ),
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
        'clarifying': re.compile(
            r"to clarify|"
            r"let me understand|"
            r"to make sure i understand|"
            r"if i understand correctly|"
            r"just to confirm",
            re.IGNORECASE
        ),
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

        # New patterns — Idea Evolution behaviors

        # A: Unsolicited addition (Helpful Saboteur)
        'unsolicited_addition': re.compile(
            r"i'?(?:ll|ve)? also (?:added?|included?|created?)|"
            r"while i was at it|"
            r"i went ahead and|"
            r"i took the liberty|"
            r"as a bonus|"
            r"i also (?:added?|made|built|created|included)|"
            r"for good measure|"
            r"just in case|"
            r"as a safety net|"
            r"(?:added?|included?) (?:a )?fallback|"
            r"(?:added?|included?) (?:a )?default|"
            r"graceful(?:ly)? degrad|"
            r"opt(?:-|\s)?in behavior|"
            r"(?:added?|included?) error handling for .{0,30} edge case",
            re.IGNORECASE
        ),

        # B: Premature completion declaration
        'premature_completion': re.compile(
            r"\ball (?:done|set|complete|finished|fixed|resolved|working)\b|"
            r"\bfully (?:complete|implemented|working|functional)\b|"
            r"\beverything (?:is |looks? )?(?:good|great|working|done|fixed)\b|"
            r"\bthat'?s? (?:it|all|everything)\b.*(?:done|complete|finished)|"
            r"\bsuccessfully (?:completed?|implemented?|fixed)\b|"
            r"\bnothing (?:left|else|more) to (?:do|fix|change)\b",
            re.IGNORECASE
        ),

        # D: Silent decision (choosing values/approaches without presenting options)
        'silent_decision': re.compile(
            r"i(?:'ll| will) (?:set|use|pick|choose|go with|default to)|"
            r"(?:setting|using) (?:a )?(?:default|limit|threshold|cap|budget|timeout) (?:of|to|at)|"
            r"i'?(?:ll|ve) (?:configured?|set) (?:it|this|the) to|"
            r"for (?:safety|efficiency|performance|simplicity),? i|"
            r"to be safe,? i|"
            r"a reasonable (?:default|value|limit|threshold)|"
            r"i(?:'ll| will) cap (?:it|this|the)|"
            r"(?:truncat|limit|cap)(?:e|ing|ed) (?:it|this|the|content|output|data) (?:at|to)",
            re.IGNORECASE
        ),

        # F: Unverified claim
        'unverified_claim': re.compile(
            r"this (?:should|will) (?:work|fix|resolve|handle)|"
            r"(?:all|every) tests? (?:pass|passing|passed)|"
            r"(?:verified|confirmed) (?:that )?(?:it|this|everything) works|"
            r"no (?:issues?|errors?|problems?) (?:found|detected|remaining)|"
            r"100% (?:complete|correct|working|coverage)|"
            r"everything (?:checks? out|looks? (?:good|correct))",
            re.IGNORECASE
        ),

        # G: Scope creep
        'scope_creep': re.compile(
            r"while (?:i'?m|we'?re) at it|"
            r"(?:might|may) as well|"
            r"since (?:i'?m|we'?re) (?:already|here)|"
            r"i (?:also|additionally) (?:noticed|saw|found) (?:that )?we (?:should|could)|"
            r"bonus:? |"
            r"as an? (?:extra|additional|bonus)|"
            r"i'?(?:ll|ve) (?:also|additionally) (?:refactored?|cleaned? up|reorganized?|improved?)",
            re.IGNORECASE
        ),
    }

    # ── File operation patterns for batch detection ──
    FILE_OP_PATTERNS = re.compile(
        r"(?:created?|wrote|written|modified|updated|edited|changed|added|generated) "
        r"(?:the file |file )?[`\"']?([\w/._-]+\.(?:py|js|ts|html|css|json|md))[`\"']?",
        re.IGNORECASE
    )

    def analyze_message(
        self,
        msg: ClaudeMessage,
        prev_messages: List[ClaudeMessage] = None
    ) -> ClaudeBehaviorFlags:
        """
        Analyze a single Claude message for all 20 behavioral patterns.

        Uses all previous messages by default for cross-message patterns.
        Falls back to last 10 if the full list causes issues.
        """
        if msg.role != "assistant":
            return ClaudeBehaviorFlags()

        flags = ClaudeBehaviorFlags()
        prev = prev_messages or []

        thinking = msg.thinking or ""
        content = msg.content or ""
        full_text = thinking + " " + content
        content_lower = content.lower()

        # ── Original text-based detections ──

        flags.shows_confusion = bool(self.PATTERNS['confusion'].search(full_text))
        flags.admits_forgetting = bool(self.PATTERNS['forgetting'].search(full_text))
        flags.makes_assumptions = bool(self.PATTERNS['assumptions'].search(full_text))
        flags.apologizes = bool(self.PATTERNS['apologies'].search(full_text))
        flags.overconfident = bool(self.PATTERNS['overconfidence'].search(full_text))
        flags.tries_to_clarify = bool(self.PATTERNS['clarifying'].search(full_text))
        flags.acknowledges_mistake = bool(self.PATTERNS['acknowledges_mistake'].search(full_text))

        # Rushing: short thinking relative to task complexity
        if thinking:
            if len(thinking) < 100 and len(content) > 500:
                flags.rushes_to_solution = True

        # Asking questions (positive behavior)
        if '?' in content and any(q in content_lower for q in
            ['would you', 'should i', 'do you want', 'which', 'what would you',
             'how would you', 'what do you think', 'your preference',
             'your call', 'up to you', 'let me know']):
            flags.asks_questions = True

        # ── New: Idea Evolution pattern detections ──

        # A: Unsolicited addition (Helpful Saboteur)
        match = self.PATTERNS['unsolicited_addition'].search(full_text)
        if match:
            flags.unsolicited_addition = True
            flags.details['unsolicited_addition'] = match.group(0)

        # B: Premature completion
        match = self.PATTERNS['premature_completion'].search(content)
        if match:
            flags.premature_completion = True
            flags.details['premature_completion'] = match.group(0)

        # C: Batch without verify — detected by counting file operations
        # in this message without any "test", "run", "verify" in between
        file_ops = self.FILE_OP_PATTERNS.findall(content)
        if len(file_ops) >= 3:
            has_verify = bool(re.search(
                r'\b(?:test(?:ed|ing)?|verif(?:y|ied|ying)|ran|running|executed?|checked?|confirmed?)\b',
                content, re.IGNORECASE
            ))
            if not has_verify:
                flags.batch_without_verify = True
                flags.details['batch_without_verify'] = f"{len(file_ops)} files: {', '.join(file_ops)}"

        # D: Silent decision
        match = self.PATTERNS['silent_decision'].search(full_text)
        if match:
            flags.silent_decision = True
            flags.details['silent_decision'] = match.group(0)

        # E: Hollow fulfillment — repeated structural patterns in output
        # Detect if Claude is producing templated/repetitive content
        if len(content) > 500:
            paragraphs = [p.strip() for p in content.split('\n\n') if len(p.strip()) > 50]
            if len(paragraphs) >= 4:
                # Check if paragraphs follow a repetitive structure
                # (same opening words, same length pattern)
                openings = [p.split()[:3] if p.split() else [] for p in paragraphs]
                opening_strs = [' '.join(o) for o in openings]
                most_common_opening = max(set(opening_strs), key=opening_strs.count) if opening_strs else ''
                repetition_count = opening_strs.count(most_common_opening)
                if repetition_count >= 3 and repetition_count / len(paragraphs) > 0.5:
                    flags.hollow_fulfillment = True
                    flags.details['hollow_fulfillment'] = f"{repetition_count}/{len(paragraphs)} paragraphs start with '{most_common_opening}'"

        # F: Unverified claim
        match = self.PATTERNS['unverified_claim'].search(content)
        if match:
            # Only flag if there's no actual evidence nearby (no code output, no test results)
            has_evidence = bool(re.search(
                r'```|output:|result:|error:|pass(?:ed|ing)|PASS|OK|Success',
                content
            ))
            if not has_evidence:
                flags.unverified_claim = True
                flags.details['unverified_claim'] = match.group(0)

        # G: Scope creep
        match = self.PATTERNS['scope_creep'].search(full_text)
        if match:
            flags.scope_creep = True
            flags.details['scope_creep'] = match.group(0)

        # ── Cross-message detections (require previous messages) ──

        if prev:
            prev_assistant = [m for m in prev if m.role == "assistant"]

            # H: Contradicts self — check if current message contradicts prior statements
            flags.contradicts_self = self._detect_contradiction(content, prev_assistant)

            # I: Repeats failed approach — check if this approach was tried and failed before
            flags.repeats_failed_approach = self._detect_repeated_failure(content, prev)

            # Ignores context — check if Claude references anything from recent conversation
            if prev_assistant and len(content) > 200:
                # Get key terms from the last user message
                last_user = None
                for m in reversed(prev):
                    if m.role == "user":
                        last_user = m
                        break
                if last_user and last_user.content:
                    user_terms = set(w.lower() for w in last_user.content.split()
                                     if len(w) > 5 and w.isalpha())
                    if user_terms:
                        content_terms = set(w.lower() for w in content.split()
                                            if len(w) > 5 and w.isalpha())
                        overlap = user_terms & content_terms
                        if len(overlap) < min(3, len(user_terms) * 0.1):
                            flags.ignores_context = True

        # ── Calculate user upset score ──
        # Scores assigned by the user (Feb 13, 2026) based on how upsetting
        # each behavior would be if they found out it just happened.
        # Scale: 1-10 (10 = most upsetting). Negative = good behavior.
        # Score of 20 for ignores_context = "off the scale, worst thing possible"

        USER_UPSET_SCORES = {
            'shows_confusion': -5,        # Good — means Claude is being honest
            'admits_forgetting': 0,       # Saying "I forgot" ≠ actually forgetting
            'makes_assumptions': 7,
            'contradicts_self': 0,        # Usually a result of other behaviors, not root cause
            'apologizes': 0,              # Not bad
            'rushes_to_solution': 4,
            'overconfident': 8,
            'unsolicited_addition': 7,
            'premature_completion': 9,
            'batch_without_verify': 10,
            'silent_decision': 10,
            'hollow_fulfillment': 10,
            'unverified_claim': 10,       # User's word: "a nice way of saying lying"
            'scope_creep': 10,
            'repeats_failed_approach': 9,
            'ignores_context': 20,        # Off the scale. The single worst behavior.
        }

        score = 0
        for attr, weight in USER_UPSET_SCORES.items():
            if getattr(flags, attr, False):
                score += weight

        # Positive behaviors (user didn't score these — they're not upsetting)
        # No reduction applied. Positive behaviors are tracked separately.

        flags.user_upset_score = max(0, score)

        return flags

    def _detect_contradiction(self, current_content: str, prev_assistant: List[ClaudeMessage]) -> bool:
        """Detect if current message contradicts a prior assistant statement.

        Looks for patterns where Claude says the opposite of what it said before:
        - Previously said X works, now says X doesn't work
        - Previously said it used model A, now says it used model B
        - Previously said file doesn't exist, now references it as existing
        """
        if not prev_assistant or not current_content:
            return False

        current_lower = current_content.lower()

        # Pattern: "actually, that was wrong" / "I was incorrect earlier"
        if re.search(r'actually,? (?:that|this|it) was(?:n\'?t| not)|'
                     r'i was (?:wrong|incorrect|mistaken) (?:earlier|before|about)|'
                     r'contrary to what i (?:said|stated|mentioned)',
                     current_lower):
            return True

        # Pattern: Check for direct negation of prior claims
        for prev_msg in prev_assistant[-5:]:  # Check last 5 assistant messages
            prev_content = (prev_msg.content or "").lower()
            if not prev_content:
                continue

            # "X works" followed by "X doesn't work" (or vice versa)
            prev_works = re.findall(r'(\w+(?:\.\w+)?)\s+(?:works?|is working|is functional)', prev_content)
            for item in prev_works:
                if re.search(rf'{re.escape(item)}\s+(?:doesn\'?t|does not|isn\'?t|is not)\s+work', current_lower):
                    return True

            # "complete" followed by "not complete"
            prev_complete = re.findall(r'(\w+(?:\.\w+)?)\s+(?:is )?(?:complete|done|finished)', prev_content)
            for item in prev_complete:
                if re.search(rf'{re.escape(item)}\s+(?:is )?(?:not |in)complete|{re.escape(item)}\s+(?:still )?needs?', current_lower):
                    return True

        return False

    def _detect_repeated_failure(self, current_content: str, prev_messages: List[ClaudeMessage]) -> bool:
        """Detect if Claude is trying the same approach that already failed.

        Looks for:
        - Same file being modified again after a prior error on that file
        - Same command/approach being suggested after it failed before
        """
        if not prev_messages or not current_content:
            return False

        # Find files mentioned in current message
        current_files = set(self.FILE_OP_PATTERNS.findall(current_content))
        if not current_files:
            return False

        # Look for prior failures involving those same files
        recent_failure_files = set()
        for prev_msg in prev_messages:
            prev_content = (prev_msg.content or "").lower()
            if not prev_content:
                continue

            # Check if this previous message indicates a failure
            has_failure = bool(re.search(
                r'error|failed|exception|traceback|doesn\'?t work|broken|crash',
                prev_content
            ))
            if has_failure:
                failed_files = set(self.FILE_OP_PATTERNS.findall(prev_content))
                recent_failure_files.update(failed_files)

        # If current message operates on a file that previously failed
        overlap = current_files & recent_failure_files
        if overlap:
            # Only flag if current message doesn't acknowledge the prior failure
            acknowledges = bool(re.search(
                r'(?:fix|resolv|address|handl)(?:e|ed|ing) (?:the|this) (?:error|issue|bug|problem)|'
                r'(?:let me|i\'ll) try (?:a )?different|'
                r'(?:the|this) (?:error|issue|bug) (?:was|is) (?:caused|due)',
                current_content, re.IGNORECASE
            ))
            if not acknowledges:
                return True

        return False

    def analyze_session(self, session: ClaudeSession) -> Dict[str, Any]:
        """Analyze an entire session for Claude behavior patterns."""
        total_messages = 0
        total_upset_score = 0
        pattern_counts = defaultdict(int)
        high_damage_indices = []
        all_messages_so_far = []

        for i, msg in enumerate(session.messages):
            if msg.role != "assistant":
                all_messages_so_far.append(msg)
                continue

            flags = self.analyze_message(msg, prev_messages=all_messages_so_far)
            all_messages_so_far.append(msg)
            total_messages += 1
            total_upset_score += flags.user_upset_score

            # Count all behaviors
            for attr in [
                'shows_confusion', 'admits_forgetting', 'makes_assumptions',
                'contradicts_self', 'apologizes', 'rushes_to_solution',
                'overconfident', 'ignores_context', 'repeats_failed_approach',
                'unsolicited_addition', 'premature_completion', 'batch_without_verify',
                'silent_decision', 'hollow_fulfillment', 'unverified_claim',
                'scope_creep', 'tries_to_clarify', 'asks_questions',
                'acknowledges_mistake',
            ]:
                if getattr(flags, attr, False):
                    pattern_counts[attr] += 1

            if flags.user_upset_score >= 5:
                high_damage_indices.append(i)

        avg_upset = total_upset_score / total_messages if total_messages > 0 else 0

        return {
            "total_assistant_messages": total_messages,
            "avg_upset_score": round(avg_upset, 2),
            "high_damage_moments": len(high_damage_indices),
            "high_damage_indices": high_damage_indices,
            "pattern_counts": dict(pattern_counts),
            "most_common_issues": sorted(
                [(k, v) for k, v in pattern_counts.items()
                 if k not in ('tries_to_clarify', 'asks_questions', 'acknowledges_mistake')],
                key=lambda x: -x[1]
            ),
        }

    def get_pre_emergency_behavior(
        self,
        session: ClaudeSession,
        emergency_indices: List[int],
        window: int = 3
    ) -> Dict[str, Any]:
        """
        Analyze Claude's behavior in the messages BEFORE emergency interventions.
        """
        pre_emergency_patterns = defaultdict(int)
        pre_emergency_upset_scores = []

        assistant_messages = [(i, m) for i, m in enumerate(session.messages) if m.role == "assistant"]

        for emergency_idx in emergency_indices:
            relevant_messages = [
                (i, m) for i, m in assistant_messages
                if m.timestamp and session.messages[emergency_idx].timestamp
                and m.timestamp < session.messages[emergency_idx].timestamp
            ][-window:]

            for _, msg in relevant_messages:
                flags = self.analyze_message(msg)
                pre_emergency_upset_scores.append(flags.user_upset_score)

                for attr in [
                    'shows_confusion', 'admits_forgetting', 'makes_assumptions',
                    'contradicts_self', 'apologizes', 'rushes_to_solution',
                    'overconfident', 'unsolicited_addition', 'premature_completion',
                    'batch_without_verify', 'silent_decision', 'unverified_claim',
                ]:
                    if getattr(flags, attr, False):
                        pre_emergency_patterns[attr] += 1

        avg_pre_upset = sum(pre_emergency_upset_scores) / len(pre_emergency_upset_scores) if pre_emergency_upset_scores else 0

        return {
            "emergencies_analyzed": len(emergency_indices),
            "avg_pre_emergency_upset": round(avg_pre_upset, 2),
            "pre_emergency_patterns": dict(pre_emergency_patterns),
            "top_warning_signs": sorted(pre_emergency_patterns.items(), key=lambda x: -x[1]),
        }


@dataclass
class PreventionAlert:
    """Alert generated when context damage risk is detected."""
    level: str  # "WATCH", "CAUTION", "WARNING", "CRITICAL"
    sensing: List[str]
    tactics: List[str]
    message_index: int
    upset_score: int

    def to_prompt_injection(self) -> str:
        lines = [
            f"PREVENTION ALERT [{self.level}] - Message #{self.message_index}",
            "",
            "SENSING (what's happening):",
        ]
        for s in self.sensing:
            lines.append(f"  - {s}")
        lines.append("")
        lines.append("TACTICS (what to do):")
        for t in self.tactics:
            lines.append(f"  -> {t}")
        return "\n".join(lines)


class PreventionSystem:
    """
    Combines user frustration metadata + Claude behavior analysis
    to generate prevention alerts before context damage cascades.
    """

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
        'unsolicited_addition': [
            "STOP - Only build what was asked for",
            "ASK - Present the addition as a suggestion, not a fait accompli",
            "REVERT - Remove the unsolicited addition"
        ],
        'premature_completion': [
            "SHOW EVIDENCE - Output, test results, verification",
            "DO NOT CLAIM DONE - Let the user decide if it's done",
            "LIST REMAINING - What hasn't been verified yet?"
        ],
        'silent_decision': [
            "PRESENT OPTIONS - Show the user what the choices are",
            "EXPLAIN TRADEOFFS - What does each option mean?",
            "WAIT - Do not implement until the user chooses"
        ],
        'batch_without_verify': [
            "STOP - Test the current file before touching the next one",
            "RUN - Execute the code and show the output",
            "ONE AT A TIME - Verify each piece before continuing"
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
        ],
    }

    def generate_alert(
        self,
        claude_flags: ClaudeBehaviorFlags,
        user_frustration_level: int = 0,
        user_has_profanity: bool = False,
        user_exclamations: int = 0,
        message_index: int = 0
    ) -> Optional[PreventionAlert]:
        sensing = []
        tactics = []
        total_risk = claude_flags.user_upset_score

        # User signals
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

        # Claude behavior signals
        behavior_tactics_map = {
            'shows_confusion': ('Claude showing confusion signals', 'confusion'),
            'admits_forgetting': ('Claude forgetting/missing context', 'forgetting'),
            'makes_assumptions': ('Claude making assumptions without verification', 'assumptions'),
            'rushes_to_solution': ('Claude rushing (short thinking, quick action)', 'rushing'),
            'overconfident': ('Claude overconfident (certainty language)', 'overconfidence'),
            'unsolicited_addition': ('Claude adding unrequested features/defaults', 'unsolicited_addition'),
            'premature_completion': ('Claude declaring work complete without evidence', 'premature_completion'),
            'silent_decision': ('Claude making design decisions without presenting options', 'silent_decision'),
            'batch_without_verify': ('Claude modifying multiple files without testing', 'batch_without_verify'),
        }

        for attr, (description, tactic_key) in behavior_tactics_map.items():
            if getattr(claude_flags, attr, False):
                sensing.append(description)
                if tactic_key in self.TACTICS:
                    tactics.extend(self.TACTICS[tactic_key])

        if claude_flags.contradicts_self:
            sensing.append("Claude contradicting a prior statement")
        if claude_flags.repeats_failed_approach:
            sensing.append("Claude repeating an approach that already failed")
        if claude_flags.hollow_fulfillment:
            sensing.append("Claude producing generic/templated output")
        if claude_flags.unverified_claim:
            sensing.append("Claude making claims without showing evidence")
        if claude_flags.scope_creep:
            sensing.append("Claude expanding scope beyond what was requested")

        # Alert level
        if total_risk >= 8:
            level = "CRITICAL"
            sensing.insert(0, "EMERGENCY IMMINENT - Multiple high-risk signals")
            tactics = self.TACTICS['emergency_imminent'] + tactics
        elif total_risk >= 5:
            level = "WARNING"
        elif total_risk >= 3:
            level = "CAUTION"
        elif total_risk >= 1:
            level = "WATCH"
        else:
            return None

        # Deduplicate tactics
        tactics = list(dict.fromkeys(tactics))

        return PreventionAlert(
            level=level,
            sensing=sensing,
            tactics=tactics,
            message_index=message_index,
            upset_score=total_risk
        )


def main():
    """CLI for testing the behavior analyzer."""
    from pathlib import Path

    print("=" * 70)
    print("CLAUDE BEHAVIOR ANALYZER (v2 — 20 behaviors)")
    print("=" * 70)

    reader = ClaudeSessionReader(verbose=False)
    analyzer = ClaudeBehaviorAnalyzer()

    project = os.getenv("HYPERDOCS_PROJECT_ID", "")
    sessions = reader.load_project_sessions(project_name=project, limit=5)

    for session in list(sessions.values())[:2]:
        print(f"\nSession: {session.session_id}")
        analysis = analyzer.analyze_session(session)

        print(f"  Assistant messages: {analysis['total_assistant_messages']}")
        print(f"  Avg upset score: {analysis['avg_upset_score']}")
        print(f"  High damage moments: {analysis['high_damage_moments']}")
        print(f"  Pattern counts:")
        for k, v in sorted(analysis['pattern_counts'].items(), key=lambda x: -x[1]):
            print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
