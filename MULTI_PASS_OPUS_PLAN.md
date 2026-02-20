# Phase 0 Redesign — Multi-Pass Opus Analysis via Batch API

**Status:** SAVED — Execution blocked until March 1, 2026 (usage budget reinstatement)
**Created:** February 19, 2026
**Last updated:** February 19, 2026

---

## Context

The 4-tier message filtering system was designed to save money by skipping "unimportant" messages. But skipping messages means losing context. A one-word "sure" at tier 1 might be the user agreeing to a design decision that reshapes the entire session. The tier system optimizes for cost at the expense of understanding.

The new architecture: Opus reads ALL messages. No tier filtering. Python preprocessing handles only the mechanical work that Opus shouldn't waste time on. Opus does multiple read-throughs of each session, building deeper understanding with each pass. The accumulated understanding from all 165 sessions becomes a "system recipe" — a prompt template that can extract the same information from future sessions efficiently.

Execution model: Anthropic Batch API. No rate limit concerns. 24-hour turnaround per batch. Separate infrastructure from real-time API.

## What Python Preprocessing Must Do (Before Opus Sees Anything)

These are the precursors that Opus genuinely cannot do or shouldn't waste tokens on:

1. **Protocol detection** — Identify which messages are system-generated wrappers (XML tags, /clear boilerplate, skill injections, subagent relays, empty tool-result delimiters). Without this, Opus would analyze boilerplate as if a human wrote it.

2. **Char-per-line collapse** — Some messages arrive encoded with one character per line (a Claude Code artifact). These are literally unreadable until collapsed. Example: `H\ne\nl\nl\no` → `Hello`.

3. **Subagent detection** — Determine if this is a human conversation or an automated subagent session (memory agent, observer agent, task agent). Three strategies: session ID pattern, filename pattern, first-message content analysis.

4. **Profanity sanitization** — Replace strong language with `[expletive]`. Required because Anthropic's content policy blocks API requests containing raw profanity. Without this, Opus literally cannot read the session.

5. **Structural annotation** — Attach basic facts Opus can see at a glance: message index, role, timestamp, content length, whether code blocks are present. This is $0 and saves Opus from counting characters or parsing timestamps.

