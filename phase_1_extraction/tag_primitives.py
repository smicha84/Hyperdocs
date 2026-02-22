#!/usr/bin/env python3
"""
Semantic Primitives Tagger (standalone)
Tags tier 4 priority messages with the 7 Semantic Primitives.

NOTE: This is the standalone/deterministic tagger. The Phase 1 batch pipeline
uses the Opus-based tagger in phase1_redo_orchestrator.py instead. This file
is kept for single-session processing and as a reference implementation.

Primitives:
1. Action Vector: created|modified|debugged|refactored|discovered|decided|abandoned|reverted
2. Confidence Signal: experimental|tentative|working|stable|proven|fragile
3. Emotional Tenor: frustrated|uncertain|curious|cautious|confident|excited|relieved
4. Intent Marker: correctness|performance|maintainability|feature|bugfix|exploration|cleanup
5. Friction Log: Single compressed sentence or null
6. Decision Trace: "chose X over Y because Z" or null
7. Disclosure Pointer: content_hash from enriched data
"""

import json
import re
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import get_session_output_dir
    SESSION_DIR = get_session_output_dir()
except ImportError:
    _SID = os.getenv("HYPERDOCS_SESSION_ID", "")
    SESSION_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output")) / f"session_{_SID[:8]}"

TIER4_FILE = SESSION_DIR / "tier4_priority_messages.json"
USER_FILE = SESSION_DIR / "user_messages_tier2plus.json"
OUTPUT_FILE = SESSION_DIR / "semantic_primitives.json"


def reconstruct_content(content: str) -> str:
    """Reconstruct readable text from character-separated format.

    Detects if content is in the \\n-separated single-character format
    and joins characters back together. Otherwise returns content as-is.
    """
    if not content:
        return ""

    lines = content.split("\n")
    # Heuristic: if most lines are single characters, it's char-separated
    single_char_lines = sum(1 for l in lines if len(l) <= 1)
    if len(lines) > 10 and single_char_lines / len(lines) > 0.7:
        return "".join(lines)
    return content


def parse_filter_signals(signals: list) -> dict:
    """Parse filter_signals like ['frustration:1', 'code:31'] into a dict."""
    result = {}
    for sig in signals:
        if ":" in sig:
            key, val = sig.split(":", 1)
            try:
                result[key] = int(val)
            except ValueError:
                result[key] = val
    return result


# ---------------------------------------------------------------------------
# Action Vector Classification
# ---------------------------------------------------------------------------

def classify_action_vector(content: str, metadata: dict, signals: dict,
                           behavior_flags: dict, role: str) -> str:
    """Classify the action vector from message content and metadata."""
    c = content.lower()

    # Check for revert signals
    revert_kw = ["revert", "undo", "rollback", "roll back", "restore", "put back",
                 "undo those", "bring back", "go back to"]
    if any(kw in c for kw in revert_kw):
        return "reverted"

    # Check for abandon signals
    abandon_kw = ["abandon", "drop this", "forget it", "skip this", "don't need",
                  "not needed", "remove this", "scrap", "no longer need",
                  "is_ignored_gem"]
    if any(kw in c for kw in abandon_kw):
        return "abandoned"
    if signals.get("pivot", 0) >= 3:
        return "abandoned"

    # Check for decision signals
    decision_kw = ["chose", "decide", "decided", "decision", "go with", "let's use",
                   "instead of", "rather than", "prefer", "switch to", "picked",
                   "approved", "plan it out", "let's do", "I want"]
    if any(kw in c for kw in decision_kw):
        return "decided"
    if signals.get("pivot", 0) >= 1 and "plan" in signals:
        return "decided"

    # Check for discovery signals
    discover_kw = ["found", "discovered", "realized", "noticed", "turns out",
                   "it appears", "insight", "interesting", "learned",
                   "the problem is", "the issue is", "root cause",
                   "actually", "it seems"]
    if any(kw in c for kw in discover_kw):
        return "discovered"

    # Check for debug signals
    debug_kw = ["error", "fix", "bug", "traceback", "exception", "failed",
                "broken", "crash", "issue", "debug", "troubleshoot",
                "not working", "doesn't work", "wrong"]
    if metadata.get("error", False) or metadata.get("traceback", False):
        return "debugged"
    if signals.get("failure", 0) >= 2:
        return "debugged"
    if any(kw in c for kw in debug_kw):
        return "debugged"

    # Check for refactor signals
    refactor_kw = ["refactor", "cleanup", "clean up", "reorganize", "restructure",
                   "simplify", "consolidate", "deduplicate", "rename", "move to",
                   "extract into", "split into"]
    if any(kw in c for kw in refactor_kw):
        return "refactored"

    # Check for create signals
    create_kw = ["created", "create", "implement", "built", "wrote", "write",
                 "generate", "add", "new file", "new module"]
    if metadata.get("code_block", False) and metadata.get("files_create"):
        return "created"
    if any(kw in c for kw in create_kw):
        if metadata.get("code_block", False) or signals.get("code", 0) >= 10:
            return "created"

    # Check for modify signals
    modify_kw = ["update", "updated", "change", "changed", "modify", "modified",
                 "edit", "edited", "replace", "replaced", "adjust", "tweak",
                 "patch"]
    if metadata.get("files_edit") and len(metadata["files_edit"]) > 0:
        return "modified"
    if any(kw in c for kw in modify_kw):
        return "modified"

    # Architecture / code-heavy messages default to modified or created
    if signals.get("architecture", 0) >= 4 and signals.get("code", 0) >= 10:
        return "created"
    if signals.get("code", 0) >= 5:
        return "modified"

    # Fallback based on role
    if role == "user":
        if metadata.get("questions", 0) >= 2:
            return "discovered"
        return "decided"

    # Assistant default: discovered if analytical, otherwise modified
    if signals.get("architecture", 0) >= 2 or signals.get("plan", 0) >= 2:
        return "discovered"
    return "modified"


