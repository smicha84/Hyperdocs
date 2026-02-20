#!/usr/bin/env python3
"""
Phase 0 LLM Pass Prompts
=========================

Seven prompt templates for the 4 LLM passes that supplement Python-only Phase 0.
Each prompt was tested across 450+ API calls (3 models x 3 rounds of refinement)
on 50-message samples from session 0012ebed.

Round 3 (example-based) achieved:
  - content_referential: 90%+ agreement (all models)
  - unverified_claims: 90% agreement
  - overconfidence: 92% agreement
  - assumptions subtypes: 80% ceiling (best achievable)
  - silent_decisions: 80% with Opus (50% cross-model)

Pass 1 (Haiku 4.5): content_referential + assumption subtypes
Pass 2 (Opus 4.6): silent_decisions + unverified_claims + overconfidence
Pass 3 (Opus 4.6): intent_assumption resolution (targeted, needs user context)
Pass 4 (Haiku 4.5): strategic importance scoring
"""


# ── Pass 1: Content-Referential + Assumption Subtypes (Haiku) ──────────

PASS1_SYSTEM = """You are a behavioral analysis engine for AI coding assistant conversations.
You analyze assistant messages to detect two things:

1. CONTENT-REFERENTIAL SIGNALS: Whether failure/frustration/error signals in
   the message come from the TOPIC being discussed (the assistant is analyzing
   or explaining error handling patterns) rather than from actual session dynamics
   (real errors happening right now).

2. ASSUMPTION SUBTYPES: Whether the assistant is making assumptions in 4 categories:
   - code_assumption: Assuming what code does without reading it
   - format_assumption: Assuming output format, file structure, or data shape
   - direction_assumption: Assuming what the user wants without asking
   - scope_assumption: Assuming what's in/out of scope

Respond with a JSON array, one object per message, matching the input order."""

PASS1_USER_TEMPLATE = """Analyze each assistant message below. For each, output:
{{
  "index": <message index from input>,
  "content_referential": true/false,
  "content_referential_reason": "<one sentence if true, null if false>",
  "code_assumption": true/false,
  "format_assumption": true/false,
  "direction_assumption": true/false,
  "scope_assumption": true/false,
  "assumption_details": "<what was assumed, null if none>"
}}

EXAMPLES:

Message: "The error handling in gate_protection.py uses bare except blocks, which
swallow all exceptions including KeyboardInterrupt. There are 86 instances across
the codebase. Each one should be replaced with `except Exception`."
→ content_referential: true (discussing error handling patterns, not experiencing errors)
→ code_assumption: false, format_assumption: false, direction_assumption: false, scope_assumption: false

Message: "I'll set the batch size to 30 messages per chunk, which should work well
for most sessions."
→ content_referential: false
→ code_assumption: false, format_assumption: true (assuming 30 is the right batch size),
  direction_assumption: false, scope_assumption: false

Message: "Let me fix the authentication module. I think the user wants OAuth2 since
that's the standard approach for this kind of application."
→ content_referential: false
→ code_assumption: false, format_assumption: false,
  direction_assumption: true (assuming user wants OAuth2 without asking),
  scope_assumption: false

Message: "I'll also clean up the import statements while I'm editing this file."
→ content_referential: false
→ code_assumption: false, format_assumption: false, direction_assumption: false,
  scope_assumption: true (assuming cleanup is in scope)

MESSAGES TO ANALYZE:
{messages}

Respond with ONLY a JSON array. No markdown, no explanation."""


# ── Pass 2: Silent Decisions + Unverified Claims + Overconfidence (Opus) ──

PASS2_SYSTEM = """You are a behavioral analysis engine with extremely high precision.
You detect three specific patterns in AI assistant messages. You err on the side of
NOT flagging — only flag when the evidence is clear.

1. SILENT DECISIONS: The assistant chose a specific value, default, threshold, limit,
   approach, or implementation detail WITHOUT presenting it as a choice to the user.
   The key test: did the user specify this, or did the assistant pick it?

2. UNVERIFIED CLAIMS: The assistant states something as fact ("this works", "tests pass",
   "no errors") without showing the actual output, test result, or evidence in the
   same message. The claim must be about the current work, not general knowledge.

3. OVERCONFIDENCE: The assistant uses certainty language ("will definitely", "guaranteed",
   "this should fix it", "100% correct") about outcomes that haven't been verified yet.

CRITICAL: Low false positive rate matters more than catching everything. If uncertain,
output false."""

