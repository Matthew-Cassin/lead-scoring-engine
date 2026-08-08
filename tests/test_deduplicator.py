"""Tests for lead_scoring_engine.deduplicator.

Runs against the real contact-deduplicator library (fully local, no
network) -- not mocked, since duplicate detection is exactly the logic
this module delegates to.
"""

import pytest

from lead_scoring_engine.deduplicator import deduplicate_leads
from lead_scoring_engine.models import Lead, LeadScoringError


def _lead(id, **overrides):
    fields = dict(raw_text="...", extraction_succeeded=True)
    fields.update(overrides)
    return Lead(id=id, **fields)


class TestDeduplicateLeads:
    def test_empty_list(self):
        leads, report = deduplicate_leads([])
        assert leads == []
        assert report == {"duplicates_found": 0, "merged_count": 0, "removed_count": 0}

    def test_single_lead(self):
        leads, report = deduplicate_leads([_lead("a", email="x@x.com")])
        assert len(leads) == 1
        assert report["duplicates_found"] == 0

    def test_exact_email_match_merges(self):
        leads = [
            _lead("a", name="Dan", email="dan@x.com", company="Acme"),
            _lead("b", name="D. Reyes", email="dan@x.com", intent_signals="asked about pricing"),
        ]
        deduped, report = deduplicate_leads(leads)
        assert len(deduped) == 1
        assert report == {"duplicates_found": 1, "merged_count": 1, "removed_count": 1}
        merged = deduped[0]
        assert merged.email == "dan@x.com"
        assert merged.company == "Acme"  # carried over from the record that had it
        assert merged.intent_signals == "asked about pricing"
        assert merged.merged_from == ["b"]

    def test_exact_phone_match_merges(self):
        leads = [
            _lead("a", name="Carlos", phone="+14155550166", company="Palmetto"),
            _lead(
                "b",
                name="Carlos M.",
                phone="+14155550166",
                intent_signals="trade show follow-up",
            ),
        ]
        deduped, report = deduplicate_leads(leads)
        assert len(deduped) == 1
        assert deduped[0].company == "Palmetto"
        assert deduped[0].intent_signals == "trade show follow-up"

    def test_fuzzy_name_match_merges_above_threshold(self):
        leads = [
            _lead("a", name="Jonathan Smithson", company="Acme"),
            _lead("b", name="Jonathan Smithsen", company="Acme"),  # one-letter typo
        ]
        deduped, _ = deduplicate_leads(leads, threshold=0.85)
        assert len(deduped) == 1

    def test_no_shared_signal_does_not_merge(self):
        leads = [
            _lead("a", name="Alice Anderson", email="alice@x.com"),
            _lead("b", name="Bob Baker", email="bob@x.com"),
        ]
        deduped, report = deduplicate_leads(leads)
        assert len(deduped) == 2
        assert report["duplicates_found"] == 0

    def test_extraction_succeeded_true_if_any_group_member_succeeded(self):
        leads = [
            _lead("a", email="x@x.com", extraction_succeeded=False),
            _lead("b", email="x@x.com", extraction_succeeded=True),
        ]
        deduped, _ = deduplicate_leads(leads)
        assert deduped[0].extraction_succeeded is True

    def test_email_valid_flag_follows_the_winning_email_value(self):
        # Two records share a phone (so they merge); one has a validated
        # email the other lacks. The merged record's email_valid should
        # describe whichever email the merge actually kept.
        leads = [
            _lead("a", phone="+14155550166", email=None, email_valid=None),
            _lead("b", phone="+14155550166", email="dan@x.com", email_valid=True),
        ]
        deduped, _ = deduplicate_leads(leads)
        assert deduped[0].email == "dan@x.com"
        assert deduped[0].email_valid is True

    def test_not_a_list_raises(self):
        with pytest.raises(LeadScoringError):
            deduplicate_leads("not a list")

    def test_bad_threshold_raises(self):
        with pytest.raises(LeadScoringError):
            deduplicate_leads([_lead("a"), _lead("b")], threshold=1.5)
