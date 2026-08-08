"""Tests for lead_scoring_engine.models."""

from lead_scoring_engine.models import (
    ApiUsage,
    ExtractionResult,
    Lead,
    ProcessingStats,
    ScoreResult,
)


class TestLead:
    def test_defaults_are_none_or_empty_not_invalid(self):
        lead = Lead(id="lead-1", raw_text="some raw text")
        assert lead.name is None
        assert lead.email_valid is None
        assert lead.extraction_succeeded is False
        assert lead.merged_from == []

    def test_two_leads_do_not_share_the_merged_from_default_list(self):
        # A classic mutable-default-argument trap -- guard against it explicitly.
        a = Lead(id="a", raw_text="x")
        b = Lead(id="b", raw_text="y")
        a.merged_from.append("z")
        assert b.merged_from == []


class TestExtractionResult:
    def test_failure_has_no_fields_populated(self):
        result = ExtractionResult(success=False, error="boom")
        assert result.name is None
        assert result.usage is None


class TestScoreResult:
    def test_success_carries_usage(self):
        usage = ApiUsage(input_tokens=10, output_tokens=5, cost_usd=0.001)
        result = ScoreResult(success=True, score=80, usage=usage)
        assert result.usage.cost_usd == 0.001


class TestProcessingStats:
    def test_field_roundtrip(self):
        stats = ProcessingStats(
            total_input=10,
            successful_extractions=9,
            valid_emails=8,
            duplicates_removed=1,
            avg_score=72.4,
            high_value_count=3,
            processing_time_sec=12.5,
            total_api_cost_usd=0.05,
            cache_hits=2,
        )
        assert stats.total_input == 10
        assert stats.cache_hits == 2
