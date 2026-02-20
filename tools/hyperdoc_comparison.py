#!/usr/bin/env python3
"""
Hyperdoc Comparison — Side-by-side demo of Opus with vs without hyperdocs.

Sends the same file to Opus twice with a deliberately vague prompt:
  "Here's my file. What should I do next?"

Version A: bare code (markers stripped)
Version B: code + hyperdoc markers

Outputs an HTML visual showing both responses side by side.

Usage:
    python3 hyperdoc_comparison.py phase_0_prep/deterministic_prep.py
    python3 hyperdoc_comparison.py --all   # Run on all 5 enhanced files

Requires: ANTHROPIC_API_KEY environment variable
"""
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parent.parent  # hyperdocs_3 root

# Load API key from .env if present
ENV_FILE = REPO / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip()

PROMPT = """Here's a file from my project. I need your help — what should I do next with this file? What's broken, what needs attention, and what would you prioritize?

Don't just describe what the file does. Tell me what to DO.

```
{code}
```"""

MODEL = "claude-opus-4-6"


def strip_markers(text):
    """Remove everything after the HISTORICAL disclaimer line."""
    lines = text.splitlines()
    bare_lines = []
    for line in lines:
        if "@ctx HYPERDOC" in line and "HISTORICAL" in line:
            break
        bare_lines.append(line)
    return "\n".join(bare_lines).rstrip()


def call_opus(prompt):
    """Single Opus API call. Returns response text."""
    import anthropic
    client = anthropic.Anthropic()

    text_parts = []
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for event in stream:
            if hasattr(event, "type"):
                if event.type == "content_block_delta" and hasattr(event, "delta"):
                    if event.delta.type == "text_delta":
                        text_parts.append(event.delta.text)

    return "".join(text_parts)