# ---------------------------------------------------------------------------
# Confidence Signal Classification
# ---------------------------------------------------------------------------

def classify_confidence(content: str, metadata: dict, signals: dict,
                        behavior_flags: dict, role: str) -> str:
    """Classify confidence signal."""
    c = content.lower()

    # Fragile indicators
    fragile_kw = ["fragile", "#fragile", "silently fail", "silent fallback",
                  "may fail", "might break", "edge case", "hack", "workaround",
                  "brittle", "unstable"]
    if any(kw in c for kw in fragile_kw):
        return "fragile"

    # Experimental indicators
    experimental_kw = ["experimental", "prototype", "proof of concept", "poc",
                       "try this", "let's see", "attempt", "rough", "draft",
                       "first pass", "quick test"]
    if any(kw in c for kw in experimental_kw):
        return "experimental"

    # Proven indicators
    proven_kw = ["verified", "all tests pass", "19/19", "100%", "confirmed",
                 "proven", "validated", "pass: ", "working correctly"]
    if any(kw in c for kw in proven_kw):
        return "proven"

    # Stable indicators
    stable_kw = ["stable", "solid", "reliable", "production", "complete",
                 "done", "finished", "all checks complete"]
    if any(kw in c for kw in stable_kw):
        return "stable"

    # Working indicators
    working_kw = ["working", "works", "functional", "runs", "operational",
                  "wired up", "connected", "integrated"]
    if any(kw in c for kw in working_kw):
        return "working"

    # Tentative indicators
    tentative_kw = ["might", "maybe", "possibly", "not sure", "unclear",
                    "think", "seems like", "appears to", "could be"]
    if any(kw in c for kw in tentative_kw):
        return "tentative"

    # Check behavior flags for assistant
    if behavior_flags:
        if behavior_flags.get("overconfident"):
            return "working"  # claims more than warranted
        if behavior_flags.get("confusion") or behavior_flags.get("assumptions"):
            return "tentative"

    # If there are errors mentioned
    if metadata.get("error", False) or signals.get("failure", 0) >= 2:
        return "fragile"

    # Default based on signal strength
    if signals.get("code", 0) >= 15:
        return "working"
    return "tentative"


# ---------------------------------------------------------------------------
# Emotional Tenor Classification
# ---------------------------------------------------------------------------