PASS2_USER_TEMPLATE = """Analyze each assistant message below. For each, output:
{{
  "index": <message index>,
  "silent_decisions": [
    {{"decision": "<what was decided>", "context": "<why this is a silent decision>"}}
  ],
  "unverified_claims": [
    {{"claim": "<the claim made>", "evidence_gap": "<what evidence is missing>"}}
  ],
  "overconfident": true/false,
  "overconfidence_detail": "<the overconfident phrase, null if false>"
}}

EXAMPLES:

Message: "I'll set the timeout to 30 seconds and use retry logic with exponential
backoff starting at 1 second."
→ silent_decisions: [{{"decision": "set timeout to 30s", "context": "user never specified timeout value"}},
   {{"decision": "exponential backoff starting at 1s", "context": "backoff strategy not discussed"}}]
→ unverified_claims: []
→ overconfident: false

Message: "I've updated all 15 files and everything is working correctly now. The
pipeline processes messages without any errors."
→ silent_decisions: []
→ unverified_claims: [{{"claim": "everything is working correctly", "evidence_gap": "no test output shown"}},
   {{"claim": "processes without any errors", "evidence_gap": "no execution results in this message"}}]
→ overconfident: false

Message: "This implementation will definitely handle all edge cases. I'm confident
the regex pattern covers every possible input format."
→ silent_decisions: []
→ unverified_claims: []
→ overconfident: true
→ overconfidence_detail: "will definitely handle all edge cases"

Message: "Here's the function. I tested it with the sample data and got this output:
```
Processing 50 messages... done.
Results: 47 classified, 3 skipped
```"
→ silent_decisions: []
→ unverified_claims: [] (claim backed by shown output)
→ overconfident: false

Message: "For simplicity, I'll cap the content at 200 characters in the summary view."
→ silent_decisions: [{{"decision": "cap content at 200 characters", "context": "character limit is a design choice not discussed with user"}}]
→ unverified_claims: []
→ overconfident: false

MESSAGES TO ANALYZE:
{messages}

Respond with ONLY a JSON array. No markdown, no explanation."""


# ── Pass 3: Intent Assumption Resolution (Opus, targeted) ─────────────

PASS3_SYSTEM = """You are a behavioral analysis engine specializing in detecting
INTENT ASSUMPTIONS — cases where an AI assistant assumes what the user wants without
asking.

You have access to the preceding user messages for context. Your job is to determine:
did the assistant ASSUME what the user wanted, or did the user explicitly state it?

Output one of three values:
  - "yes": The assistant clearly assumed user intent without evidence
  - "no": The user explicitly stated what they wanted, or the intent is obvious
  - "uncertain": Reasonable people could disagree

CRITICAL: "uncertain" is a valid and important output. Use it when the assistant's
action COULD be an assumption but could also be a reasonable inference from clear
context."""

PASS3_USER_TEMPLATE = """For each assistant message below, determine if it contains
an INTENT ASSUMPTION. You are given the preceding user message(s) for context.

Output for each:
{{
  "index": <message index>,
  "intent_assumption": "yes" | "no" | "uncertain",
  "reasoning": "<one sentence explaining your judgment>"
}}

EXAMPLE:

User context: "fix the bug in the login page"
Assistant: "I'll also add input validation to prevent SQL injection while I'm fixing
the login bug."
→ intent_assumption: "yes"
→ reasoning: "User asked to fix a bug, not add validation. The addition is an assumption about scope."

User context: "the tests are failing, can you look at it"
Assistant: "Let me read the test file and run the tests to see the errors."
→ intent_assumption: "no"
→ reasoning: "Reading and running tests is the obvious first step for debugging test failures."

User context: "make the dashboard look better"
Assistant: "I'll add a dark mode toggle and reorganize the layout with a sidebar."
→ intent_assumption: "uncertain"
→ reasoning: "Dark mode and sidebar could be improvements, but the user didn't specify these. 'Look better' is vague enough that these choices might or might not match intent."

MESSAGES TO ANALYZE:
{messages}

Respond with ONLY a JSON array. No markdown, no explanation."""


# ── Pass 4: Strategic Importance Scoring (Haiku) ──────────────────────

PASS4_SYSTEM = """You are a message importance scorer for AI coding assistant conversations.
You assign each message a strategic importance score from 1-10 based on how much it
matters for understanding the session's trajectory and outcomes.

Scoring guide:
  1-2: Boilerplate, acknowledgments, "sure, let me do that", routine tool output
  3-4: Standard implementation steps, reading files, minor edits
  5-6: Meaningful work — creating features, fixing bugs, making progress
  7-8: Key decisions, architectural choices, significant pivots, user corrections
  9-10: Session-defining moments — major breakthroughs, critical failures, user directives
        that reshape everything, fundamental design decisions

Short messages can be high importance. "use only Opus" (14 chars) is a 10.
Long messages can be low importance. A 2000-char boilerplate response is a 2."""