def generate_html(filename, bare_code, enhanced_code, response_bare, response_enhanced):
    """Generate side-by-side comparison HTML."""
    bare_lines = bare_code.count("\n")
    enhanced_lines = enhanced_code.count("\n")
    marker_count = enhanced_code.count("@ctx:")

    # Escape HTML
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Convert markdown-ish response to HTML paragraphs
    def md_to_html(text):
        lines = text.split("\n")
        html_parts = []
        in_code = False
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                if in_code:
                    html_parts.append("<pre><code>")
                else:
                    html_parts.append("</code></pre>")
                continue
            if in_code:
                html_parts.append(esc(line))
                continue
            if line.startswith("# "):
                html_parts.append(f"<h3>{esc(line[2:])}</h3>")
            elif line.startswith("## "):
                html_parts.append(f"<h4>{esc(line[3:])}</h4>")
            elif line.startswith("### "):
                html_parts.append(f"<h4>{esc(line[4:])}</h4>")
            elif line.startswith("- "):
                html_parts.append(f"<li>{esc(line[2:])}</li>")
            elif line.startswith("**") and line.endswith("**"):
                html_parts.append(f"<p><strong>{esc(line[2:-2])}</strong></p>")
            elif line.strip():
                html_parts.append(f"<p>{esc(line)}</p>")
        return "\n".join(html_parts)

    response_a_html = md_to_html(response_bare)
    response_b_html = md_to_html(response_enhanced)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Hyperdoc Comparison: {esc(filename)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e0e0e0; }}
  .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 40px 60px; border-bottom: 2px solid #333; }}
  .header h1 {{ font-size: 28px; color: #fff; margin-bottom: 8px; }}
  .header .subtitle {{ font-size: 16px; color: #888; }}
  .header .prompt {{ background: #111; border: 1px solid #333; border-radius: 8px; padding: 16px 20px; margin-top: 20px; font-family: monospace; font-size: 14px; color: #aaa; white-space: pre-wrap; }}
  .stats {{ display: flex; gap: 40px; margin-top: 20px; }}
  .stat {{ text-align: center; }}
  .stat .num {{ font-size: 24px; font-weight: 700; color: #4fc3f7; }}
  .stat .label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 1px; }}
  .comparison {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; min-height: calc(100vh - 250px); }}
  .panel {{ padding: 30px 40px; overflow-y: auto; }}
  .panel-a {{ background: #0d0d0d; border-right: 2px solid #333; }}
  .panel-b {{ background: #0d1117; }}
  .panel-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #222; }}
  .panel-header .badge {{ padding: 4px 12px; border-radius: 4px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
  .badge-bare {{ background: #333; color: #999; }}
  .badge-enhanced {{ background: #1b4332; color: #52b788; }}
  .panel-header h2 {{ font-size: 18px; color: #ccc; }}
  .panel-header .meta {{ font-size: 13px; color: #555; margin-left: auto; }}
  .response {{ line-height: 1.7; }}
  .response h3 {{ color: #fff; font-size: 16px; margin: 20px 0 8px; }}
  .response h4 {{ color: #ccc; font-size: 14px; margin: 16px 0 6px; }}
  .response p {{ color: #bbb; margin: 6px 0; font-size: 14px; }}
  .response li {{ color: #bbb; margin: 4px 0 4px 20px; font-size: 14px; }}
  .response strong {{ color: #fff; }}
  .response pre {{ background: #111; border: 1px solid #222; border-radius: 4px; padding: 12px; margin: 8px 0; overflow-x: auto; }}
  .response code {{ font-family: 'SF Mono', Menlo, monospace; font-size: 13px; color: #a0a0a0; }}
  .verdict {{ background: #111; border-top: 2px solid #333; padding: 30px 60px; text-align: center; }}
  .verdict h3 {{ font-size: 20px; color: #52b788; margin-bottom: 8px; }}
  .verdict p {{ color: #888; font-size: 14px; max-width: 700px; margin: 0 auto; }}
</style>
</head>
<body>

<div class="header">
  <h1>Hyperdoc Comparison: {esc(filename)}</h1>
  <div class="subtitle">Same file. Same prompt. Same model ({MODEL}). Different context.</div>
  <div class="prompt">Prompt: "Here's a file from my project. I need your help — what should I do next with this file? What's broken, what needs attention, and what would you prioritize?"</div>
  <div class="stats">
    <div class="stat"><div class="num">{bare_lines}</div><div class="label">Lines (bare)</div></div>
    <div class="stat"><div class="num">{enhanced_lines}</div><div class="label">Lines (enhanced)</div></div>
    <div class="stat"><div class="num">{marker_count}</div><div class="label">@ctx markers</div></div>
    <div class="stat"><div class="num">{MODEL}</div><div class="label">Model</div></div>
  </div>
</div>

<div class="comparison">
  <div class="panel panel-a">
    <div class="panel-header">
      <span class="badge badge-bare">Without Hyperdocs</span>
      <h2>Opus sees bare code only</h2>
      <span class="meta">{bare_lines} lines</span>
    </div>
    <div class="response">{response_a_html}</div>
  </div>
  <div class="panel panel-b">
    <div class="panel-header">
      <span class="badge badge-enhanced">With Hyperdocs</span>
      <h2>Opus sees code + {marker_count} markers</h2>
      <span class="meta">{enhanced_lines} lines</span>
    </div>
    <div class="response">{response_b_html}</div>
  </div>
</div>

<div class="verdict">
  <h3>The difference is context.</h3>
  <p>Without hyperdocs, Opus gives generic code review suggestions. With hyperdocs, Opus knows the file's history — what was tried, what failed, what decisions were made, and what still needs attention. It gives actionable guidance instead of surface observations.</p>
</div>

</body>
</html>"""
    return html


def run_comparison(filepath):
    """Run the full comparison on one file."""
    full_text = filepath.read_text()
    bare_text = strip_markers(full_text)
    filename = filepath.name

    bare_markers = bare_text.count("@ctx:")
    full_markers = full_text.count("@ctx:")

    print(f"File: {filename}")
    print(f"  Bare: {bare_text.count(chr(10))} lines, {bare_markers} markers")
    print(f"  Full: {full_text.count(chr(10))} lines, {full_markers} markers")

    print(f"  Calling Opus (bare)...", end="", flush=True)
    t0 = time.time()
    response_bare = call_opus(PROMPT.format(code=bare_text))
    print(f" {time.time()-t0:.0f}s")

    print(f"  Calling Opus (enhanced)...", end="", flush=True)
    t0 = time.time()
    response_enhanced = call_opus(PROMPT.format(code=full_text))
    print(f" {time.time()-t0:.0f}s")

    html = generate_html(filename, bare_text, full_text, response_bare, response_enhanced)

    out_path = REPO / "output" / f"comparison_{filepath.stem}.html"
    out_path.write_text(html)
    print(f"  Output: {out_path}")

    # Also save raw responses
    raw_path = REPO / "output" / f"comparison_{filepath.stem}.json"
    raw_path.write_text(json.dumps({
        "file": filename,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model": MODEL,
        "bare_lines": bare_text.count("\n"),
        "enhanced_lines": full_text.count("\n"),
        "markers": full_markers,
        "response_bare": response_bare,
        "response_enhanced": response_enhanced,
    }, indent=2))

    return out_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 hyperdoc_comparison.py <file_path>")
        print("       python3 hyperdoc_comparison.py --all")
        sys.exit(1)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        print("  Set it in environment or in .env file")
        sys.exit(1)

    if sys.argv[1] == "--all":
        # Run on all 5 enhanced files
        targets = [
            REPO / "config.py",
            REPO / "phase_1_extraction" / "batch_orchestrator.py",
            REPO / "phase_0_prep" / "deterministic_prep.py",
            REPO / "phase_3_hyperdoc_writing" / "generate_viewer.py",
            REPO / "phase_0_prep" / "geological_reader.py",
        ]
        for t in targets:
            if t.exists() and "@ctx:" in t.read_text():
                run_comparison(t)
            else:
                print(f"SKIP {t.name}: no markers found")
    else:
        target = Path(sys.argv[1])
        if not target.is_absolute():
            target = REPO / target
        if not target.exists():
            print(f"ERROR: File not found: {target}")
            sys.exit(1)
        out = run_comparison(target)
        # Auto-open
        os.system(f'open "{out}"')


if __name__ == "__main__":
    main()
