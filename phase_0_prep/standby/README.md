# Standby Code

Files here are working code that has been temporarily replaced by Opus-driven equivalents.

Once enough Opus classifications accumulate, the patterns will be studied and codified back into Python. These files will then be updated with learned rules (not hand-crafted heuristics).

## Current standby files:
- `message_filter.py` — Python tier 1-4 classification (replaced by opus_classifier.py)
  - Moved: Feb 20, 2026
  - Reason: Tier system uses character count + keyword matching. Misses short strategic messages like "ONLY OPUS" (11 chars → tier 1 → skipped). Opus handles context-dependent importance.
  - Return condition: When Opus classifications across 50+ sessions reveal codifiable patterns
