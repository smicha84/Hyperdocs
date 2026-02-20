#!/usr/bin/env python3
"""
Phase 0 LLM Pass Runner
========================

Core infrastructure for running LLM passes on enriched session data.
Loads enriched_session.json, filters messages per pass, batches into
prompts within context window limits, calls specified model, parses
JSON responses, retries on errors, and writes per-pass output JSON.

Usage:
    # Run a single pass on a single session
    python3 llm_pass_runner.py --pass 1 --session session_0012ebed

    # Run all passes on a single session
    python3 llm_pass_runner.py --pass all --session session_0012ebed

    # Dry run (show what would be processed, no API calls)
    python3 llm_pass_runner.py --pass 1 --session session_0012ebed --dry-run
"""

import os
import sys
import json
import time
import argparse
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

# ── Path setup ────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Load API key from .env file — check multiple locations
# (hyperdocs_3/.env, project root .env, ~/Hyperdocs/.env)
ENV_CANDIDATES = [
    REPO / ".env",
    REPO.parent.parent.parent.parent.parent / ".env",  # project root
    Path.home() / "Hyperdocs" / ".env",
]
for env_path in ENV_CANDIDATES:
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key.strip() not in os.environ:  # don't override existing
                    os.environ[key.strip()] = val.strip()
        break  # use first found

import anthropic
client = anthropic.Anthropic()

from config import OUTPUT_DIR as DEFAULT_OUTPUT_DIR

# Import prompts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompts import PASS_CONFIGS, format_messages_for_prompt, format_messages_with_context

# ── Constants ─────────────────────────────────────────────────────────

# Approximate token-per-char ratio (conservative: 1 token per 3.5 chars)
CHARS_PER_TOKEN = 3.5

# Leave headroom for system prompt + response
HAIKU_CONTEXT_LIMIT = 180_000   # tokens (200K window minus headroom)
OPUS_CONTEXT_LIMIT = 180_000    # tokens

# Maximum messages per API call batch
MAX_BATCH_SIZE = 40

# Maximum output tokens per call
MAX_OUTPUT_TOKENS = 16_000

# Retry config
MAX_RETRIES = 3
RETRY_DELAY_BASE = 5  # seconds


# ── Cost tracking ─────────────────────────────────────────────────────

# Prices per million tokens (as of Feb 2026)
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6-20250514": {"input": 15.00, "output": 75.00},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost in dollars."""
    prices = PRICING.get(model, {"input": 15.0, "output": 75.0})
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


# ── Session loading ───────────────────────────────────────────────────

def find_session_dir(session_name: str) -> Optional[Path]:
    """Find the output directory for a session."""
    # Check both output locations
    for base in [
        DEFAULT_OUTPUT_DIR,
        Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS"))) / "sessions",
    ]:
        candidate = base / session_name
        if candidate.exists() and (candidate / "enriched_session.json").exists():
            return candidate
        # Try with session_ prefix
        if not session_name.startswith("session_"):
            candidate = base / f"session_{session_name}"
            if candidate.exists() and (candidate / "enriched_session.json").exists():
                return candidate
    return None


def load_enriched_session(session_dir: Path) -> Dict:
    """Load enriched_session.json for a session."""
    path = session_dir / "enriched_session.json"
    with open(path) as f:
        return json.load(f)


# ── Message filtering ─────────────────────────────────────────────────

def filter_messages_for_pass(messages: List[Dict], pass_num: int,
                             pass1_results: Optional[Dict] = None) -> List[Dict]:
    """Filter messages for a specific pass.

    Pass 1, 2, 4: Use the pass config's filter function
    Pass 3: Only messages flagged by Pass 1 with any assumption subtype
    """
    config = PASS_CONFIGS[pass_num]

    if pass_num == 3:
        # Pass 3: only messages flagged by Pass 1 as having assumptions
        if not pass1_results:
            return []
        flagged_indices = set()
        for result in pass1_results.get("results", []):
            if any([
                result.get("code_assumption"),
                result.get("format_assumption"),
                result.get("direction_assumption"),
                result.get("scope_assumption"),
            ]):
                flagged_indices.add(result.get("index"))
        return [m for m in messages if m.get("index") in flagged_indices]

    filter_fn = config["message_filter"]
    if filter_fn is None:
        return messages
    return [m for m in messages if filter_fn(m)]