def classify_emotion(content: str, metadata: dict, signals: dict,
                     behavior_flags: dict, role: str) -> str:
    """Classify emotional tenor."""
    c = content.lower()
    caps_ratio = metadata.get("caps_ratio", 0)
    exclamations = metadata.get("exclamations", 0)
    profanity = metadata.get("profanity", False)
    emergency = metadata.get("emergency_intervention", False)

    # Frustrated: profanity, high caps, emergency interventions
    if profanity and caps_ratio > 0.3:
        return "frustrated"
    if emergency:
        return "frustrated"
    if caps_ratio > 0.5:
        return "frustrated"
    if profanity:
        return "frustrated"
    if signals.get("frustration", 0) >= 3:
        return "frustrated"

    # Excited: exclamations with positive context
    excited_kw = ["remarkable", "amazing", "great", "love", "perfect",
                  "excellent", "awesome", "fantastic", "breakthrough", "insight"]
    if exclamations >= 2 and any(kw in c for kw in excited_kw):
        return "excited"
    if "love" in c and role == "user":
        return "excited"

    # Relieved: after fixing something
    relieved_kw = ["done", "fixed", "resolved", "finally", "that's better",
                   "now it works", "all checks complete", "problem solved"]
    if any(kw in c for kw in relieved_kw) and not profanity:
        return "relieved"

    # Confident: strong assertions
    confident_kw = ["definitely", "clearly", "certainly", "obviously",
                    "absolutely", "no doubt"]
    if any(kw in c for kw in confident_kw):
        return "confident"
    if behavior_flags and behavior_flags.get("overconfident"):
        return "confident"

    # Cautious: hedging language
    cautious_kw = ["careful", "caution", "risk", "consider", "should check",
                   "verify", "make sure", "double check", "watch out",
                   "be aware", "note that"]
    if any(kw in c for kw in cautious_kw):
        return "cautious"

    # Uncertain: questioning, confusion
    uncertain_kw = ["not sure", "unclear", "confused", "don't know",
                    "don't understand", "what do you mean", "hmm"]
    if metadata.get("questions", 0) >= 3 and role == "user":
        return "uncertain"
    if any(kw in c for kw in uncertain_kw):
        return "uncertain"
    if behavior_flags and behavior_flags.get("confusion"):
        return "uncertain"

    # Curious: exploring, investigating
    curious_kw = ["interesting", "let's see", "I wonder", "what if",
                  "explore", "investigate", "look into", "dig into",
                  "analyze", "check"]
    if any(kw in c for kw in curious_kw):
        return "curious"
    if signals.get("architecture", 0) >= 3 and not profanity:
        return "curious"

    # Default
    if role == "user":
        if caps_ratio > 0.15:
            return "frustrated"
        if metadata.get("questions", 0) >= 1:
            return "curious"
        return "confident"

    # Assistant default
    return "confident"


# ---------------------------------------------------------------------------
# Intent Marker Classification
# ---------------------------------------------------------------------------

def classify_intent(content: str, metadata: dict, signals: dict,
                    behavior_flags: dict, role: str) -> str:
    """Classify intent marker."""
    c = content.lower()

    # Bugfix intent
    bugfix_kw = ["fix", "bug", "error", "broken", "crash", "patch",
                 "resolve", "issue", "traceback", "exception"]
    if metadata.get("error", False) or metadata.get("traceback", False):
        return "bugfix"
    if signals.get("failure", 0) >= 3:
        return "bugfix"
    if any(kw in c for kw in bugfix_kw) and not any(
            kw in c for kw in ["feature", "new", "create", "implement"]):
        return "bugfix"

    # Cleanup intent
    cleanup_kw = ["cleanup", "clean up", "remove dead", "delete unused",
                  "strip", "remove", "tidy", "prune", "simplify"]
    if any(kw in c for kw in cleanup_kw):
        return "cleanup"

    # Exploration intent
    explore_kw = ["analyze", "analysis", "investigate", "explore", "check",
                  "verify", "audit", "examine", "look at", "understand",
                  "should vs", "should be vs", "what it actually"]
    if any(kw in c for kw in explore_kw):
        return "exploration"
    if signals.get("architecture", 0) >= 4:
        return "exploration"

    # Correctness intent
    correct_kw = ["correct", "accurate", "valid", "proper", "right",
                  "import verification", "test", "pass/fail", "verify"]
    if any(kw in c for kw in correct_kw):
        return "correctness"

    # Maintainability intent
    maintain_kw = ["maintainability", "readable", "documentation", "doc",
                   "comment", "refactor", "restructure", "organize",
                   "#fragile", "technical debt"]
    if any(kw in c for kw in maintain_kw):
        return "maintainability"

    # Performance intent
    perf_kw = ["performance", "speed", "fast", "slow", "optimize",
               "efficient", "cost", "expensive", "token", "latency"]
    if any(kw in c for kw in perf_kw):
        return "performance"

    # Feature intent
    feature_kw = ["feature", "implement", "create", "build", "add",
                  "new", "orchestrator", "pipeline", "system", "module"]
    if any(kw in c for kw in feature_kw):
        return "feature"

    # Default based on signals
    if signals.get("plan", 0) >= 3:
        return "feature"
    if signals.get("code", 0) >= 10:
        return "feature"
    return "exploration"


