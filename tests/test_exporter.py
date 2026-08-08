"""Tests for lead_scoring_engine.exporter."""

import csv
import json

from lead_scoring_engine.exporter import (
    export_csv,
    export_json,
    generate_email_digest,
    generate_summary_report,
)
from lead_scoring_engine.models import Lead, ProcessingStats


def _lead(id, **overrides):
    fields = dict(raw_text="...")
    fields.update(overrides)
    return Lead(id=id, **fields)


def _stats(**overrides):
    fields = dict(
        total_input=2,
        successful_extractions=2,
        valid_emails=2,
        duplicates_removed=0,
        avg_score=75.0,
        high_value_count=1,
        processing_time_sec=3.2,
        total_api_cost_usd=0.01,
        cache_hits=0,
    )
    fields.update(overrides)
    return ProcessingStats(**fields)


class TestExportCsv:
    def test_writes_expected_columns_and_creates_parent_dir(self, tmp_path):
        leads = [_lead("a", name="Jane", email="jane@x.com", score=80)]
        path = tmp_path / "nested" / "leads.csv"
        export_csv(leads, str(path))
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["name"] == "Jane"
        assert rows[0]["score"] == "80"
        assert "id" in rows[0] and "email_valid" in rows[0]

    def test_empty_leads_still_writes_a_header(self, tmp_path):
        path = tmp_path / "leads.csv"
        export_csv([], str(path))
        with open(path, encoding="utf-8") as f:
            header = f.readline().strip()
        assert "name" in header


class TestExportJson:
    def test_writes_full_lead_objects(self, tmp_path):
        leads = [_lead("a", name="Jane", merged_from=["b"])]
        path = tmp_path / "leads.json"
        export_json(leads, str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data[0]["name"] == "Jane"
        assert data[0]["merged_from"] == ["b"]


class TestGenerateSummaryReport:
    def test_includes_headline_stats(self):
        leads = [_lead("a", name="Jane", score=90), _lead("b", name="Bob", score=40)]
        report = generate_summary_report(leads, _stats(total_input=2))
        assert "Total Leads Processed: 2" in report
        assert "Average Lead Score: 75.0" in report

    def test_top_leads_sorted_highest_first(self):
        leads = [_lead("a", name="Low", score=10), _lead("b", name="High", score=90)]
        report = generate_summary_report(leads, _stats())
        assert report.index("High") < report.index("Low")

    def test_no_scored_leads_does_not_crash(self):
        leads = [_lead("a", name="Unscored")]
        report = generate_summary_report(leads, _stats(avg_score=0.0))
        assert "(none scored)" in report


class TestGenerateEmailDigest:
    def test_uses_only_inline_styles_no_style_block(self):
        leads = [_lead("a", name="Jane", score=80)]
        html = generate_email_digest(leads)
        assert "<style" not in html
        assert 'style="' in html

    def test_escapes_html_special_characters(self):
        leads = [_lead("a", name='<script>alert(1)</script>', score=80)]
        html = generate_email_digest(leads)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_respects_top_n(self):
        leads = [_lead(f"lead-{i}", name=f"Lead {i}", score=i) for i in range(10)]
        html = generate_email_digest(leads, top_n=3)
        # Body rows carry a distinct border style from the header row, so
        # this counts only body rows.
        assert html.count("border-bottom:1px solid #eee") == 3

    def test_empty_scored_list_renders_placeholder_row(self):
        html = generate_email_digest([_lead("a", name="Unscored")])
        assert "No scored leads" in html
