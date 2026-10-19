"""
Centralized logging configuration for DuaVideoGenerator.
Call setup_logging() once from main.py entry point.
Each module uses: logger = logging.getLogger(__name__)
"""

import logging
import logging.handlers
import os
import sys

_initialized = False

__all__ = ["setup_logging"]


def setup_logging(level=None, log_file=None):
    global _initialized
    if _initialized:
        return
    _initialized = True

    try:
        import config

        _level = level or getattr(config, "LOG_LEVEL", "INFO")
        _file = log_file or getattr(config, "LOG_FILE", None)
        _fmt = getattr(config, "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        _logs_dir = getattr(config, "LOGS_DIR", None)
    except Exception:
        _level = level or "INFO"
        _file = log_file
        _fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        _logs_dir = None

    numeric = getattr(logging, _level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric)

    fmt = logging.Formatter(_fmt, datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric)
    console.setFormatter(fmt)
    root.addHandler(console)

    if _file:
        if _logs_dir and not os.path.exists(_logs_dir):
            os.makedirs(_logs_dir, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setLevel(numeric)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("edge_tts").setLevel(logging.WARNING)
