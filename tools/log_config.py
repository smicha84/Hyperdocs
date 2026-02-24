"""
Shared logging setup for the Hyperdocs pipeline.

Usage in any module:
    from tools.log_config import get_logger
    logger = get_logger("phase0.enrich_session")
    logger.info("Processing session...")

Main entry points call setup_pipeline_logging() once to configure handlers:
    from tools.log_config import setup_pipeline_logging
    setup_pipeline_logging(session_id="abc12345", log_dir=Path("output/session_abc12345"))

Namespace convention:
    hyperdocs.phase0.enrich_session
    hyperdocs.phase1.extract_threads
    hyperdocs.tools.run_pipeline
    hyperdocs.product.dashboard
"""
import json
import logging
from datetime import datetime
from pathlib import Path


def get_logger(name):
    """Return a logger under the hyperdocs namespace.

    Args:
        name: dotted module name, e.g. "phase0.enrich_session"

    Returns:
        logging.Logger named "hyperdocs.{name}"
    """
    return logging.getLogger(f"hyperdocs.{name}")


class _JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for structured log files."""

    def __init__(self, session_id=None):
        super().__init__()
        self._session_id = session_id or ""

    def format(self, record):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "session": self._session_id,
            "message": record.getMessage(),
        }
        return json.dumps(entry)


def setup_pipeline_logging(session_id=None, log_dir=None):
    """Configure the root hyperdocs logger with console and optional file output.

    Idempotent — only attaches handlers if none exist yet on the root logger.

    Args:
        session_id: Optional session ID for log file naming and JSON records.
        log_dir: Optional Path for the JSON log file. If provided with session_id,
                 writes structured logs to {log_dir}/pipeline_run.log.
    """
    root = logging.getLogger("hyperdocs")

    # Only attach handlers once
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)

    # Console handler — INFO level, simple format
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    # File handler — DEBUG level, JSON structured
    if session_id and log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "pipeline_run.log"
        file_handler = logging.FileHandler(log_file, mode="a")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(_JsonFormatter(session_id=session_id))
        root.addHandler(file_handler)
