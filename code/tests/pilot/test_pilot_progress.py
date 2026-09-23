"""Progress display contracts for the shared pilot trainer."""

import sys

from kaf_profiti.experiments.pilot_runner import _resolve_progress


def test_progress_defaults_to_terminal_and_honors_explicit_override(monkeypatch):
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    assert _resolve_progress(None) is True
    assert _resolve_progress(False) is False

    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    assert _resolve_progress(None) is False
    assert _resolve_progress(True) is True
