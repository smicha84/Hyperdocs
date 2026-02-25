# Hyperdocs Troubleshooting

## Common errors

### "ANTHROPIC_API_KEY not set"

**Symptom:** Phase 0c (Opus classifier) or Phase 1 (Opus extraction) skips or fails.

**Fix:** Create a `.env` file in the Hyperdocs root directory:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Or set it as an environment variable:
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### "Session directory not found"

**Symptom:** `hyperdocs process SESSION_ID` says the session doesn't exist.

**Fix:**
1. Run `hyperdocs discover` to see available sessions
2. Use the full UUID or the first 8 characters
3. Check that `HYPERDOCS_OUTPUT_DIR` points to the right location

### "Budget exceeded"

**Symptom:** Pipeline stops with "Would exceed budget" message.

**Fix:** This is working as intended. The `--budget` flag prevents overspending.
- Run `hyperdocs cost SESSION_ID` to see the full estimate
- Use `--budget` with a higher value: `hyperdocs process SESSION_ID --full --budget 50.00`

### "Phase 1 timeout"

**Symptom:** Phase 1 Opus calls take > 5 minutes and fail.

**Fix:**
- Large sessions (500+ messages) may hit API timeouts
- The system auto-chunks large sessions, but very large ones may need manual intervention
- Try processing just one phase at a time: `hyperdocs process SESSION_ID --phase 1`

### "ModuleNotFoundError: No module named 'tools'"

**Symptom:** Running scripts directly fails with import errors.

**Fix:** Either:
1. Use the CLI: `hyperdocs process SESSION_ID` (handles paths automatically)
2. Set PYTHONPATH: `PYTHONPATH=. python3 tools/run_pipeline.py SESSION_ID`
3. Install the package: `pip install -e .`

### "Schema validation failed"

**Symptom:** Pipeline reports MISSING_KEY or WRONG_TYPE errors after a phase.

**Fix:**
1. Run the schema normalizer: `hyperdocs process SESSION_ID --normalize`
2. Re-run the failed phase with `--force`: `hyperdocs process SESSION_ID --phase N --force`

### "JSON parse error" in Phase 1

**Symptom:** Opus agent returns malformed JSON.

**Fix:** The system has 3 automatic JSON recovery strategies. If all fail:
1. Check the session output directory for partial results
2. Re-run with `--force`: `hyperdocs process SESSION_ID --phase 1 --force`
3. Large sessions may produce output that exceeds the 128K token limit

## Getting help

- Check `hyperdocs status` for a quick overview of all sessions
- Check the session output directory for `pipeline_run.log`
- Run `hyperdocs cost SESSION_ID` before processing to understand costs
- Report issues at https://github.com/anthropics/claude-code/issues
