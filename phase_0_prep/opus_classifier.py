#!/usr/bin/env python3
"""
Opus Message Classifier — Replaces Python tier 1-4 heuristics

Instead of Python guessing importance via keyword matching and character counts,
Opus reads each message in context and determines:
1. Whether this message matters for understanding the session
2. WHY it matters (what category of importance)
3. What it connects to (which files, which ideas, which decisions)

The Python tier system is in standby (message_filter.py). When enough Opus
classifications accumulate across sessions, the patterns will be codified
back into Python rules — but the rules will be LEARNED from Opus, not
hand-crafted from assumptions.

Design: Based on FAIR-RAG gap-driven refinement and the "steak 10 seconds
at a time" principle. Classify in batches. Check quality. Stop when done.

Usage:
    # Classify a sample of messages from a session
    python3 opus_classifier.py --session 0012ebed --sample 30

    # Classify all messages (expensive)
    python3 opus_classifier.py --session 0012ebed --all

    # Compare Opus classifications to Python tier system
    python3 opus_classifier.py --session 0012ebed --compare
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import get_session_output_dir, SESSION_ID
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    def get_session_output_dir():
        return Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output")) / f"session_{SESSION_ID[:8]}"


# ── The Opus Classification Prompt ─────────────────────────────────────────
# This is the core of the system. It replaces 331 lines of keyword matching.

CLASSIFICATION_PROMPT = """You are analyzing messages from a Claude Code chat history session.

For each message, determine its IMPORTANCE for understanding what happened in this session.
Do NOT use length as a proxy for importance. Short messages can be pivotal.

For each message, provide:

1. **importance**: one of:
   - "critical": This message changes the direction of the session, reveals a fundamental insight,
     makes a design decision, or expresses the user's core values/priorities. A future Claude
     MUST know about this message.
   - "significant": This message contributes meaningfully to understanding what happened —
     a technical decision, a completed action, a discovered problem, a frustration event.
   - "context": This message provides background that helps interpret other messages but isn't
     independently important.
   - "noise": Protocol boilerplate, empty acknowledgments, system messages, trivial exchanges
     that add nothing to understanding.

2. **reason**: One sentence explaining WHY this importance level. Be specific.

3. **categories** (list): Which of these apply:
   - "decision": A choice was made (tool, approach, architecture, values)
   - "frustration": User expresses frustration, anger, or disappointment
   - "breakthrough": Something works, a problem is solved, an insight is reached
   - "pivot": Direction changes, approach abandoned, new strategy
   - "file_event": A file is created, modified, deleted, or discussed in depth
   - "behavioral": Reveals a pattern in Claude's behavior (rushing, overconfidence, etc.)
   - "values": User states or enforces a value/priority/constraint
   - "error": An error occurs, a tool fails, something breaks
   - "architectural": System design, module structure, dependency decisions
   - "continuation": Session resumption, context recovery after context window loss

4. **connected_files** (list): Filenames mentioned or implied by this message.

CRITICAL EXAMPLES (short messages that are NOT noise):
- "ONLY OPUS" (11 chars) → critical, values — user establishing a non-negotiable constraint
- "sure" (4 chars) → could be critical if it's agreement to delete a file or accept an architecture
- "stop" (4 chars) → critical, pivot — user halting a direction
- "yes" (3 chars) after "should I delete these imports?" → critical, decision