### What gets DROPPED from the current Phase 0:
- The 4-tier classification system (the whole point is Opus reads everything)
- The 20-pattern regex behavior analyzer (Opus will do deeper analysis)
- The 7-category keyword scoring (Opus doesn't need keyword counts)
- The content-referential detection (Opus will understand context naturally)
- The metadata extractor's file/error/terminal regex patterns (optional — could keep as helpful annotations since they're $0, but Opus doesn't need them)

## The Dependency Chain

The user's key insight: extractions have logical dependencies. You can't detect "Claude went off on a tangent" without first establishing a chain of prior facts.

Here's the chain, from foundation to complex inference:

```
Level 0 — Physical Facts (Python, $0)
  "Is this readable?" → char-per-line collapse
  "Is this a real message?" → protocol detection
  "Is this a human conversation?" → subagent detection
  "Is this safe to send to the API?" → profanity sanitization

Level 1 — Who Said What (Opus, first read)
  "Who is the message creator?" → role + protocol status
  "What is the user telling Claude to do?" → intent extraction
  "What is Claude trying to do?" → response classification

Level 2 — Alignment (Opus, builds on Level 1)
  "Did Claude do what was asked?" → compare intent vs action
  "Where did Claude diverge?" → tangent detection
  "What decisions did Claude make silently?" → implicit choice detection

Level 3 — Patterns (Opus, builds on Level 2)
  "What behavioral patterns emerge?" → across multiple exchanges
  "How do ideas evolve across the session?" → idea tracking
  "What's the emotional arc?" → frustration/breakthrough dynamics

Level 4 — Meta (Opus, builds on everything)
  "What's missing from the analysis?" → gap detection
  "What would a system need to extract all of this?" → the recipe
```

Each level requires the prior levels as input. This is why multiple passes matter — not because Opus can't hold the session in memory, but because deeper inferences require foundational facts to already be established.

## The Data: 165 Unique Sessions

- Median session: 59 messages, ~4,581 tokens
- 75th percentile: 99 messages, ~9,000 tokens
- Largest: 16,297 messages, ~3.2M tokens
- 96% of sessions fit in 200K context window
- 99% fit in 1M context window (only 2 sessions don't)
- Total across all sessions: 84,574 messages, ~10.8M tokens

Most sessions are small enough that Opus can absorb the entire thing in a single read with massive room to spare.

## Design Decisions (for user)

### Decision 1: What should the 10 lenses focus on?

Proposed 10 lenses (each pass reads the full session with accumulated notes from prior passes):

1. **Narrative** — What happened, start to finish? Major phases, transitions, time gaps.
2. **Intent & Alignment** — For each user→assistant exchange: what was asked, what was done, where did they diverge?
3. **Decision Inventory** — Every decision made: who made it, was it explicit or implicit, was it presented as a choice?
4. **Emotional Dynamics** — User's emotional state throughout. Frustration peaks. Breakthroughs. What triggered each shift.
5. **Behavioral Patterns** — Claude's patterns: overconfidence, assumptions, scope creep, premature completion, silent decisions.
6. **Idea Evolution** — Ideas that emerged, evolved, split, merged, died. The idea graph.
7. **File & Code Activity** — What happened to each file. Architecture decisions. Code patterns.
8. **Errors & Recovery** — What went wrong, how each error was handled, what was learned, what repeated.
9. **Gap Analysis** — What's missing from lenses 1-8? What was overlooked? What patterns weren't captured?
10. **The System** — Given everything from all 9 lenses: what would a prompt need to extract all of this from any future session in a single pass?

Lens 10 is the "recipe" — the meta-output that turns expensive historical analysis into efficient future processing.

### Decision 2: Execution structure

**Option A — Single-call per session (1 batch, ~1 day)**
Send the full session to Opus in one prompt, ask it to analyze through all 10 lenses in sequence. Works for 96% of sessions (under 200K tokens). For the 2 huge sessions, chunk into multiple calls.

Pro: Fastest, simplest. Opus maintains full context across all lenses.
Con: Opus might not go as deep on each lens because it's doing all 10 at once.

**Option B — 3 sequential batches (~3 days)**
Batch 1: Lenses 1-3 (narrative, alignment, decisions)
Batch 2: Lenses 4-7 (emotion, behavior, ideas, files) — includes notes from Batch 1
Batch 3: Lenses 8-10 (errors, gaps, the system) — includes notes from Batches 1+2

Pro: Each batch goes deeper because it's focused on fewer lenses. Notes accumulate.
Con: Takes 3 days. Session data re-read each time (but that's fine for rate limits).

**Option C — 10 sequential batches (~10 days)**
One lens per batch. Maximum depth per lens. Each batch includes all prior notes.

Pro: Deepest possible analysis. Each lens gets Opus's full attention.
Con: Takes 10 days. Most sessions are tiny enough that this depth is overkill.

### Decision 3: What to keep as $0 annotations

The existing Python metadata extraction (files mentioned, error types, terminal activity, etc.) costs nothing and produces 34 fields per message. These could be passed to Opus as "here's what the regex found, verify and build on it" — or they could be dropped entirely and let Opus do everything from scratch.

Options:
- **Keep as annotations**: Gives Opus a head start. $0 additional cost.
- **Drop entirely**: Cleaner input. Opus might spot things the regex missed (but also might miss things the regex caught).
- **Keep but label as "unverified hints"**: Tell Opus these are regex extractions that may have false positives/negatives.

## Implementation Steps

| Step | What | Details |
|------|------|---------|
| 1 | Slim down deterministic_prep.py | Keep only: protocol detection, char-per-line collapse, subagent detection, sanitization, structural annotations. Remove tier classification and behavior regex. |
| 2 | Build Batch API client | Script that creates batch requests, submits them, polls for completion, downloads results. Uses `client.beta.messages.batches.create()`. |
| 3 | Build the 10-lens prompt templates | One system prompt + user template per lens. Each template includes a slot for notes from prior lenses. |
| 4 | Test on 1 session | Run all 10 lenses on session_0012ebed. Verify output quality. |
| 5 | Build the batch orchestrator | Submits all 165 sessions as a batch, tracks progress, handles results. |
| 6 | Run on all 165 sessions | Submit batch(es), wait for results, collect outputs. |
| 7 | Synthesize the "system recipe" | Analyze lens 10 outputs across all sessions to distill the universal prompt template. |

## Files to Modify/Create

- `phase_0_prep/deterministic_prep_slim.py` — Stripped-down Phase 0 (protocol + collapse + subagent + sanitize only)
- `phase_0_prep/batch_api_client.py` — Batch API submission, polling, result collection
- `phase_0_prep/lens_prompts.py` — 10 lens prompt templates
- `phase_0_prep/multi_pass_orchestrator.py` — Orchestrates the full multi-lens pipeline across all sessions
- `phase_0_prep/recipe_synthesizer.py` — Collects lens 10 outputs and distills the universal extraction prompt

## Verification

1. Run the slimmed-down Phase 0 on session_0012ebed, confirm it produces clean annotated output
2. Run all 10 lenses on session_0012ebed via real-time API (not batch — for fast iteration)
3. Read the lens 10 output and evaluate: does it actually describe a system that could extract everything?
4. Submit a 5-session test batch, verify batch mechanics work
5. Submit full 165-session batch, collect results
6. Read lens 10 outputs across sessions, synthesize the recipe