# ---------------------------------------------------------------------------
# Friction Log Extraction
# ---------------------------------------------------------------------------

def extract_friction(content: str, metadata: dict, signals: dict,
                     behavior_flags: dict, role: str) -> str:
    """Extract a friction log sentence, or None if no friction."""
    c = content.lower()
    caps_ratio = metadata.get("caps_ratio", 0)
    profanity = metadata.get("profanity", False)
    emergency = metadata.get("emergency_intervention", False)

    # High frustration user messages
    if role == "user" and (caps_ratio > 0.3 or profanity or emergency):
        # Try to extract the core complaint
        readable = reconstruct_content(content).strip()
        # Clean up
        readable = readable.replace("\n", " ").strip()
        if readable:
            return f"User frustration: {readable}"

    # Error-related friction
    if metadata.get("error", False) or metadata.get("traceback", False):
        error_types = metadata.get("error_types", [])
        if error_types:
            return f"Encountered {', '.join(error_types)} during execution"
        return "Code error encountered during execution"

    # Behavior flag friction
    if behavior_flags:
        flags_active = [k for k, v in behavior_flags.items()
                        if v and k not in ("asks_questions", "clarifying")]
        if flags_active:
            return f"Assistant exhibited: {', '.join(flags_active)}"

    # Pivot-related friction
    if signals.get("pivot", 0) >= 2:
        return "Direction changed mid-task, prior work potentially wasted"

    # Failure-related friction
    if signals.get("failure", 0) >= 3:
        return "Multiple failure signals detected in this message"

    # Frustration signal
    if signals.get("frustration", 0) >= 2:
        return "Frustration signals present in interaction"

    return None


# ---------------------------------------------------------------------------
# Decision Trace Extraction
# ---------------------------------------------------------------------------

def extract_decision(content: str, metadata: dict, signals: dict,
                     role: str) -> str:
    """Extract decision trace in 'chose X over Y because Z' format, or None."""
    c = content.lower()

    # Look for explicit decision patterns
    # Pattern: "chose X over Y because Z"
    match = re.search(r'chose\s+(.+?)\s+over\s+(.+?)\s+because\s+(.+?)(?:\.|$)',
                      c, re.IGNORECASE)
    if match:
        return f"chose {match.group(1).strip()} over {match.group(2).strip()} because {match.group(3).strip()}"

    # Pattern: "instead of X, use Y" / "rather than X, Y"
    match = re.search(r'(?:instead of|rather than)\s+(.+?),?\s+(?:use|we|I|go with|chose|pick)\s+(.+?)(?:\.|$)',
                      c, re.IGNORECASE)
    if match:
        return f"chose {match.group(2).strip()} over {match.group(1).strip()} because stated preference"

    # Pattern: "switched from X to Y"
    match = re.search(r'switch(?:ed)?\s+from\s+(.+?)\s+to\s+(.+?)(?:\.|$)',
                      c, re.IGNORECASE)
    if match:
        return f"chose {match.group(2).strip()} over {match.group(1).strip()} because migration/upgrade"

    # Pattern: "evolved from X to Y"
    match = re.search(r'evolved?\s+from\s+(.+?)\s+to\s+(.+?)(?:\.|$)',
                      c, re.IGNORECASE)
    if match:
        return f"chose {match.group(2).strip()} over {match.group(1).strip()} because evolution"

    # Pattern: "X not Y" with context
    match = re.search(r'(?:not|don\'t|do not)\s+(.+?)\s*[,;]\s*(?:use|do|prefer|want)\s+(.+?)(?:\.|$)',
                      c, re.IGNORECASE)
    if match:
        return f"chose {match.group(2).strip()} over {match.group(1).strip()} because user preference"

    # Check for architectural decisions in content
    if "four_thread" in c and "six_thread" in c:
        return "chose six_thread_extractor over four_thread_extractor because expanded analysis threads"

    if "v1" in c and "v5" in c and ("enhance" in c or "incorporate" in c):
        return "chose enhancing V1 with V5 capabilities over replacing V1 because V1 actually worked"

    if "unified_orchestrator" in c and ("pipeline" in c or "orchestrat" in c):
        return "chose unified orchestrator over separate pipelines because need single entry point"

    if "opus" in c and ("sonnet" in c or "haiku" in c) and ("only" in c or "not" in c):
        return "chose Opus only over tiered models because user mandate for quality"

    # Pivot signals may indicate decisions
    if signals.get("pivot", 0) >= 2 and role == "user":
        return None  # pivot without clear decision trace

    return None