Respond as a JSON array. One object per message."""


def build_classification_batch(messages: list, batch_size: int = 30) -> list:
    """Build a batch of messages for Opus classification.

    Selects a representative sample that includes:
    - All messages currently classified as tier 1 (the ones Python skips)
      that are near frustration peaks or file events
    - A random sample of each tier for baseline comparison
    - Messages at topic boundaries (where the previous message has different
      files than the next)
    """
    import random

    # Filter out truly empty messages (protocol wrappers with no content)
    non_empty = [m for m in messages if m.get("content_length", 0) > 0 or m.get("content_preview", "")]
    if not non_empty:
        non_empty = messages

    if len(non_empty) <= batch_size:
        return non_empty

    selected_indices = set()

    # 1. Include SHORT USER messages (the ones Python is most likely to misclassify)
    # These are the "ONLY OPUS" / "sure" / "stop" messages that Python skips
    for msg in non_empty:
        if (msg.get("role") == "user"
                and 0 < msg.get("content_length", 0) < 100
                and not msg.get("is_protocol", False)):
            selected_indices.add(msg.get("index", 0))

    # 2. Include tier-1 messages that have SOME content (not empty protocol)
    for msg in non_empty:
        idx = msg.get("index", 0)
        tier = msg.get("filter_tier", 0)
        length = msg.get("content_length", 0)
        if tier == 1 and length > 5 and not msg.get("is_protocol", False):
            selected_indices.add(idx)

    # 3. Sample from each tier for comparison (5 per tier)
    by_tier = {}
    for msg in non_empty:
        t = msg.get("filter_tier", 0)
        if t not in by_tier:
            by_tier[t] = []
        by_tier[t].append(msg)

    for tier, tier_msgs in by_tier.items():
        random.shuffle(tier_msgs)
        for msg in tier_msgs[:5]:
            selected_indices.add(msg.get("index", 0))

    # 4. Include messages near frustration peaks
    frustration_indices = set()
    for msg in non_empty:
        meta = msg.get("metadata", {})
        if meta.get("profanity") or meta.get("caps_ratio", 0) > 0.3:
            frustration_indices.add(msg.get("index", 0))

    for msg in non_empty:
        idx = msg.get("index", 0)
        for window in range(-3, 4):
            if (idx + window) in frustration_indices:
                length = msg.get("content_length", 0)
                if length > 0 and not msg.get("is_protocol", False):
                    selected_indices.add(idx)
                break

    # 5. Trim to batch size, preferring short user messages
    if len(selected_indices) > batch_size:
        # Prioritize: short user msgs > near-frustration > tier samples > rest
        priority = []
        for idx in selected_indices:
            msg = next((m for m in non_empty if m.get("index") == idx), None)
            if not msg:
                continue
            score = 0
            if msg.get("role") == "user" and msg.get("content_length", 0) < 100:
                score += 10  # Short user messages — most likely misclassified
            if idx in frustration_indices or any((idx + w) in frustration_indices for w in range(-3, 4)):
                score += 5
            priority.append((score, idx))
        priority.sort(reverse=True)
        selected_indices = set(idx for _, idx in priority[:batch_size])

    # Build the batch
    idx_to_msg = {msg.get("index", i): msg for i, msg in enumerate(non_empty)}
    batch = [idx_to_msg[idx] for idx in sorted(selected_indices) if idx in idx_to_msg]

    return batch[:batch_size]


def format_messages_for_prompt(messages: list) -> str:
    """Format messages for the Opus classification prompt."""
    lines = []
    for msg in messages:
        idx = msg.get("index", "?")
        role = msg.get("role", "?")
        content = msg.get("content", msg.get("content_preview", ""))
        if len(content) > 500:
            content = content[:500] + "..."
        tier = msg.get("filter_tier", "?")
        length = msg.get("content_length", len(content))

        lines.append(f"[MSG {idx}] role={role} | python_tier={tier} | {length} chars")
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


def classify_with_opus(messages: list, api_key: str = None) -> list:
    """Send messages to Opus for classification. Returns list of classifications."""
    import anthropic

    # Load API key from .env if not in environment
    if not api_key and not os.getenv("ANTHROPIC_API_KEY"):
        for env_path in [
            Path(__file__).resolve().parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent.parent.parent.parent / ".env",
        ]:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip()
                break

    client = anthropic.Anthropic(api_key=api_key)

    formatted = format_messages_for_prompt(messages)
    user_prompt = f"""Classify these {len(messages)} messages. Return a JSON array with one object per message.

{formatted}

Return ONLY the JSON array. Each object must have: msg_index, importance, reason, categories, connected_files."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=16000,
        temperature=0.2,
        messages=[
            {"role": "user", "content": CLASSIFICATION_PROMPT + "\n\n" + user_prompt}
        ],
    )

    # Parse the response
    text = response.content[0].text
    # Find JSON array in the response
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    return []


