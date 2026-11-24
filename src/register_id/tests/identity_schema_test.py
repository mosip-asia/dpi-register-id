"""The enrol identity document matches the Kit's sixteen-field schema."""

import json
import re
from pathlib import Path

from register_id.identity_schema import build_identity

_REQUIRED_FIELDS = Path(__file__).parent / "fixtures" / "identity-required.json"
_MOSIP_DATE = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def test_identity_document_has_the_kit_fields():
    required = json.loads(_REQUIRED_FIELDS.read_text(encoding="utf-8"))
    identity = build_identity(
        uin="1234567890",
        full_name="Ada Lovelace",
        date_of_birth="1990-12-10",
        gender="Female",
        email="ada@example.com",
        phone="0812345678",
        address_line1="1 Register Road",
        address_line2="",
        address_line3="",
        region="Bangkok",
        province="Bangkok",
        city="Pathum Wan",
        zone="1",
        postal_code="10330",
        reference_identity_number="REF-1",
    )
    assert list(identity) == required
    assert len(required) == 16
    assert identity["IDSchemaVersion"] == 1.1
    assert _MOSIP_DATE.fullmatch(identity["dateOfBirth"])
    assert identity["dateOfBirth"] == "1990/12/10"
    assert identity["gender"] == [{"language": "eng", "value": "Female"}]
    assert identity["fullName"] == [{"language": "eng", "value": "Ada Lovelace"}]
    assert "faceImage" not in identity
    assert "individualBiometrics" not in identity
