"""
Evidence Resolver — parses @evidence directives and replaces them with rendered blocks.

The resolver is called after the Phase 3 narrator (LLM) produces text. It finds all
@evidence:type(params) directives, routes each to the appropriate renderer, and replaces
the directive with the rendered output.

Usage:
    from evidence_resolver import resolve
    final_text = resolve(narrator_output, session_dir)

Directive syntax:
    @evidence:debug_sequence(range=[523,531])
    @evidence:emotional_arc(range=[520,540])
    @evidence:idea_transition(chain=[N01,N02,N03])
    @evidence:idea_transition(node=N16)
    @evidence:reaction_log(range=[0,1317])
    @evidence:file_timeline(file="config.py")
    @evidence:geological_event(msg=523)
    @evidence:decision_trace(marker="GM-001")
    @evidence:decision_trace(chain=[N01,N02])
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger("hyperdocs.evidence_resolver")

# Import the renderer registry
try:
    from .evidence import RENDERER_REGISTRY
except ImportError:
    # Fallback for direct script execution
    from evidence import RENDERER_REGISTRY

# Regex to match @evidence:type(params) directives
# Captures: type name and the full params string inside parentheses
_DIRECTIVE_PATTERN = re.compile(
    r'@evidence:(\w+)\(([^)]*)\)'
)


def _parse_params(params_str):
    """Parse the params string inside an @evidence directive.

    Handles:
      range=[523,531]        -> {"range": [523, 531]}
      file="config.py"       -> {"file": "config.py"}
      marker="GM-001"        -> {"marker": "GM-001"}
      chain=[N01,N02,N03]    -> {"chain": ["N01", "N02", "N03"]}
      node=N16               -> {"node": "N16"}
      msg=523                -> {"msg": 523}
    """
    params = {}
    if not params_str or not params_str.strip():
        return params

    # Tokenize by commas that are NOT inside brackets
    tokens = _split_top_level(params_str)

    for token in tokens:
        token = token.strip()
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip()
        value = value.strip()

        if not key or not value:
            continue

        # Parse the value
        if value.startswith("[") and value.endswith("]"):
            # Array: [523,531] or [N01,N02,N03]
            inner = value[1:-1].strip()
            items = [_parse_scalar(v.strip()) for v in inner.split(",") if v.strip()]
            params[key] = items
        elif value.startswith('"') and value.endswith('"'):
            params[key] = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            params[key] = value[1:-1]
        else:
            params[key] = _parse_scalar(value)

    return params


def _parse_scalar(value):
    """Parse a scalar value — integer if numeric, else string."""
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return float(value)
        except (ValueError, TypeError):
            return value


def _split_top_level(s):
    """Split string by commas not inside brackets."""
    parts = []
    depth = 0
    current = []
    for ch in s:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def resolve(text, session_dir, session_id=""):
    """Resolve all @evidence directives in text.

    Args:
        text: Narrator output containing @evidence:type(params) directives
        session_dir: Path to the session output directory
        session_id: Optional session ID (derived from session_dir if empty)

    Returns:
        Text with all directives replaced by rendered evidence blocks.
        Failed directives are replaced with [evidence unavailable: reason].
    """
    if not isinstance(text, str):
        return text

    session_dir = Path(session_dir) if not isinstance(session_dir, Path) else session_dir

    # Cache renderer instances per type (they share lazy-loaded data)
    renderer_cache = {}

    def _get_renderer(renderer_type):
        if renderer_type not in renderer_cache:
            cls = RENDERER_REGISTRY.get(renderer_type)
            if cls is None:
                return None
            renderer_cache[renderer_type] = cls(session_dir, session_id)
        return renderer_cache[renderer_type]

    def _replace_directive(match):
        directive_type = match.group(1)
        params_str = match.group(2)

        try:
            params = _parse_params(params_str)
        except Exception as e:
            logger.warning(f"Failed to parse params for @evidence:{directive_type}: {e}")
            return f"[evidence unavailable: parse error in {directive_type}({params_str})]"

        renderer = _get_renderer(directive_type)
        if renderer is None:
            return f"[evidence unavailable: unknown type \"{directive_type}\"]"

        try:
            result = renderer.render(params)
            return result
        except Exception as e:
            logger.warning(f"Renderer {directive_type} failed: {e}")
            return f"[evidence unavailable: {directive_type} render error: {e}]"

    resolved = _DIRECTIVE_PATTERN.sub(_replace_directive, text)
    return resolved


def resolve_count(text):
    """Count the number of @evidence directives in text without resolving them."""
    if not isinstance(text, str):
        return 0
    return len(_DIRECTIVE_PATTERN.findall(text))
