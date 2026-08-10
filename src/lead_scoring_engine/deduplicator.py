"""Duplicate lead detection and merging.

Built on top of `contact-deduplicator
<https://github.com/Matthew-Cassin/contact-deduplicator>`_'s public
``ContactDeduplicator`` rather than reimplementing fuzzy matching here.
Its ``Contact`` model only tracks five generic fields (name, email,
phone, company, address), so this module maps each ``Lead`` to a
``Contact`` stand-in, lets ``ContactDeduplicator`` do the actual
duplicate-detection and contact-field merging, then reapplies that same
grouping to the full ``Lead`` records -- carrying over the
lead-specific fields (``industry``, ``intent_signals``, extraction/
validation state) that ``Contact`` knows nothing about.
"""

from __future__ import annotations

from dataclasses import replace

from contact_deduplicator import Contact, ContactDeduplicator, DeduplicationError

from . import config
from .logger import get_logger
from .models import Lead, LeadScoringError

logger = get_logger("deduplicator")

__all__ = ["deduplicate_leads"]

# Mirrors contact_deduplicator.matcher.calculate_completeness's formula
# (fraction of 5 tracked fields that are non-null) rather than importing
# that helper, since it isn't part of contact-deduplicator's public
# __init__.py surface -- reimplementing one line here is cheaper than
# depending on another package's internal module layout.
_TRACKED_CONTACT_FIELDS = 5


def _completeness(
    name: str | None, email: str | None, phone: str | None, company: str | None
) -> float:
    """Fraction of the 5 Contact-tracked fields that are non-null (address is always None here)."""
    return sum(1 for value in (name, email, phone, company) if value) / _TRACKED_CONTACT_FIELDS


def _longest(values: list[str | None]) -> str | None:
    """The longest non-null value in ``values``, or None if all are null -- the same
    "most complete wins" heuristic contact-deduplicator itself uses for merging."""
    candidates = [v for v in values if v]
    return max(candidates, key=len) if candidates else None


def deduplicate_leads(
    leads: list[Lead], threshold: float = config.DEDUP_THRESHOLD
) -> tuple[list[Lead], dict[str, int]]:
    """Detect and merge duplicate leads.

    Args:
        leads: The leads to deduplicate, typically after extraction and
            validation but before scoring.
        threshold: Minimum fuzzy name-match similarity (``0.0``-``1.0``)
            for two leads with no matching email/phone to be considered
            duplicates. Forwarded to
            ``ContactDeduplicator(name_similarity_threshold=...)``.

    Returns:
        A ``(deduplicated_leads, merge_report)`` tuple. ``merge_report``
        has the shape ``{"duplicates_found": int, "merged_count": int,
        "removed_count": int}`` -- ``duplicates_found`` and
        ``removed_count`` are the same number (every record folded into
        another counts as one removed original), reported under both
        names to match the field the rest of this pipeline's callers
        expect.

    Raises:
        LeadScoringError: If ``leads`` is not a list, or ``threshold``
            is outside ``0.0``-``1.0`` (surfaced from
            ``ContactDeduplicator``'s own validation).
    """
    if not isinstance(leads, list):
        raise LeadScoringError(f"leads must be a list, got {type(leads).__name__}")

    if len(leads) < 2:
        return list(leads), {"duplicates_found": 0, "merged_count": 0, "removed_count": 0}

    try:
        contact_deduplicator = ContactDeduplicator(
            name_similarity_threshold=threshold, skip_validation=True
        )
    except DeduplicationError as exc:
        raise LeadScoringError(str(exc)) from exc

    contacts = [
        Contact(
            id=lead.id,
            name=lead.name,
            email=lead.email,
            phone=lead.phone,
            company=lead.company,
            address=None,
            completeness_score=_completeness(lead.name, lead.email, lead.phone, lead.company),
        )
        for lead in leads
    ]

    result = contact_deduplicator.deduplicate(contacts)
    lead_by_id = {lead.id: lead for lead in leads}
    grouped_ids = {
        lead_id
        for action in result.merge_actions
        for lead_id in [action.primary_id, *action.merged_ids]
    }

    deduplicated: list[Lead] = []
    for action in result.merge_actions:
        group = [lead_by_id[action.primary_id]] + [lead_by_id[i] for i in action.merged_ids]
        primary = lead_by_id[action.primary_id]
        merged = replace(
            primary,
            id=action.primary_id,
            name=action.merged_contact.name,
            email=action.merged_contact.email,
            phone=action.merged_contact.phone,
            company=action.merged_contact.company,
            industry=_longest([lead.industry for lead in group]),
            intent_signals=_longest([lead.intent_signals for lead in group]),
            extraction_succeeded=any(lead.extraction_succeeded for lead in group),
            email_valid=next(
                (lead.email_valid for lead in group if lead.email == action.merged_contact.email),
                None,
            ),
            phone_valid=next(
                (lead.phone_valid for lead in group if lead.phone == action.merged_contact.phone),
                None,
            ),
            merged_from=action.merged_ids,
        )
        deduplicated.append(merged)
        logger.info(
            "Merged %d duplicate(s) into %s (%s)",
            len(action.merged_ids),
            action.primary_id,
            action.reason,
        )

    deduplicated.extend(lead for lead in leads if lead.id not in grouped_ids)

    merge_report = {
        "duplicates_found": result.duplicates_found,
        "merged_count": len(result.merge_actions),
        "removed_count": result.duplicates_found,
    }
    logger.info(
        "Deduplication complete: %d lead(s) -> %d unique (%d removed)",
        len(leads),
        len(deduplicated),
        merge_report["removed_count"],
    )
    return deduplicated, merge_report
