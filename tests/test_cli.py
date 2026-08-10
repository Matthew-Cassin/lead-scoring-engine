"""Tests for lead_scoring_engine.cli.

process_leads is mocked throughout -- real end-to-end CLI behavior
against the live Claude API was verified by hand while building this
module (see the README's Quick Start for the captured real output).
"""

import json
from unittest.mock import patch

from click.testing import CliRunner

from lead_scoring_engine.cli import main
from lead_scoring_engine.models import Lead, LeadScoringError, ProcessingStats


def _stats(**overrides):
    fields = {
        "total_input": 2,
        "successful_extractions": 2,
        "valid_emails": 2,
        "duplicates_removed": 0,
        "avg_score": 75.0,
        "high_value_count": 1,
        "processing_time_sec": 3.2,
        "total_api_cost_usd": 0.0123,
        "cache_hits": 0,
    }
    fields.update(overrides)
    return ProcessingStats(**fields)


def _leads():
    return [Lead(id="lead-1", raw_text="...", name="Jane", email="jane@x.com", score=80)]


def _input_csv(tmp_path):
    path = tmp_path / "leads.csv"
    path.write_text("raw_lead\nJane, jane@x.com\n", encoding="utf-8")
    return path


def run(args):
    return CliRunner().invoke(main, args)


class TestFormatValidation:
    def test_unknown_format_is_rejected(self, tmp_path):
        result = run(["--input", str(_input_csv(tmp_path)), "--formats", "csv,xml"])
        assert result.exit_code != 0
        assert "xml" in result.output

    def test_missing_input_file_is_rejected(self):
        result = run(["--input", "/nonexistent/leads.csv"])
        assert result.exit_code != 0


class TestSuccessfulRun:
    @patch("lead_scoring_engine.cli.process_leads")
    def test_prints_checklist_and_writes_selected_formats(self, mock_process, tmp_path):
        mock_process.return_value = (_leads(), _stats())
        output_dir = tmp_path / "out"

        result = run(
            [
                "--input", str(_input_csv(tmp_path)),
                "--output", str(output_dir),
                "--formats", "csv,summary",
            ]
        )

        assert result.exit_code == 0, result.output
        assert "Loaded 2 lead(s)" in result.output
        assert "Extracted fields (2/2 successful)" in result.output
        assert "Total API cost: $0.0123" in result.output
        assert (output_dir / "leads_scored.csv").exists()
        assert (output_dir / "summary_report.txt").exists()
        assert not (output_dir / "leads_scored.json").exists()
        assert not (output_dir / "email_digest.html").exists()

    @patch("lead_scoring_engine.cli.process_leads")
    def test_all_formats_by_default(self, mock_process, tmp_path):
        mock_process.return_value = (_leads(), _stats())
        output_dir = tmp_path / "out"

        run(["--input", str(_input_csv(tmp_path)), "--output", str(output_dir)])

        filenames = (
            "leads_scored.csv", "leads_scored.json", "summary_report.txt", "email_digest.html"
        )
        for filename in filenames:
            assert (output_dir / filename).exists()

    @patch("lead_scoring_engine.cli.process_leads")
    def test_json_output_is_valid_and_matches_leads(self, mock_process, tmp_path):
        mock_process.return_value = (_leads(), _stats())
        output_dir = tmp_path / "out"

        run(
            ["--input", str(_input_csv(tmp_path)), "--output", str(output_dir), "--formats", "json"]
        )

        data = json.loads((output_dir / "leads_scored.json").read_text(encoding="utf-8"))
        assert data[0]["name"] == "Jane"

    @patch("lead_scoring_engine.cli.process_leads")
    def test_cache_hit_note_only_shown_when_nonzero(self, mock_process, tmp_path):
        mock_process.return_value = (_leads(), _stats(cache_hits=5))
        result = run(["--input", str(_input_csv(tmp_path)), "--formats", "summary"])
        assert "5 cache hit(s)" in result.output

    @patch("lead_scoring_engine.cli.process_leads")
    def test_no_cache_hit_note_when_zero(self, mock_process, tmp_path):
        mock_process.return_value = (_leads(), _stats(cache_hits=0))
        result = run(["--input", str(_input_csv(tmp_path)), "--formats", "summary"])
        assert "cache hit" not in result.output

    @patch("lead_scoring_engine.cli.process_leads")
    def test_forwards_cli_options_to_process_leads(self, mock_process, tmp_path):
        mock_process.return_value = (_leads(), _stats())
        run(
            [
                "--input", str(_input_csv(tmp_path)),
                "--model", "claude-haiku-4-5-20251001",
                "--dedup-threshold", "0.7",
                "--no-cache",
                "--formats", "summary",
            ]
        )
        _, kwargs = mock_process.call_args
        assert kwargs["model"] == "claude-haiku-4-5-20251001"
        assert kwargs["dedup_threshold"] == 0.7
        assert kwargs["cache_dir"] is None  # --no-cache disables it


class TestErrorHandling:
    @patch("lead_scoring_engine.cli.process_leads")
    def test_lead_scoring_error_becomes_clean_cli_error(self, mock_process, tmp_path):
        mock_process.side_effect = LeadScoringError("no 'raw_lead' column")
        result = run(["--input", str(_input_csv(tmp_path))])
        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert "raw_lead" in result.output
