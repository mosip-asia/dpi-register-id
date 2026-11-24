"""MOSIP identity document fields for a Kit enrolment.

The pinned identity schema is the sixteen demographic fields below.
``individualBiometrics`` is a document, not one of these fields.
"""

from __future__ import annotations

from typing import Any

# Order matches the Kit identity schema pinned in tests/fixtures/identity-required.json.
IDENTITY_FIELDS: tuple[str, ...] = (
    "IDSchemaVersion",
    "UIN",
    "fullName",
    "dateOfBirth",
    "gender",
    "phone",
    "email",
    "addressLine1",
    "addressLine2",
    "addressLine3",
    "region",
    "province",
    "city",
    "zone",
    "postalCode",
    "referenceIdentityNumber",
)

_LANGUAGE_FIELDS = frozenset(
    {
        "fullName",
        "gender",
        "addressLine1",
        "addressLine2",
        "addressLine3",
        "region",
        "province",
        "city",
        "zone",
    }
)

SCHEMA_VERSION = 1.1


def _language(value: str) -> list[dict[str, str]]:
    return [{"language": "eng", "value": value}]


def mosip_date(value: str) -> str:
    """MOSIP stores a birth date as yyyy/MM/dd. The portal sends yyyy-MM-dd."""
    text = (value or "").strip()
    if len(text) >= 10 and text[4] in "-/" and text[7] in "-/":
        return f"{text[0:4]}/{text[5:7]}/{text[8:10]}"
    return text


def build_identity(
    *,
    uin: str,
    full_name: str,
    date_of_birth: str,
    gender: str,
    email: str | None,
    phone: str = "",
    address_line1: str = "",
    address_line2: str = "",
    address_line3: str = "",
    region: str = "",
    province: str = "",
    city: str = "",
    zone: str = "",
    postal_code: str = "",
    reference_identity_number: str = "",
) -> dict[str, Any]:
    """Return an identity object whose keys are exactly ``IDENTITY_FIELDS``."""
    raw: dict[str, str] = {
        "UIN": uin,
        "fullName": full_name,
        "dateOfBirth": mosip_date(date_of_birth),
        "gender": gender,
        "phone": phone,
        "email": email or "",
        "addressLine1": address_line1,
        "addressLine2": address_line2,
        "addressLine3": address_line3,
        "region": region,
        "province": province,
        "city": city,
        "zone": zone,
        "postalCode": postal_code,
        "referenceIdentityNumber": reference_identity_number,
    }
    identity: dict[str, Any] = {"IDSchemaVersion": SCHEMA_VERSION}
    for field in IDENTITY_FIELDS:
        if field == "IDSchemaVersion":
            continue
        value = raw[field]
        identity[field] = _language(value) if field in _LANGUAGE_FIELDS else value
    return identity