# ---------------------------------------------------------------------------
# Main Processing
# ---------------------------------------------------------------------------

def tag_message(msg: dict) -> dict:
    """Tag a single message with all 7 semantic primitives."""
    content_raw = msg.get("content", "")
    metadata = msg.get("metadata", {})
    signals = parse_filter_signals(msg.get("filter_signals", []))
    behavior_flags = msg.get("behavior_flags") or {}
    role = msg.get("role", "unknown")
    content_hash = msg.get("content_hash", "")
    index = msg.get("index", -1)

    # Reconstruct readable content for user messages
    content = reconstruct_content(content_raw)

    action = classify_action_vector(content, metadata, signals, behavior_flags, role)
    confidence = classify_confidence(content, metadata, signals, behavior_flags, role)
    emotion = classify_emotion(content, metadata, signals, behavior_flags, role)
    intent = classify_intent(content, metadata, signals, behavior_flags, role)
    friction = extract_friction(content, metadata, signals, behavior_flags, role)
    decision = extract_decision(content, metadata, signals, role)

    return {
        "index": index,
        "role": role,
        "content_hash": content_hash,
        "primitives": {
            "action_vector": action,
            "confidence_signal": confidence,
            "emotional_tenor": emotion,
            "intent_marker": intent,
            "friction_log": friction,
            "decision_trace": decision,
            "disclosure_pointer": content_hash
        }
    }


def main():
    print(f"Loading tier4 messages from {TIER4_FILE}...")
    with open(TIER4_FILE, "r") as f:
        tier4_data = json.load(f)

    messages = tier4_data.get("messages", [])
    print(f"Found {len(messages)} tier4 priority messages")

    # Also load user messages for supplementary context
    print(f"Loading user messages from {USER_FILE}...")
    with open(USER_FILE, "r") as f:
        user_data = json.load(f)

    user_messages = user_data.get("messages", [])
    print(f"Found {len(user_messages)} user tier2+ messages")

    # Build index of user messages already in tier4
    tier4_indices = {m["index"] for m in messages}

    # Add user messages not already in tier4
    extra_user = [m for m in user_messages
                  if m["index"] not in tier4_indices and m.get("filter_tier", 0) >= 2]
    print(f"Adding {len(extra_user)} additional user messages from tier2+")

    all_messages = messages + extra_user
    all_messages.sort(key=lambda m: m["index"])

    print(f"Total messages to tag: {len(all_messages)}")

    # Tag each message
    tagged = []
    for msg in all_messages:
        result = tag_message(msg)
        tagged.append(result)

    # Compute distribution stats
    action_dist = {}
    confidence_dist = {}
    emotion_dist = {}
    intent_dist = {}
    friction_count = 0
    decision_count = 0

    for t in tagged:
        p = t["primitives"]
        action_dist[p["action_vector"]] = action_dist.get(p["action_vector"], 0) + 1
        confidence_dist[p["confidence_signal"]] = confidence_dist.get(p["confidence_signal"], 0) + 1
        emotion_dist[p["emotional_tenor"]] = emotion_dist.get(p["emotional_tenor"], 0) + 1
        intent_dist[p["intent_marker"]] = intent_dist.get(p["intent_marker"], 0) + 1
        if p["friction_log"] is not None:
            friction_count += 1
        if p["decision_trace"] is not None:
            decision_count += 1

    output = {
        "session_id": os.getenv("HYPERDOCS_SESSION_ID", ""),
        "total_tagged": len(tagged),
        "distributions": {
            "action_vector": dict(sorted(action_dist.items(), key=lambda x: -x[1])),
            "confidence_signal": dict(sorted(confidence_dist.items(), key=lambda x: -x[1])),
            "emotional_tenor": dict(sorted(emotion_dist.items(), key=lambda x: -x[1])),
            "intent_marker": dict(sorted(intent_dist.items(), key=lambda x: -x[1])),
            "friction_logs": friction_count,
            "decision_traces": decision_count
        },
        "primitives": tagged
    }

    print(f"\nWriting results to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nTagged {len(tagged)} messages")
    print(f"\n--- Distribution Summary ---")
    print(f"\nAction Vector:")
    for k, v in sorted(action_dist.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nConfidence Signal:")
    for k, v in sorted(confidence_dist.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nEmotional Tenor:")
    for k, v in sorted(emotion_dist.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nIntent Marker:")
    for k, v in sorted(intent_dist.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nFriction Logs: {friction_count} / {len(tagged)}")
    print(f"Decision Traces: {decision_count} / {len(tagged)}")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