PASS4_USER_TEMPLATE = """Score each message's strategic importance (1-10).

Output for each:
{{
  "index": <message index>,
  "importance": <1-10>,
  "reason": "<one sentence>"
}}

EXAMPLES:

Message (user, 14 chars): "use only Opus"
→ importance: 10, reason: "Direct architectural constraint that affects entire pipeline"

Message (assistant, 500 chars): "Sure, I'll read the file now. Let me take a look at
the contents..."
→ importance: 2, reason: "Routine acknowledgment before action"

Message (user, 200 chars): "I really hate the idea of you deleting things"
→ importance: 9, reason: "Establishes fundamental behavioral constraint"

Message (assistant, 1500 chars): "Here's the implementation of the message filter with
4 tiers based on content length and keyword density..."
→ importance: 6, reason: "Meaningful implementation work contributing to pipeline"

Message (assistant, 800 chars): "I've updated the configuration. The changes look good
and everything should work now."
→ importance: 3, reason: "Routine status update without evidence"

MESSAGES TO ANALYZE:
{messages}

Respond with ONLY a JSON array. No markdown, no explanation."""


# ── Helper: Format messages for prompt injection ──────────────────────

def format_messages_for_prompt(messages, include_user_context=False):
    """Format enriched message records into prompt-ready text.

    Args:
        messages: List of enriched message dicts from enriched_session.json
        include_user_context: If True, include preceding user messages (for Pass 3)

    Returns:
        Formatted string for insertion into prompt templates
    """
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        index = msg.get("index", "?")
        content = msg.get("content", "")

        # Truncate extremely long messages to keep within context window
        # but preserve enough for accurate analysis
        if len(content) > 4000:
            content = content[:3800] + "\n[... truncated for analysis ...]"

        header = f"--- Message {index} ({role}) ---"
        parts.append(f"{header}\n{content}")

    return "\n\n".join(parts)


def format_messages_with_context(target_messages, all_messages):
    """Format target messages with their preceding user context (for Pass 3).

    For each target assistant message, includes up to 2 preceding user messages.

    Args:
        target_messages: List of assistant message dicts to analyze
        all_messages: Full message list for context lookup

    Returns:
        Formatted string with user context before each target message
    """
    # Build index lookup
    by_index = {m["index"]: m for m in all_messages}

    parts = []
    for msg in target_messages:
        idx = msg.get("index", 0)

        # Find preceding user messages
        context_msgs = []
        for look_back in range(1, 10):
            prev_idx = idx - look_back
            if prev_idx in by_index and by_index[prev_idx]["role"] == "user":
                context_msgs.insert(0, by_index[prev_idx])
                if len(context_msgs) >= 2:
                    break

        # Format context
        if context_msgs:
            for cm in context_msgs:
                c_content = cm.get("content", "")
                if len(c_content) > 2000:
                    c_content = c_content[:1800] + "\n[... truncated ...]"
                parts.append(f"--- User context (message {cm['index']}) ---\n{c_content}")

        # Format target message
        content = msg.get("content", "")
        if len(content) > 4000:
            content = content[:3800] + "\n[... truncated for analysis ...]"
        parts.append(f"--- Message {msg['index']} (assistant) [ANALYZE THIS] ---\n{content}")
        parts.append("")  # blank line separator

    return "\n\n".join(parts)


# ── Pass configuration registry ──────────────────────────────────────

PASS_CONFIGS = {
    1: {
        "name": "Content-Referential + Assumption Subtypes",
        "model": "claude-haiku-4-5-20251001",
        "system_prompt": PASS1_SYSTEM,
        "user_template": PASS1_USER_TEMPLATE,
        "message_filter": lambda m: m.get("role") == "assistant" and m.get("filter_tier", 0) >= 2,
        "needs_user_context": False,
        "output_file": "llm_pass1_content_ref.json",
    },
    2: {
        "name": "Silent Decisions + Unverified Claims + Overconfidence",
        "model": "claude-opus-4-6",
        "system_prompt": PASS2_SYSTEM,
        "user_template": PASS2_USER_TEMPLATE,
        "message_filter": lambda m: m.get("role") == "assistant" and m.get("filter_tier", 0) >= 2,
        "needs_user_context": False,
        "output_file": "llm_pass2_behaviors.json",
    },
    3: {
        "name": "Intent Assumption Resolution",
        "model": "claude-opus-4-6",
        "system_prompt": PASS3_SYSTEM,
        "user_template": PASS3_USER_TEMPLATE,
        "message_filter": None,  # Targeted: only messages flagged by Pass 1
        "needs_user_context": True,
        "output_file": "llm_pass3_intent.json",
    },
    4: {
        "name": "Strategic Importance Scoring",
        "model": "claude-haiku-4-5-20251001",
        "system_prompt": PASS4_SYSTEM,
        "user_template": PASS4_USER_TEMPLATE,
        "message_filter": lambda m: m.get("filter_tier", 0) >= 2,
        "needs_user_context": False,
        "output_file": "llm_pass4_importance.json",
    },
}
