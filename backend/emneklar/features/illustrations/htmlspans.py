"""Source positions of HTML elements – moved to :mod:`emneklar.core.canvas.htmlspans` (shared with targeted fixes).

Kept as a re-export so existing imports in the illustration assistant keep working.
"""

from __future__ import annotations

from emneklar.core.canvas.htmlspans import IMPLIED, P_CLOSERS, RAW_TEXT, VOID, ScanResult, Span, scan

__all__ = ["IMPLIED", "P_CLOSERS", "RAW_TEXT", "VOID", "ScanResult", "Span", "scan"]
