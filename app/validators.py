"""
Pure validation and normalization helpers.

Nothing in here touches the database or the request/response cycle — that
makes these easy to call from anywhere (and to reason about / change
without worrying about side effects). Routes are responsible for turning a
ValueError raised here into the right HTTP response.
"""
import re
from datetime import datetime

from app.models import OfferType, IdentityType

# Required parameter fields per offer type, with a simple validator for
# each. A bare offer type with no values is explicitly disallowed by the
# spec, so every type here has at least one required numeric/text field.
OFFER_PARAM_SPECS = {
    OfferType.PRODUCT_PERCENT_DISCOUNT: {
        "percent": "number",       # e.g. 10
        "applies_to": "text",      # free-text SKU list / label
    },
    OfferType.CART_FIXED_DISCOUNT: {
        "amount_off": "number",
        "min_basket": "number",
    },
    OfferType.STICKER_EARN: {
        "stickers": "number",
        "per_amount": "number",
    },
}


def validate_offer_params(offer_type: OfferType, raw_params: dict) -> dict:
    """Validate raw form values for one offer, return cleaned params.

    Raises ValueError with a human-readable message on the first problem.
    """
    spec = OFFER_PARAM_SPECS[offer_type]
    cleaned = {}
    for field, kind in spec.items():
        value = raw_params.get(field)
        if value is None or str(value).strip() == "":
            raise ValueError(f"'{field}' is required for {offer_type.value}")
        if kind == "number":
            try:
                num = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"'{field}' must be a number")
            if num < 0:
                raise ValueError(f"'{field}' must not be negative")
            cleaned[field] = num
        else:
            cleaned[field] = str(value).strip()
    return cleaned


def validate_campaign_basics(name: str, description: str, starts_at: str, ends_at: str):
    """Validate the name/description/window fields from the builder form.

    starts_at/ends_at arrive as strings from an <input type="datetime-local">
    (e.g. "2026-07-01T10:00"). Returns (name, description, starts_dt, ends_dt).
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Campaign name is required")
    description = (description or "").strip()

    starts_dt = _parse_datetime_local(starts_at, "Start date")
    ends_dt = _parse_datetime_local(ends_at, "End date")
    return name, description, starts_dt, ends_dt


def _parse_datetime_local(value: str, label: str) -> datetime:
    if not value:
        raise ValueError(f"{label} is required")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} is not a valid date/time")


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_identity(raw: str):
    """Detect + normalize a shopper identity.

    Returns (IdentityType, normalized_string). Raises ValueError if it
    looks like neither an email nor a phone number.

    Normalization is intentionally a pragmatic pass, per the spec, not a
    full RFC/E.164 implementation:
      - email: trim + lowercase
      - phone: strip everything but digits and a leading '+'
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Please enter a phone number or email")

    if "@" in raw:
        if not EMAIL_RE.match(raw):
            raise ValueError("That doesn't look like a valid email")
        return IdentityType.EMAIL, raw.lower()

    digits = re.sub(r"[^\d+]", "", raw)
    digit_count = len(re.sub(r"\D", "", digits))
    if digit_count < 7:
        raise ValueError("That doesn't look like a valid phone number")
    return IdentityType.PHONE, digits
