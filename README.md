# Hyperdocs

A system that reads Claude Code chat history and writes the truth into code files.

**Input:** Any Claude Code chat history (`.jsonl` file)
**Output:** Your project's code files enhanced with hyperdoc comments — structured context that tells a future AI what happened, what went wrong, what decisions were made, and what was never verified.

## What it does

When you work with Claude Code, your conversation is a rich record of decisions, mistakes, fixes, and frustrations. But the next session starts from zero. Hyperdocs extracts that knowledge and embeds it directly into your code as structured comments:

```python
# @ctx:state=proven @ctx:confidence=high-regression-risk @ctx:emotion=relieved
# @ctx:friction="opus_parse_message() called Opus at $0.05/line for JSON traversal
#   that pure Python does for free. Fixed with deterministic_parse_message()."
# @ctx:decision="chose Python json.loads() over Opus because V1 proved it works"
# @ctx:trace=conv_3b7084d5:msg2272
def deterministic_parse_message(raw_line):
    ...
```

A future Claude reading this file — with no chat history, no memory, no prior sessions — now knows: this function replaced an expensive bug, the user discovered the fix, and pure Python was chosen over LLM calls for a specific reason.

## The 6-Phase Pipeline

| Phase | What | How | Cost |
|-------|------|-----|------|
| **0** | Deterministic Prep | Pure Python metadata extraction, 4-tier message classification | Free |
| **1** | Parallel Extraction | 4 agents: threads, geological layers, semantic primitives, free exploration | Opus |
| **2** | Synthesis | Idea evolution graph + 6-pass temperature-ramped analysis | Opus |
| **3** | Hyperdoc Writing | Per-file dossiers, then one dedicated agent per file writes header + inline + footer | Opus |
| **4** | Smart Insertion | AST-based placement into code files + versioned storage | Free |
| **5** | Ground Truth | Python verifies claims against actual code state — the gap = the lie | Free |

## Quick Start

```bash
# Clone
git clone https://github.com/smicha84/Hyperdocs.git
cd Hyperdocs

# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env: add your ANTHROPIC_API_KEY and set HYPERDOCS_SESSION_ID or HYPERDOCS_CHAT_HISTORY

# Run Phase 0 (free, no API calls)
python3 phase_0_prep/deterministic_prep.py
python3 phase_0_prep/prepare_agent_data.py
```

Phases 1-3 require Claude Code to launch the agents. See `HYPERDOCS_3_SYSTEM_GUIDE.html` for the full walkthrough.

## Configuration

Set these environment variables (or edit `config.py`):

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (phases 1-3) | Your Anthropic API key |
| `HYPERDOCS_SESSION_ID` | One of these | Claude Code session UUID |
| `HYPERDOCS_CHAT_HISTORY` | required | Path to `.jsonl` file |
| `HYPERDOCS_OUTPUT_DIR` | No | Output directory (default: `./output`) |

## File Structure

```
Hyperdocs/
├── config.py                        — Central configuration
├── phase_0_prep/                    — Deterministic prep (7 files, pure Python)
├── phase_1_extraction/              — 4 parallel agents + helper scripts (6 files)
├── phase_2_synthesis/               — Idea graph + synthesizer agents (2 files)
├── phase_3_hyperdoc_writing/        — File mapper + per-file writers (7 files)
├── phase_4_insertion/               — AST-based insertion + versioned store (3 files)
├── phase_5_ground_truth/            — Claim verification (3 files)
├── examples/                        — Sample input data
└── HYPERDOCS_3_SYSTEM_GUIDE.html    — Visual system guide (open in browser)
```

28 system files. 19 Python scripts. 9 agent definitions.

## The Seven Semantic Primitives

Every analyzable message gets tagged with 7 dimensions:

1. **Action Vector:** created | modified | debugged | refactored | discovered | decided | abandoned | reverted
2. **Confidence Signal:** experimental | tentative | working | stable | proven | fragile
3. **Emotional Tenor:** frustrated | uncertain | curious | cautious | confident | excited | relieved
4. **Intent Marker:** correctness | performance | maintainability | feature | bugfix | exploration | cleanup
5. **Friction Log:** Single compressed sentence describing what went wrong
6. **Decision Trace:** "chose X over Y because Z"
7. **Disclosure Pointer:** Hash reference to full context

## Ground Truth Verification

Phase 5 independently verifies claims using Python's AST, regex, and importlib — not Claude self-reporting. It checks for:

- Bare `except:` blocks (claimed fixed but still present?)
- Unsafe API access patterns
- Hardcoded truncation limits
- Model string violations (Sonnet where Opus was promised)
- Missing functions (claimed implemented but not found)
- Broad exception handlers

The result is a per-file **credibility score**: verified claims / total claims. The gap between what Claude said and what Python found is the measured lie rate.

## License

MIT
