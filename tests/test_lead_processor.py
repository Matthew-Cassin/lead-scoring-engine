"""Tests for lead_scoring_engine.lead_processor.

A fake ClaudeExtractor/ClaudeScorer is injected throughout -- process_leads
accepts pre-built instances specifically so tests never need a real (or
even mocked-at-the-SDK-level) API client to exercise the orchestration
logic (loading, stats, progress, dedup wiring) this module owns.
"""

import json

import pytest

from lead_scoring_engine.lead_processor import _load_raw_leads, process_leads
from lead_scoring_engine.models import (
    ApiUsage,
    ExtractionResult,
    LeadScoringError,
    ScoreResult,
)


class FakeExtractor:
    """Returns a canned ExtractionResult per raw_text, tracking call order."""

    def __init__(self, results: dict):
        self._results = results
        self.calls = []

    def extract_lead_fields(self, raw_text):
        self.calls.append(raw_text)
        return self._results[raw_text]


class FakeScorer:
    """Returns a canned ScoreResult (or one computed per-lead), tracking call order."""

    def __init__(self, result_fn):
        self._result_fn = result_fn
        self.calls = []

    def score_lead(self, lead):
        self.calls.append(lead)
        return self._result_fn(lead) if callable(self._result_fn) else self._result_fn


def _extraction(**overrides):
    fields = {"success": True, "name": "Jane", "email": "jane@x.com", "company": "Acme"}
    fields.update(overrides)
    return ExtractionResult(**fields)


def _score(**overrides):
    fields = {
        "success": True,
        "score": 70,
        "reasoning": "ok",
        "high_value": False,
        "follow_up_tactic": "email",
    }
    fields.update(overrides)
    return ScoreResult(**fields)


def _write_csv(tmp_path, rows, columns=("raw_lead", "source")):
    import csv

    path = tmp_path / "leads.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


class TestLoadRawLeads:
    def test_loads_csv(self, tmp_path):
        path = _write_csv(tmp_path, [{"raw_lead": "Jane, jane@x.com", "source": "form"}])
        raw = _load_raw_leads(str(path))
        assert raw == [{"raw_text": "Jane, jane@x.com", "source": "form"}]

    def test_loads_json(self, tmp_path):
        path = tmp_path / "leads.json"
        path.write_text(json.dumps([{"raw_lead": "Jane, jane@x.com"}]), encoding="utf-8")
        raw = _load_raw_leads(str(path))
        assert raw == [{"raw_text": "Jane, jane@x.com", "source": None}]

    def test_skips_blank_raw_lead_rows(self, tmp_path):
        rows = [{"raw_lead": "Jane", "source": ""}, {"raw_lead": "", "source": ""}]
        path = _write_csv(tmp_path, rows)
        raw = _load_raw_leads(str(path))
        assert len(raw) == 1

    def test_missing_file_raises(self):
        with pytest.raises(LeadScoringError):
            _load_raw_leads("/nonexistent/path.csv")

    def test_unsupported_extension_raises(self, tmp_path):
        path = tmp_path / "leads.txt"
        path.write_text("raw_lead\nJane", encoding="utf-8")
        with pytest.raises(LeadScoringError):
            _load_raw_leads(str(path))

    def test_csv_missing_raw_lead_column_raises(self, tmp_path):
        path = _write_csv(tmp_path, [{"name": "x", "source": "y"}], columns=("name", "source"))
        with pytest.raises(LeadScoringError):
            _load_raw_leads(str(path))

    def test_json_not_a_list_raises(self, tmp_path):
        path = tmp_path / "leads.json"
        path.write_text(json.dumps({"raw_lead": "Jane"}), encoding="utf-8")
        with pytest.raises(LeadScoringError):
            _load_raw_leads(str(path))