def compare_classifications(messages: list, opus_results: list) -> dict:
    """Compare Opus classifications to Python tier system."""
    opus_by_idx = {r.get("msg_index", i): r for i, r in enumerate(opus_results)}

    upgrades = []  # Python said skip, Opus says important
    downgrades = []  # Python said priority, Opus says noise
    agreements = []
    disagreements = []

    for msg in messages:
        idx = msg.get("index", 0)
        python_tier = msg.get("filter_tier", 0)
        opus = opus_by_idx.get(idx)
        if not opus:
            continue

        opus_importance = opus.get("importance", "noise")

        # Map Opus importance to equivalent tier
        opus_tier = {"critical": 4, "significant": 3, "context": 2, "noise": 1}.get(opus_importance, 1)

        if python_tier <= 1 and opus_tier >= 3:
            upgrades.append({
                "msg_index": idx,
                "content_preview": str(msg.get("content", msg.get("content_preview", "")))[:100],
                "python_tier": python_tier,
                "opus_importance": opus_importance,
                "opus_reason": opus.get("reason", ""),
                "opus_categories": opus.get("categories", []),
            })
        elif python_tier >= 3 and opus_tier <= 1:
            downgrades.append({
                "msg_index": idx,
                "content_preview": str(msg.get("content", msg.get("content_preview", "")))[:100],
                "python_tier": python_tier,
                "opus_importance": opus_importance,
                "opus_reason": opus.get("reason", ""),
            })
        elif abs(python_tier - opus_tier) <= 1:
            agreements.append(idx)
        else:
            disagreements.append({
                "msg_index": idx,
                "python_tier": python_tier,
                "opus_tier": opus_tier,
                "opus_importance": opus_importance,
            })

    return {
        "total_compared": len(messages),
        "agreements": len(agreements),
        "disagreements": len(disagreements),
        "upgrades": upgrades,
        "downgrades": downgrades,
        "agreement_rate": round(len(agreements) / len(messages), 2) if messages else 0,
        "upgrade_count": len(upgrades),
        "downgrade_count": len(downgrades),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Opus Message Classifier")
    parser.add_argument("--session", default="", help="Session ID")
    parser.add_argument("--dir", default="", help="Session output directory")
    parser.add_argument("--sample", type=int, default=30, help="Number of messages to classify")
    parser.add_argument("--all", action="store_true", help="Classify all messages (expensive)")
    parser.add_argument("--compare", action="store_true", help="Compare Opus vs Python classifications")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be classified without calling Opus")
    args = parser.parse_args()

    # Determine session directory
    if args.dir:
        session_dir = Path(args.dir)
    elif args.session:
        candidates = [
            Path(__file__).resolve().parent.parent / "output" / f"session_{args.session[:8]}",
            Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{args.session[:8]}",
        ]
        session_dir = next((c for c in candidates if c.exists()), candidates[0])
    else:
        session_dir = get_session_output_dir()

    print("=" * 60)
    print("Opus Message Classifier")
    print("=" * 60)
    print(f"Session dir: {session_dir}")

    # Load enriched session (prefer v2 with LLM pass data when available)
    enriched_v2 = session_dir / "enriched_session_v2.json"
    enriched_path = enriched_v2 if enriched_v2.exists() else session_dir / "enriched_session.json"
    if not enriched_path.exists():
        print(f"ERROR: enriched_session.json not found in {session_dir}")
        sys.exit(1)

    data = json.loads(enriched_path.read_text())
    messages = data.get("messages", [])
    print(f"Total messages: {len(messages)}")

    # Build batch
    if args.all:
        batch = messages
    else:
        batch = build_classification_batch(messages, args.sample)

    print(f"Batch size: {len(batch)}")

    # Show tier distribution of the batch
    tier_dist = {}
    for msg in batch:
        t = msg.get("filter_tier", 0)
        tier_dist[t] = tier_dist.get(t, 0) + 1
    print(f"Batch tier distribution: {json.dumps(tier_dist)}")

    # Count short user messages in batch
    short_user = sum(1 for m in batch if m.get("role") == "user" and m.get("content_length", 0) < 50)
    print(f"Short user messages (< 50 chars): {short_user}")
    print()

    if args.dry_run:
        print("=== DRY RUN — Messages that would be classified ===")
        for msg in batch:
            idx = msg.get("index", "?")
            role = msg.get("role", "?")
            tier = msg.get("filter_tier", "?")
            length = msg.get("content_length", 0)
            preview = str(msg.get("content", msg.get("content_preview", "")))[:80]
            print(f"  [{idx:>4d}] tier={tier} {role:>9s} {length:>5d}ch  {preview}")
        print(f"\nTo actually classify, remove --dry-run.")
        print(f"Estimated cost: ~${len(batch) * 0.003:.2f} (batch of {len(batch)} messages)")
        return

    # Call Opus — batch into chunks of 50 to avoid output truncation
    CHUNK_SIZE = 50
    results = []
    total_chunks = (len(batch) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"Calling Opus for classification ({total_chunks} chunks of {CHUNK_SIZE})...")

    for i in range(0, len(batch), CHUNK_SIZE):
        chunk = batch[i:i + CHUNK_SIZE]
        chunk_num = i // CHUNK_SIZE + 1
        print(f"  Chunk {chunk_num}/{total_chunks}: {len(chunk)} messages...", end=" ", flush=True)
        try:
            chunk_results = classify_with_opus(chunk)
            results.extend(chunk_results)
            print(f"got {len(chunk_results)}")
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e} — skipping chunk")
        except (KeyError, TypeError, ValueError, OSError) as e:
            print(f"Error: {e} — skipping chunk")

    print(f"Total classifications: {len(results)}")

    # Save results
    output = {
        "session_id": args.session or session_dir.name.replace("session_", ""),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "opus_classifier.py",
        "batch_size": len(batch),
        "total_session_messages": len(messages),
        "classifications": results,
    }

    out_path = session_dir / "opus_classifications.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Written: {out_path}")

    # Compare if requested
    if args.compare:
        comparison = compare_classifications(batch, results)
        print(f"\n=== COMPARISON: Opus vs Python ===")
        print(f"Agreement rate: {comparison['agreement_rate']:.0%}")
        print(f"Upgrades (Python skipped, Opus says important): {comparison['upgrade_count']}")
        print(f"Downgrades (Python prioritized, Opus says noise): {comparison['downgrade_count']}")

        if comparison['upgrades']:
            print(f"\nMost significant upgrades:")
            for u in comparison['upgrades'][:5]:
                print(f"  msg {u['msg_index']}: python_tier={u['python_tier']} → opus={u['opus_importance']}")
                print(f"    {u['content_preview']}")
                print(f"    Reason: {u['opus_reason']}")
                print()

        comp_path = session_dir / "opus_vs_python_comparison.json"
        with open(comp_path, "w") as f:
            json.dump(comparison, f, indent=2, default=str)
        print(f"Comparison written: {comp_path}")


if __name__ == "__main__":
    main()
