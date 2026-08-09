"""Email and phone validation for extracted lead data.

Deliberately thin: the real validation logic lives in
`email-phone-validator <https://github.com/Matthew-Cassin/email-phone-validator>`_,
already a tested, portfolio-grade library. Reimplementing email/phone
regexes here would both duplicate that work and be strictly worse --
a plain phone regex like ``^\\+?1?\\d{9,15}$`` rejects any formatted
number (``"(555) 555-0123"``, ``"555-0123"``) with punctuation still in
it, which is exactly what Claude's extraction returns.

This module keeps the simple ``(is_valid, cleaned_value)`` tuple shape
so the rest of the pipeline doesn't need to depend on
``email_phone_validator``'s richer ``ValidationResult`` directly.
"""

from __future__ import annotations

from functools import lru_cache

from email_phone_validator import EmailValidator, PhoneValidator

from .models import LeadScoringError

__all__ = ["validate_email", "validate_phone"]


@lru_cache(maxsize=1)
def _email_validator() -> EmailValidator:
    # check_mx=False: fast, offline format validation. MX lookups add
    # real per-lead latency and can false-negative on a flaky resolver;
    # use email_phone_validator directly with check_mx=True if you need
    # deliverability confidence rather than just "well-formed."
    return EmailValidator(check_mx=False)


@lru_cache(maxsize=1)
def _phone_validator() -> PhoneValidator:
    return PhoneValidator(default_country="US")


def validate_email(email: str | None) -> tuple[bool, str | None]:
    """Validate and normalize an extracted email address.

    Args:
        email: The address to validate, or ``None`` if extraction found
            none.

    Returns:
        ``(True, normalized_lowercased_address)`` if valid.
        ``(False, email.strip() or None)`` if invalid or missing -- the
        second element is whatever was given, unvalidated, so a caller
        can still display what was extracted even though it didn't
        pass validation; it is never a value you should treat as clean.

    Raises:
        LeadScoringError: If ``email`` is neither ``None`` nor a string.
    """
    if email is None:
        return False, None
    if not isinstance(email, str):
        raise LeadScoringError(f"email must be a string or None, got {type(email).__name__}")

    result = _email_validator().validate(email)
    if result.is_valid:
        return True, result.formatted
    return False, email.strip() or None


def validate_phone(
    phone: str | None, country: str | None = None
) -> tuple[bool, str | None]:
    """Validate and normalize an extracted phone number.

    Args:
        phone: The number to validate, or ``None`` if extraction found
            none.
        country: ISO region code to interpret ``phone`` against, e.g.
            ``"GB"``. Defaults to ``"US"`` (ignored if ``phone`` already
            starts with ``+``, which carries its own country code).

    Returns:
        ``(True, e164_formatted_number)`` if valid.
        ``(False, phone.strip() or None)`` if invalid or missing.

    Raises:
        LeadScoringError: If ``phone`` is neither ``None`` nor a string.
    """
    if phone is None:
        return False, None
    if not isinstance(phone, str):
        raise LeadScoringError(f"phone must be a string or None, got {type(phone).__name__}")

    result = _phone_validator().validate(phone, country=country)
    if result.is_valid:
        return True, result.formatted
    return False, phone.strip() or None
