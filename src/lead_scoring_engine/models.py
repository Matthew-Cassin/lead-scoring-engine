"""Core data structures for lead-scoring-engine.

``Lead`` is the record that flows through the whole pipeline, gaining
fields as each stage runs. ``ExtractionResult`` and ``ScoreResult`` are
what the two Claude-backed stages return before their fields get folded
into a ``Lead``. ``ApiUsage`` tracks token counts and estimated cost for
a single Claude API call. ``ProcessingStats`` summarizes a full pipeline
run. ``LeadScoringError`` is the package's single exception type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "ApiUsage",
    "ExtractionResult",
    "Lead",
    "LeadScoringError",
    "ProcessingStats",
    "ScoreResult",
]


@dataclass
class ApiUsage:
    """Token usage and estimated USD cost for a single Claude API call.

    Attributes:
        input_tokens: Input tokens billed for the call.
        output_tokens: Output tokens billed for the call.
        cost_usd: Estimated cost, computed from
            :data:`~lead_scoring_engine.config.PRICING_PER_MTOK_USD`.
            An estimate, not an invoice -- see that module's docstring
            for how it can drift from your actual bill.
    """

    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class Lead:
    """A single lead record as it moves through the pipeline.

    Every field past ``id``/``raw_text``/``source`` starts ``None`` and
    is filled in by a later pipeline stage. ``None`` always means "not
    yet known," never "invalid" -- an invalid email or phone is instead
    reported through ``email_valid``/``phone_valid`` being ``False``
    while ``email``/``phone`` still hold the (unusable) extracted value,
    matching how every validator in this portfolio treats bad data as
    an ordinary result rather than an exception.

    Attributes:
        id: Stable identifier for this record within a single pipeline
            run (e.g. ``"lead-3"`` for the third input row).
        raw_text: The original unstructured lead text this record was
            extracted from.
        source: Where the raw lead came from, if the input format
            supplied one (e.g. ``"form_submission"``).
        name, email, phone, company, industry, intent_signals: Fields
            populated by :mod:`~lead_scoring_engine.claude_extractor`.
        extraction_succeeded: Whether extraction produced usable fields
            at all. ``False`` means every extracted field is unreliable
            and this record should generally be excluded from scoring.
        extraction_error: Why extraction failed, when it did.
        email_valid, phone_valid: Populated by
            :mod:`~lead_scoring_engine.validators`. ``None`` if the
            corresponding field was never extracted, so there was
            nothing to validate.
        score, score_reasoning, high_value, follow_up_tactic: Populated
            by :mod:`~lead_scoring_engine.claude_scorer`.
        merged_from: The ``id``\\ s of other records folded into this
            one during deduplication, empty if this record was never
            part of a duplicate group.
    """

    id: str
    raw_text: str
    source: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    industry: str | None = None
    intent_signals: str | None = None
    extraction_succeeded: bool = False
    extraction_error: str | None = None
    email_valid: bool | None = None
    phone_valid: bool | None = None
    score: int | None = None
    score_reasoning: str | None = None
    high_value: bool | None = None
    follow_up_tactic: str | None = None
    merged_from: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """The outcome of extracting structured fields from one raw lead.

    Attributes:
        success: Whether Claude returned a parseable extraction. Fields
            below are only meaningful when this is ``True``.
        name, email, phone, company, industry, intent_signals: The
            extracted fields, ``None`` for any Claude reported as not
            found.
        error: Human-readable failure reason, set only when
            ``success`` is ``False`` (e.g. an API error after retries,
            or a response that wasn't valid JSON).
        usage: Token usage/cost for the call that produced this result,
            or ``None`` if the result came from cache (see
            ``from_cache``) and no call was made.
        from_cache: Whether this result was served from the local
            extraction cache instead of calling the API.
    """

    success: bool
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    industry: str | None = None
    intent_signals: str | None = None
    error: str | None = None
    usage: ApiUsage | None = None
    from_cache: bool = False


@dataclass
class ScoreResult:
    """The outcome of scoring one lead's likelihood to convert.

    Attributes:
        success: Whether Claude returned a parseable score. Fields
            below are only meaningful when this is ``True``.
        score: Conversion-likelihood score, ``0``-``100``.
        reasoning: Claude's brief explanation for the score.
        high_value: Whether Claude flagged this as a high-value lead.
        follow_up_tactic: Claude's suggested next action.
        error: Human-readable failure reason, set only when
            ``success`` is ``False``.
        usage: Token usage/cost for the call that produced this result,
            or ``None`` if served from cache.
        from_cache: Whether this result was served from the local
            scoring cache instead of calling the API.
    """

    success: bool
    score: int | None = None
    reasoning: str | None = None
    high_value: bool | None = None
    follow_up_tactic: str | None = None
    error: str | None = None
    usage: ApiUsage | None = None
    from_cache: bool = False


@dataclass
class ProcessingStats:
    """Summary statistics for one full pipeline run.

    Attributes:
        total_input: Number of raw leads given to the pipeline.
        successful_extractions: Leads where extraction succeeded.
        valid_emails: Leads with a validated, deliverable-looking email.
        duplicates_removed: Records folded away during deduplication
            (``total_input`` minus the unique-record count, *before*
            any per-record extraction failures are considered).
        avg_score: Mean score across leads that were successfully
            scored. ``0.0`` if none were.
        high_value_count: Leads flagged ``high_value`` by the scorer.
        processing_time_sec: Wall-clock time for the whole run.
        total_api_cost_usd: Sum of every ``ApiUsage.cost_usd`` incurred,
            across both extraction and scoring, excluding cache hits.
        cache_hits: Extraction + scoring calls served from cache instead
            of hitting the API.
    """

    total_input: int
    successful_extractions: int
    valid_emails: int
    duplicates_removed: int
    avg_score: float
    high_value_count: int
    processing_time_sec: float
    total_api_cost_usd: float
    cache_hits: int = 0


class LeadScoringError(Exception):
    """Raised when an operation can't be attempted at all, not just when data is messy.

    Messy or incomplete *lead* data is never an exception here -- a raw
    lead Claude can't extract anything useful from, an invalid email, a
    borderline score -- these are the everyday input this package exists
    to handle, and are always reported through ``ExtractionResult``,
    ``ScoreResult``, or ``Lead`` fields instead. ``LeadScoringError`` is
    reserved for cases the caller must fix in code, such as:

    * Invalid configuration (e.g. a negative ``max_retries``, or a
      ``dedup_threshold`` outside ``0.0``-``1.0``).
    * Missing API credentials.
    * An input file that can't be read at all (missing, empty,
      unparseable) -- as opposed to one that reads fine but has messy
      *values*.
    * Calling a method with the wrong argument type.
    """
