"""Tests for lead_scoring_engine.validators.

Exercises the real email-phone-validator library (check_mx=False, so
these run fully offline) -- not mocked, since it's the same fast, local
validation this module exists to delegate to.
"""

import pytest

from lead_scoring_engine.models import LeadScoringError
from lead_scoring_engine.validators import validate_email, validate_phone


class TestValidateEmail:
    def test_valid_email_is_normalized_lowercase(self):
        is_valid, cleaned = validate_email("Jane.Doe@Example.COM")
        assert is_valid is True
        assert cleaned == "jane.doe@example.com"

    def test_none_is_invalid_without_raising(self):
        assert validate_email(None) == (False, None)

    def test_malformed_email_is_invalid_but_returned_as_given(self):
        is_valid, cleaned = validate_email("not-an-email")
        assert is_valid is False
        assert cleaned == "not-an-email"

    def test_whitespace_is_stripped_even_when_invalid(self):
        is_valid, cleaned = validate_email("  not-an-email  ")
        assert is_valid is False
        assert cleaned == "not-an-email"

    def test_empty_string_becomes_none(self):
        assert validate_email("   ") == (False, None)

    def test_wrong_type_raises(self):
        with pytest.raises(LeadScoringError):
            validate_email(12345)


class TestValidatePhone:
    def test_valid_us_phone_is_normalized_to_e164(self):
        is_valid, cleaned = validate_phone("(212) 555-0123")
        assert is_valid is True
        assert cleaned == "+12125550123"

    def test_none_is_invalid_without_raising(self):
        assert validate_phone(None) == (False, None)

    def test_missing_area_code_is_invalid_but_returned_as_given(self):
        # A real case found in this project's own sample_leads.csv.
        is_valid, cleaned = validate_phone("555-0199")
        assert is_valid is False
        assert cleaned == "555-0199"

    def test_reserved_555_area_code_is_invalid(self):
        # 555 is never a real NANP area code -- only valid as the *exchange*
        # in a real area code (e.g. "(212) 555-0123"), a real distinction
        # found while building this project's sample data.
        is_valid, _ = validate_phone("(555) 555-0123")
        assert is_valid is False

    def test_country_override(self):
        is_valid, cleaned = validate_phone("020 7946 0958", country="GB")
        assert is_valid is True
        assert cleaned == "+442079460958"

    def test_wrong_type_raises(self):
        with pytest.raises(LeadScoringError):
            validate_phone(12345)
