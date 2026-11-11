import base64
import pytest
from register_id.cbeff import (
    build_cbeff_xml,
    build_iso19794_5_record,
    extract_jpeg_bytes,
    parse_cbeff_xml,
)


def test_extract_jpeg_bytes():
    raw_data = b"fake-jpeg-content-12345"
    b64 = base64.b64encode(raw_data).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"

    assert extract_jpeg_bytes(data_url) == raw_data
    assert extract_jpeg_bytes(b64) == raw_data


def test_build_iso19794_5_record():
    jpeg = b"test-jpeg-stream"
    record = build_iso19794_5_record(jpeg, width=640, height=480)
    # Magic bytes check
    assert record[:4] == b"FAC\x00"
    assert record[4:8] == b"010\x00"
    assert jpeg in record


def test_build_and_parse_cbeff_xml():
    jpeg = b"mock-selfie-data"
    xml = build_cbeff_xml(uin="1234-5678-9012", jpeg_bytes=jpeg)
    assert '<?xml version="1.0"' in xml
    assert '<Format Owner="257" Type="8"' in xml
    assert "<BDB>" in xml

    parsed = parse_cbeff_xml(xml)
    assert parsed["formatOwner"] == "257"
    assert parsed["formatType"] == "8"
    assert parsed["rawBytesLength"] > 0