class TestProcessLeads:
    def test_full_pipeline_happy_path(self, tmp_path):
        path = _write_csv(tmp_path, [{"raw_lead": "Jane, jane@x.com", "source": "form"}])
        extractor = FakeExtractor({"Jane, jane@x.com": _extraction()})
        scorer = FakeScorer(_score(score=80))

        leads, stats = process_leads(
            str(path), extractor=extractor, scorer=scorer, rate_limit_delay=0.0
        )

        assert len(leads) == 1
        assert leads[0].name == "Jane"
        assert leads[0].score == 80
        assert stats.total_input == 1
        assert stats.successful_extractions == 1
        assert stats.avg_score == 80.0

    def test_extraction_failure_still_included_in_output(self, tmp_path):
        path = _write_csv(tmp_path, [{"raw_lead": "garbled text", "source": ""}])
        failed = _extraction(success=False, error="boom", name=None)
        extractor = FakeExtractor({"garbled text": failed})
        scorer = FakeScorer(_score(success=False, error="Insufficient data"))

        leads, stats = process_leads(
            str(path), extractor=extractor, scorer=scorer, rate_limit_delay=0.0
        )

        assert len(leads) == 1
        assert leads[0].extraction_succeeded is False
        assert leads[0].extraction_error == "boom"
        assert leads[0].score is None
        assert stats.successful_extractions == 0

    def test_duplicate_leads_are_merged(self, tmp_path):
        path = _write_csv(
            tmp_path,
            [
                {"raw_lead": "Jane one", "source": ""},
                {"raw_lead": "Jane two", "source": ""},
            ],
        )
        extractor = FakeExtractor(
            {
                "Jane one": _extraction(email="jane@x.com", company="Acme"),
                "Jane two": _extraction(
                    email="jane@x.com", company=None, intent_signals="wants pricing"
                ),
            }
        )
        scorer = FakeScorer(_score())

        leads, stats = process_leads(
            str(path), extractor=extractor, scorer=scorer, rate_limit_delay=0.0
        )

        assert len(leads) == 1
        assert stats.duplicates_removed == 1
        assert stats.total_input == 2  # extraction/validation stats are pre-dedup
        assert scorer.calls == leads  # scoring only ran once, on the merged record

    def test_cost_accumulates_and_cache_hits_do_not_add_cost(self, tmp_path):
        path = _write_csv(
            tmp_path, [{"raw_lead": "a", "source": ""}, {"raw_lead": "b", "source": ""}]
        )
        usage = ApiUsage(input_tokens=100, output_tokens=50, cost_usd=0.01)
        extractor = FakeExtractor(
            {
                "a": _extraction(name="Alice Anderson", email="a@x.com", usage=usage),
                "b": _extraction(name="Bob Baker", email="b@x.com", usage=None, from_cache=True),
            }
        )
        scorer = FakeScorer(_score(usage=None, from_cache=True))

        _, stats = process_leads(
            str(path), extractor=extractor, scorer=scorer, rate_limit_delay=0.0
        )

        assert stats.total_api_cost_usd == 0.01
        assert stats.cache_hits == 3  # 1 extraction cache hit + 2 scoring cache hits

    def test_progress_callback_invoked_per_stage(self, tmp_path):
        path = _write_csv(
            tmp_path, [{"raw_lead": "a", "source": ""}, {"raw_lead": "b", "source": ""}]
        )
        extractor = FakeExtractor(
            {
                "a": _extraction(name="Alice Anderson", email="a@x.com"),
                "b": _extraction(name="Bob Baker", email="b@x.com"),
            }
        )
        scorer = FakeScorer(_score())
        calls = []

        process_leads(
            str(path),
            extractor=extractor,
            scorer=scorer,
            rate_limit_delay=0.0,
            progress=lambda stage, current, total: calls.append((stage, current, total)),
        )

        assert ("extract", 1, 2) in calls
        assert ("extract", 2, 2) in calls
        assert ("score", 2, 2) in calls

    def test_valid_emails_counted_after_validation(self, tmp_path):
        path = _write_csv(
            tmp_path, [{"raw_lead": "a", "source": ""}, {"raw_lead": "b", "source": ""}]
        )
        extractor = FakeExtractor(
            {"a": _extraction(email="jane@x.com"), "b": _extraction(email="not-an-email")}
        )
        scorer = FakeScorer(_score())

        _, stats = process_leads(
            str(path), extractor=extractor, scorer=scorer, rate_limit_delay=0.0
        )

        assert stats.valid_emails == 1
