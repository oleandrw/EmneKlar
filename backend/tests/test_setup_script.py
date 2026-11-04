"""scripts/setup.py: one setup for the whole program – the optional local models are a question in setup.bat."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from tests.script_loader import load_script

setup = load_script("setup")


def _args(**flags: bool) -> argparse.Namespace:
    return argparse.Namespace(**{"rag": False, "no_rag": False, "no_pause": False, **flags})


@pytest.fixture(autouse=True)
def _no_earlier_choice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup, "ROOT", tmp_path)  # no backend\.venv\emneklar-extras.txt


def _never(_prompt: str) -> str:
    raise AssertionError("asked although it should not")


@pytest.mark.parametrize("answer, expected", [("j", True), ("JA", True), ("y", True), ("", False), ("n", False),
                                              ("nei", False)])
def test_asks_in_a_console_and_defaults_to_no(answer: str, expected: bool) -> None:
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return answer

    assert setup.wants_local_models(_args(), ask=ask, interactive=True) is expected
    assert len(prompts) == 1 and "[j/N]" in prompts[0] and "flere GB" in prompts[0]


def test_never_asks_without_a_console_or_when_already_decided(tmp_path: Path) -> None:
    assert setup.wants_local_models(_args(), ask=_never, interactive=False) is False  # CI, the app's own runs
    assert setup.wants_local_models(_args(no_pause=True), ask=_never, interactive=True) is False  # setup.bat --no-pause
    assert setup.wants_local_models(_args(no_rag=True), ask=_never, interactive=True) is False
    assert setup.wants_local_models(_args(rag=True), ask=_never, interactive=True) is True
    setup.update.remember_extra(tmp_path, "rag")  # chosen before: kept by update.bat, not asked again
    assert setup.wants_local_models(_args(), ask=_never, interactive=True) is False


def test_closed_input_counts_as_no() -> None:
    def closed(_prompt: str) -> str:
        raise EOFError

    assert setup.wants_local_models(_args(), ask=closed, interactive=True) is False
