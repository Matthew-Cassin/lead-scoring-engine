"""Command-line interface for lead-scoring-engine, built on Click."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

from . import config
from .exporter import export_csv, export_json, generate_email_digest, generate_summary_report
from .lead_processor import process_leads
from .logger import configure_logging
from .models import LeadScoringError

__all__ = ["main"]

_VALID_FORMATS = ("csv", "json", "summary", "email")


@click.command()
@click.option(
    "--input", "input_file", required=True, type=click.Path(exists=True, dir_okay=False),
    help="Path to a .csv (with a 'raw_lead' column) or .json (list of {'raw_lead': ...}) file.",
)
@click.option("--output", default=config.OUTPUT_DIR, show_default=True, help="Output directory.")
@click.option(
    "--formats", default=",".join(_VALID_FORMATS), show_default=True,
    help="Comma-separated subset of: csv,json,summary,email.",
)
@click.option("--api-key", default=None, help="Anthropic API key. Defaults to ANTHROPIC_API_KEY.")
@click.option("--model", default=None, help=f"Claude model ID. Defaults to {config.CLAUDE_MODEL}.")
@click.option("--cache/--no-cache", "use_cache", default=True, show_default=True,
              help="Cache Claude responses on disk to avoid re-spending on reruns.")
@click.option("--cache-dir", default=config.CACHE_DIR, show_default=True)
@click.option("--dedup-threshold", default=config.DEDUP_THRESHOLD, show_default=True, type=float,
              help="Fuzzy name-match threshold (0.0-1.0) for deduplication.")
@click.option(
    "--rate-limit-delay", default=config.RATE_LIMIT_DELAY_SEC, show_default=True, type=float,
    help="Seconds to sleep between consecutive live Claude API calls.",
)
@click.option("--max-retries", default=None, type=int, help=f"Defaults to {config.MAX_RETRIES}.")
@click.option("--verbose", is_flag=True, default=False, help="Enable INFO-level console logging.")
def main(
    input_file: str,
    output: str,
    formats: str,
    api_key: Optional[str],
    model: Optional[str],
    use_cache: bool,
    cache_dir: str,
    dedup_threshold: float,
    rate_limit_delay: float,
    max_retries: Optional[int],
    verbose: bool,
) -> None:
    """Extract, validate, deduplicate, and score leads from RAW_LEAD text.

        lead-scoring-engine --input raw_leads.csv --output processed_leads

    Requires an Anthropic API key: set the ANTHROPIC_API_KEY environment
    variable (a .env file in the current directory is loaded automatically
    if present), or pass --api-key explicitly.
    """
    load_dotenv()
    if verbose:
        configure_logging(level=logging.INFO)
    _progress_state["stage"] = None  # reset between invocations (matters for tests/CliRunner reuse)

    selected_formats = {f.strip().lower() for f in formats.split(",") if f.strip()}
    unknown = selected_formats - set(_VALID_FORMATS)
    if unknown:
        raise click.BadParameter(
            f"unknown format(s) {sorted(unknown)}, expected a subset of {list(_VALID_FORMATS)}",
            param_hint="--formats",
        )

    try:
        leads, stats = process_leads(
            input_file,
            api_key=api_key,
            model=model,
            cache_dir=cache_dir if use_cache else None,
            dedup_threshold=dedup_threshold,
            rate_limit_delay=rate_limit_delay,
            max_retries=max_retries,
            progress=_cli_progress,
        )
    except LeadScoringError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo()
    click.echo(f"✓ Loaded {stats.total_input} lead(s) from {input_file}")
    click.echo(
        f"✓ Extracted fields ({stats.successful_extractions}/{stats.total_input} successful)"
    )
    click.echo(f"✓ Validated emails ({stats.valid_emails}/{stats.total_input} valid)")
    click.echo(f"✓ Deduplicated ({stats.duplicates_removed} duplicate(s) removed)")
    click.echo(f"✓ Scored leads (avg: {stats.avg_score})")

    output_dir = Path(output)
    saved = []
    if "csv" in selected_formats:
        path = output_dir / "leads_scored.csv"
        export_csv(leads, str(path))
        saved.append(path)
    if "json" in selected_formats:
        path = output_dir / "leads_scored.json"
        export_json(leads, str(path))
        saved.append(path)
    if "summary" in selected_formats:
        path = output_dir / "summary_report.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generate_summary_report(leads, stats), encoding="utf-8")
        saved.append(path)
    if "email" in selected_formats:
        path = output_dir / "email_digest.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generate_email_digest(leads), encoding="utf-8")
        saved.append(path)

    if saved:
        click.echo("\nResults saved to:")
        for path in saved:
            click.echo(f"  - {path}")

    click.echo(f"\nTotal API cost: ${stats.total_api_cost_usd:.4f}")
    if stats.cache_hits:
        click.echo(f"(includes {stats.cache_hits} cache hit(s) that made no API call)")


_progress_state = {"stage": None}


def _cli_progress(stage: str, current: int, total: int) -> None:
    """Render a simple in-place progress bar for the CLI's extract/score stages."""
    label = {"extract": "Extracting fields", "score": "Scoring leads"}.get(stage, stage)
    if _progress_state["stage"] != stage:
        if _progress_state["stage"] is not None:
            click.echo()
        click.echo(f"{label}...")
        _progress_state["stage"] = stage

    width = 30
    filled = int(width * current / total) if total else width
    bar = "#" * filled + "-" * (width - filled)
    click.echo(f"\r  [{bar}] {current}/{total}", nl=False)
    if current >= total:
        click.echo()


if __name__ == "__main__":  # pragma: no cover
    main()
