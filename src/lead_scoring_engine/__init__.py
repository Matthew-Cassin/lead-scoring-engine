"""lead-scoring-engine: AI-powered lead extraction, deduplication, and scoring.

Ingests messy, unstructured lead text (a form submission, a scraped web
page, a pasted email) and turns it into structured, deduplicated,
scored leads: Claude extracts name/email/phone/company/industry/intent
signals, `email-phone-validator
<https://github.com/Matthew-Cassin/email-phone-validator>`_ validates
the contact fields, `contact-deduplicator
<https://github.com/Matthew-Cassin/contact-deduplicator>`_ merges
duplicate records, and Claude scores each lead 0-100 on likelihood to
convert within 30 days.

Public API:
    process_leads: The main entry point -- run the full pipeline over a
        CSV/JSON file of raw leads.
    ClaudeExtractor: The extraction stage, usable standalone.
    ClaudeScorer: The scoring stage, usable standalone.
    validate_email / validate_phone: The validation stage's functions.
    deduplicate_leads: The deduplication stage's function.
    export_csv / export_json / generate_summary_report /
        generate_email_digest: Output helpers ``process_leads``'
        results are typically passed to.
    Lead: The record that flows through the whole pipeline.
    ApiUsage, ExtractionResult, ScoreResult, ProcessingStats: Supporting
        result/statistics dataclasses.
    LeadScoringError: Raised for unrecoverable errors (bad configuration
        or wrong argument types) as distinct from merely messy lead
        data, a failed extraction, or a failed score, which are never
        exceptions -- see its docstring.

Example:
    >>> from lead_scoring_engine import process_leads  # doctest: +SKIP
    >>> leads, stats = process_leads("sample_leads.csv")  # doctest: +SKIP
    >>> stats.avg_score  # doctest: +SKIP
    72.4
"""

from .claude_extractor import ClaudeExtractor
from .claude_scorer import ClaudeScorer
from .deduplicator import deduplicate_leads
from .exporter import export_csv, export_json, generate_email_digest, generate_summary_report
from .lead_processor import process_leads
from .models import ApiUsage, ExtractionResult, Lead, LeadScoringError, ProcessingStats, ScoreResult
from .validators import validate_email, validate_phone

__version__ = "0.1.0"

__all__ = [
    "process_leads",
    "ClaudeExtractor",
    "ClaudeScorer",
    "validate_email",
    "validate_phone",
    "deduplicate_leads",
    "export_csv",
    "export_json",
    "generate_summary_report",
    "generate_email_digest",
    "Lead",
    "ApiUsage",
    "ExtractionResult",
    "ScoreResult",
    "ProcessingStats",
    "LeadScoringError",
    "__version__",
]