# ── Batching ──────────────────────────────────────────────────────────

def estimate_message_tokens(msg: Dict) -> int:
    """Estimate token count for a message in the prompt."""
    content = msg.get("content", "")
    # Account for message header + content
    overhead = 50  # "--- Message X (role) ---\n"
    return int((len(content) + overhead) / CHARS_PER_TOKEN)


def batch_messages(messages: List[Dict], model: str,
                   system_prompt: str) -> List[List[Dict]]:
    """Split messages into batches that fit within context window.

    Each batch will become one API call. We need:
    system_prompt_tokens + user_prompt_tokens + output_tokens < context_limit
    """
    context_limit = OPUS_CONTEXT_LIMIT if "opus" in model else HAIKU_CONTEXT_LIMIT

    # Reserve tokens for system prompt and output
    system_tokens = int(len(system_prompt) / CHARS_PER_TOKEN)
    template_overhead = 500  # tokens for the template text around messages
    reserved = system_tokens + template_overhead + MAX_OUTPUT_TOKENS
    available = context_limit - reserved

    batches = []
    current_batch = []
    current_tokens = 0

    for msg in messages:
        msg_tokens = estimate_message_tokens(msg)

        # Would this message push us over?
        if current_tokens + msg_tokens > available and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(msg)
        current_tokens += msg_tokens

        # Also enforce max batch size for response parsing reliability
        if len(current_batch) >= MAX_BATCH_SIZE:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

    if current_batch:
        batches.append(current_batch)

    return batches


# ── API calling ───────────────────────────────────────────────────────

def parse_json_response(text: str) -> List[Dict]:
    """Parse JSON array from LLM response, handling common formatting issues."""
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        # Remove closing fence
        text = re.sub(r'\n?```\s*$', '', text)
        text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except json.JSONDecodeError:
        pass

    # Try to find JSON array in the text
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Last resort: try to fix common issues
    # Sometimes the model outputs individual objects separated by newlines
    objects = []
    for line in text.split('\n'):
        line = line.strip().rstrip(',')
        if line.startswith('{') and line.endswith('}'):
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if objects:
        return objects

    return []


