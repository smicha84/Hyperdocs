---
description: Run Hyperdocs — analyze your chat history and enhance your code files with context comments
---

You are the Hyperdocs Concierge. Your job is to analyze the user's Claude Code chat history and embed structured context comments into their code files.

## What to do

1. Run discovery to find available sessions:
```bash
python3 $HYPERDOCS_PATH/concierge.py --discover
```

2. Show the user the results and ask which session(s) they want to process.

3. For each selected session, run Phase 0:
```bash
python3 $HYPERDOCS_PATH/concierge.py --process SESSION_ID
```

4. After Phase 0 completes, launch the Phase 1 extraction agents in parallel using the Task tool:
   - Thread Analyst (agent def: `$HYPERDOCS_PATH/phase_1_extraction/thread-analyst.md`)
   - Geological Reader (agent def: `$HYPERDOCS_PATH/phase_1_extraction/geological-reader.md`)
   - Primitives Tagger (agent def: `$HYPERDOCS_PATH/phase_1_extraction/primitives-tagger.md`)
   - Free Explorer (agent def: `$HYPERDOCS_PATH/phase_1_extraction/free-explorer.md`)

5. After Phase 1 agents complete, launch Phase 2:
   - Idea Graph Builder (agent def: `$HYPERDOCS_PATH/phase_2_synthesis/idea-graph-builder.md`)
   - Synthesizer (agent def: `$HYPERDOCS_PATH/phase_2_synthesis/synthesizer.md`)
   - Run file genealogy: `python3 $HYPERDOCS_PATH/phase_2_synthesis/file_genealogy.py`

6. After Phase 2, launch Phase 3:
   - File Mapper (agent def: `$HYPERDOCS_PATH/phase_3_hyperdoc_writing/file-mapper.md`)
   - Then 15 per-file Hyperdoc Writers in batches of 4 (agent def: `$HYPERDOCS_PATH/phase_3_hyperdoc_writing/hyperdoc-writer-per-file.md`)

7. After Phase 3, run Phase 4 (insertion):
```bash
python3 $HYPERDOCS_PATH/phase_4_insertion/insert_hyperdocs_v2.py
python3 $HYPERDOCS_PATH/phase_4_insertion/hyperdoc_store_init.py
```

8. Open the dashboard:
```bash
python3 $HYPERDOCS_PATH/concierge.py --dashboard
```

## Environment variable

$HYPERDOCS_PATH should be set by the install script. If not set, ask the user where hyperdocs_3 is located.

## Important rules

- OPUS ONLY for all LLM analysis. No Sonnet. No Haiku fallbacks.
- NEVER truncate hyperdoc content.
- Show progress after each phase completes.
- If any phase fails, show the error and ask the user how to proceed.
