"""Tests for the lead_scoring_engine package's top-level public API."""

import lead_scoring_engine


def test_version_is_a_string():
    assert isinstance(lead_scoring_engine.__version__, str)


def test_all_declared_exports_are_actually_importable():
    for name in lead_scoring_engine.__all__:
        assert hasattr(lead_scoring_engine, name), f"{name} declared in __all__ but not exported"


def test_main_entry_points_are_exported():
    assert lead_scoring_engine.process_leads is not None
    assert lead_scoring_engine.ClaudeExtractor is not None
    assert lead_scoring_engine.ClaudeScorer is not None