def call_api(model: str, system_prompt: str, user_prompt: str,
             batch_num: int = 0, total_batches: int = 0) -> Tuple[List[Dict], Dict]:
    """Call the Anthropic API with retry logic.

    Returns:
        (parsed_results, usage_dict)
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "retries": 0}

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Track usage
            usage["input_tokens"] = response.usage.input_tokens
            usage["output_tokens"] = response.usage.output_tokens
            usage["cost"] = estimate_cost(model, response.usage.input_tokens,
                                          response.usage.output_tokens)

            # Parse response
            response_text = response.content[0].text if response.content else ""
            results = parse_json_response(response_text)

            if not results:
                print(f"    WARNING: Empty/unparseable response for batch {batch_num}. "
                      f"Response preview: {response_text[:200]}")
                usage["retries"] = attempt + 1
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_BASE * (attempt + 1))
                    continue

            return results, usage

        except anthropic.RateLimitError as e:
            usage["retries"] = attempt + 1
            wait = RETRY_DELAY_BASE * (2 ** attempt)
            print(f"    Rate limited (batch {batch_num}/{total_batches}). "
                  f"Waiting {wait}s... (attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(wait)

        except anthropic.APIError as e:
            usage["retries"] = attempt + 1
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY_BASE * (attempt + 1)
                print(f"    API error: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"    FAILED after {MAX_RETRIES} attempts: {e}")
                return [], usage

    return [], usage


# ── Pass execution ────────────────────────────────────────────────────

def run_pass(pass_num: int, session_dir: Path, data: Dict,
             pass1_results: Optional[Dict] = None,
             dry_run: bool = False) -> Dict:
    """Run a single LLM pass on a session.

    Args:
        pass_num: Pass number (1-4)
        session_dir: Path to session output directory
        data: Loaded enriched_session.json
        pass1_results: Results from Pass 1 (needed for Pass 3)
        dry_run: If True, show what would be processed but don't call API

    Returns:
        Dict with results, usage, and metadata
    """
    config = PASS_CONFIGS[pass_num]
    messages = data.get("messages", [])
    session_id = data.get("session_id", "unknown")

    print(f"\n  Pass {pass_num}: {config['name']}")
    print(f"    Model: {config['model']}")

    # Filter messages
    filtered = filter_messages_for_pass(messages, pass_num, pass1_results)
    print(f"    Messages to analyze: {len(filtered)} (of {len(messages)} total)")

    if not filtered:
        print(f"    No messages to analyze — skipping")
        return {
            "pass": pass_num,
            "session_id": session_id,
            "model": config["model"],
            "messages_analyzed": 0,
            "results": [],
            "total_usage": {"input_tokens": 0, "output_tokens": 0, "cost": 0.0},
        }

    if dry_run:
        # Estimate cost without calling API
        total_chars = sum(len(m.get("content", "")) for m in filtered)
        est_input_tokens = int(total_chars / CHARS_PER_TOKEN) + 2000  # overhead
        est_output_tokens = len(filtered) * 200  # ~200 tokens per result
        est_cost = estimate_cost(config["model"], est_input_tokens, est_output_tokens)
        print(f"    [DRY RUN] Estimated: ~{est_input_tokens:,} input tokens, "
              f"~{est_output_tokens:,} output tokens, ~${est_cost:.3f}")
        return {
            "pass": pass_num,
            "session_id": session_id,
            "model": config["model"],
            "messages_analyzed": len(filtered),
            "results": [],
            "dry_run": True,
            "estimated_cost": est_cost,
        }

    # Batch messages
    batches = batch_messages(filtered, config["model"], config["system_prompt"])
    print(f"    Batches: {len(batches)} (max {MAX_BATCH_SIZE} msgs/batch)")

    # Process each batch
    all_results = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "api_calls": 0}

    for i, batch in enumerate(batches):
        # Build prompt
        if config["needs_user_context"]:
            formatted = format_messages_with_context(batch, messages)
        else:
            formatted = format_messages_for_prompt(batch)

        user_prompt = config["user_template"].format(messages=formatted)

        # Call API
        results, usage = call_api(
            config["model"], config["system_prompt"], user_prompt,
            batch_num=i + 1, total_batches=len(batches)
        )

        all_results.extend(results)
        total_usage["input_tokens"] += usage["input_tokens"]
        total_usage["output_tokens"] += usage["output_tokens"]
        total_usage["cost"] += usage["cost"]
        total_usage["api_calls"] += 1

        print(f"    Batch {i+1}/{len(batches)}: {len(results)} results, "
              f"${usage['cost']:.4f}")

        # Small delay between batches to avoid rate limiting
        if i < len(batches) - 1:
            time.sleep(1)

    print(f"    Total: {len(all_results)} results, ${total_usage['cost']:.4f}")

    # Build output
    output = {
        "pass": pass_num,
        "pass_name": config["name"],
        "session_id": session_id,
        "model": config["model"],
        "messages_analyzed": len(filtered),
        "results_count": len(all_results),
        "results": all_results,
        "total_usage": total_usage,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write output file
    output_file = session_dir / config["output_file"]
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"    Output: {output_file.name} ({output_file.stat().st_size / 1024:.1f} KB)")

    return output


def run_all_passes(session_dir: Path, dry_run: bool = False,
                   passes: Optional[List[int]] = None) -> Dict:
    """Run all (or specified) LLM passes on a session.

    Args:
        session_dir: Path to session output directory
        dry_run: If True, estimate costs without calling API
        passes: List of pass numbers to run (default: all 4)

    Returns:
        Dict with combined results and usage
    """
    passes = passes or [1, 2, 3, 4]
    data = load_enriched_session(session_dir)
    session_id = data.get("session_id", "unknown")

    print(f"\n{'=' * 60}")
    print(f"Phase 0 LLM Passes — Session {session_id}")
    print(f"{'=' * 60}")
    print(f"Session dir: {session_dir}")
    print(f"Messages: {len(data.get('messages', []))}")
    print(f"Passes to run: {passes}")

    results = {}
    total_cost = 0.0

    # Pass 1 must run before Pass 3
    pass1_results = None

    for pass_num in passes:
        # Load existing Pass 1 results if we're running Pass 3 without Pass 1
        if pass_num == 3 and pass1_results is None:
            p1_file = session_dir / PASS_CONFIGS[1]["output_file"]
            if p1_file.exists():
                with open(p1_file) as f:
                    pass1_results = json.load(f)
            else:
                print(f"\n  Pass 3 skipped: Pass 1 results not available")
                continue

        result = run_pass(pass_num, session_dir, data,
                         pass1_results=pass1_results, dry_run=dry_run)
        results[pass_num] = result
        total_cost += result.get("total_usage", {}).get("cost", 0.0)

        # Save Pass 1 results for Pass 3
        if pass_num == 1:
            pass1_results = result

    print(f"\n{'=' * 60}")
    if dry_run:
        print(f"DRY RUN COMPLETE — Estimated total cost: ${total_cost:.4f}")
    else:
        print(f"ALL PASSES COMPLETE — Total cost: ${total_cost:.4f}")
    print(f"{'=' * 60}")

    return {
        "session_id": session_id,
        "passes": {str(k): v for k, v in results.items()},
        "total_cost": total_cost,
        "dry_run": dry_run,
    }


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Phase 0 LLM Pass Runner — Run behavioral analysis passes"
    )
    parser.add_argument("--pass", dest="pass_num", required=True,
                       help="Pass number (1-4) or 'all'")
    parser.add_argument("--session", required=True,
                       help="Session directory name (e.g., session_0012ebed)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Estimate costs without calling API")

    args = parser.parse_args()

    # Find session
    session_dir = find_session_dir(args.session)
    if not session_dir:
        print(f"ERROR: Session not found: {args.session}")
        print(f"Searched in: {DEFAULT_OUTPUT_DIR}")
        print(f"             {Path(os.getenv('HYPERDOCS_STORE_DIR', str(Path.home() / 'PERMANENT_HYPERDOCS'))) / 'sessions'}")
        sys.exit(1)

    if args.pass_num == "all":
        run_all_passes(session_dir, dry_run=args.dry_run)
    else:
        try:
            pass_num = int(args.pass_num)
        except ValueError:
            print(f"ERROR: Invalid pass number: {args.pass_num}")
            sys.exit(1)

        if pass_num not in PASS_CONFIGS:
            print(f"ERROR: Pass {pass_num} not found. Valid: {list(PASS_CONFIGS.keys())}")
            sys.exit(1)

        data = load_enriched_session(session_dir)

        # Pass 3 needs Pass 1 results
        pass1_results = None
        if pass_num == 3:
            p1_file = session_dir / PASS_CONFIGS[1]["output_file"]
            if p1_file.exists():
                with open(p1_file) as f:
                    pass1_results = json.load(f)
            else:
                print("ERROR: Pass 3 requires Pass 1 results. Run Pass 1 first.")
                sys.exit(1)

        run_pass(pass_num, session_dir, data, pass1_results=pass1_results,
                 dry_run=args.dry_run)


if __name__ == "__main__":
    main()
