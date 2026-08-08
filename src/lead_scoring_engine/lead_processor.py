"""Pipeline orchestration: load raw leads, extract, validate, deduplicate, score."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pandas as pd

from . import config
from .claude_extractor import ClaudeExtractor
from .claude_scorer import ClaudeScorer
from .deduplicator import deduplicate_leads
from .logger import get_logger
from .models import Lead, LeadScoringError, ProcessingStats
from .validators import validate_email, validate_phone

logger = get_logger("lead_processor")

__all__ = ["process_leads"]

# progress(stage, current, total) -- called after each per-lead step of
# the extraction and scoring stages, so a caller (typically the CLI) can
# render a progress bar without this module doing any I/O itself.
ProgressCallback = Callable[[str, int, int], None]


def process_leads(
    input_file: str,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    cache_dir: Optional[str] = config.CACHE_DIR,
    dedup_threshold: float = config.DEDUP_THRESHOLD,
    rate_limit_delay: float = config.RATE_LIMIT_DELAY_SEC,
    max_retries: Optional[int] = None,
    extractor: Optional[ClaudeExtractor] = None,
    scorer: Optional[ClaudeScorer] = None,
    progress: Optional[ProgressCallback] = None,
) -> Tuple[List[Lead], ProcessingStats]:
    """Run the full pipeline: load, extract, validate, deduplicate, score.

    Args:
        input_file: Path to a ``.csv`` (with a ``raw_lead`` column) or
            ``.json`` (a list of objects with a ``"raw_lead"`` key) file
            of raw, unstructured lead text.
        api_key: Anthropic API key, forwarded to ``ClaudeExtractor``/
            ``ClaudeScorer`` if they aren't supplied directly. Falls
            back to the ``ANTHROPIC_API_KEY`` environment variable.
        model: Claude model ID, forwarded the same way.
        cache_dir: On-disk response cache directory, forwarded the same
            way. ``None`` disables caching.
        dedup_threshold: Fuzzy name-match threshold forwarded to
            :func:`~lead_scoring_engine.deduplicator.deduplicate_leads`.
        rate_limit_delay: Seconds to sleep between consecutive live
            Claude API calls (skipped after a cache hit, since no call
            was made).
        max_retries: Forwarded to ``ClaudeExtractor``/``ClaudeScorer``.
        extractor: A pre-built ``ClaudeExtractor`` to use instead of
            constructing one from the arguments above -- mainly for
            tests, so a real API client is never required to exercise
            this function.
        scorer: Same, for ``ClaudeScorer``.
        progress: Optional callback invoked as ``progress(stage,
            current, total)`` after each lead during the "extract" and
            "score" stages (the only stages slow enough to need one).

    Returns:
        A ``(leads, stats)`` tuple: the final deduplicated, scored
        leads, and summary :class:`~lead_scoring_engine.models.ProcessingStats`
        for the whole run.

    Raises:
        LeadScoringError: If ``input_file`` doesn't exist, isn't a
            ``.csv``/``.json`` file, can't be parsed, or has no
            recognizable ``raw_lead`` data. Also raised if the Claude
            API client can't be constructed (e.g. no API key anywhere).
    """
    start_time = time.monotonic()
    raw_leads = _load_raw_leads(input_file)
    leads = [
        Lead(id=f"lead-{i}", raw_text=item["raw_text"], source=item["source"])
        for i, item in enumerate(raw_leads, start=1)
    ]
    logger.info("Loaded %d lead(s) from %s", len(leads), input_file)

    extractor = extractor or ClaudeExtractor(
        api_key=api_key, model=model, cache_dir=cache_dir, max_retries=max_retries
    )
    scorer = scorer or ClaudeScorer(
        api_key=api_key, model=model, cache_dir=cache_dir, max_retries=max_retries
    )

    total_cost = 0.0
    cache_hits = 0
    total = len(leads)

    for index, lead in enumerate(leads, start=1):
        result = extractor.extract_lead_fields(lead.raw_text)
        lead.extraction_succeeded = result.success
        if result.success:
            lead.name = result.name
            lead.email = result.email
            lead.phone = result.phone
            lead.company = result.company
            lead.industry = result.industry
            lead.intent_signals = result.intent_signals
        else:
            lead.extraction_error = result.error
            logger.warning("Extraction failed for %s: %s", lead.id, result.error)

        if result.from_cache:
            cache_hits += 1
        elif result.usage is not None:
            total_cost += result.usage.cost_usd

        if progress is not None:
            progress("extract", index, total)
        if not result.from_cache and index < total:
            time.sleep(rate_limit_delay)

    successful_extractions = sum(1 for lead in leads if lead.extraction_succeeded)

    for lead in leads:
        lead.email_valid, lead.email = validate_email(lead.email)
        lead.phone_valid, lead.phone = validate_phone(lead.phone)

    valid_emails = sum(1 for lead in leads if lead.email_valid)

    deduplicated, merge_report = deduplicate_leads(leads, threshold=dedup_threshold)
    total_scoreable = len(deduplicated)

    for index, lead in enumerate(deduplicated, start=1):
        result = scorer.score_lead(lead)
        if result.success:
            lead.score = result.score
            lead.score_reasoning = result.reasoning
            lead.high_value = result.high_value
            lead.follow_up_tactic = result.follow_up_tactic

        if result.from_cache:
            cache_hits += 1
        elif result.usage is not None:
            total_cost += result.usage.cost_usd

        if progress is not None:
            progress("score", index, total_scoreable)
        if not result.from_cache and index < total_scoreable:
            time.sleep(rate_limit_delay)

    scores = [lead.score for lead in deduplicated if lead.score is not None]
    stats = ProcessingStats(
        total_input=len(leads),
        successful_extractions=successful_extractions,
        valid_emails=valid_emails,
        duplicates_removed=merge_report["removed_count"],
        avg_score=round(sum(scores) / len(scores), 1) if scores else 0.0,
        high_value_count=sum(1 for lead in deduplicated if lead.high_value),
        processing_time_sec=round(time.monotonic() - start_time, 2),
        total_api_cost_usd=round(total_cost, 4),
        cache_hits=cache_hits,
    )
    logger.info(
        "Pipeline complete: %d lead(s) -> %d unique, avg score %.1f, cost $%.4f",
        stats.total_input,
        len(deduplicated),
        stats.avg_score,
        stats.total_api_cost_usd,
    )
    return deduplicated, stats


def _load_raw_leads(input_file: str) -> List[dict]:
    """Load raw lead rows from a ``.csv`` or ``.json`` file.

    Returns:
        A list of ``{"raw_text": str, "source": Optional[str]}`` dicts,
        one per non-empty ``raw_lead`` value found. Rows with a missing
        or empty ``raw_lead`` are skipped with a logged warning, not an
        error -- a handful of blank rows in a large CSV is normal.

    Raises:
        LeadScoringError: If the file doesn't exist, isn't a
            ``.csv``/``.json`` file, can't be parsed, or has no
            ``raw_lead`` field anywhere.
    """
    path = Path(input_file)
    if not path.exists():
        raise LeadScoringError(f"Input file not found: {input_file}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LeadScoringError(f"Could not parse {input_file} as JSON: {exc}") from exc
        if not isinstance(data, list):
            raise LeadScoringError(f"{input_file} must contain a JSON array of lead objects")
        rows = data
        has_raw_lead_field = any(isinstance(row, dict) and "raw_lead" in row for row in rows)
    elif suffix == ".csv":
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError as exc:
            raise LeadScoringError(f"Input CSV is empty: {input_file}") from exc
        except pd.errors.ParserError as exc:
            raise LeadScoringError(f"Could not parse {input_file} as CSV: {exc}") from exc
        has_raw_lead_field = "raw_lead" in frame.columns
        rows = frame.to_dict("records")
    else:
        raise LeadScoringError(
            f"Unsupported input file type (expected .csv or .json): {input_file}"
        )

    if rows and not has_raw_lead_field:
        raise LeadScoringError(f"{input_file} has no 'raw_lead' field in any row")

    raw_leads = []
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            logger.warning("Skipping row %d: not an object", row_number)
            continue
        raw_text = (row.get("raw_lead") or "").strip()
        if not raw_text:
            logger.warning("Skipping row %d: empty 'raw_lead' value", row_number)
            continue
        raw_leads.append({"raw_text": raw_text, "source": row.get("source") or None})
    return raw_leads
