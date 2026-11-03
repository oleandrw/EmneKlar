"""Issuing write permits. ONLY the change engine (core/changes) may import this module.

`tests/test_invariants.py` fails if any other module imports it, which keeps
the rule «all Canvas writes go through the change engine» enforceable.
"""

from __future__ import annotations

from emneklar.core.canvas.client import WritePermit


def issue_permit(change_id: int | None, reason: str) -> WritePermit:
    return WritePermit(change_id=change_id, reason=reason)
