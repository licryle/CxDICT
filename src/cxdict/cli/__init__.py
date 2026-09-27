"""Shared CLI plumbing."""

from __future__ import annotations

import sys


def ensure_utf8_output() -> None:
    """Make stdout Unicode-safe for CJK output.

    Windows consoles default to cp1252, where printing a dictionary row
    crashes the run after all the work is done. Best effort: terminals
    without reconfigure are left alone.
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
