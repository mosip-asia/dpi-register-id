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
    # MOSIP IDRepo validates against mosip-cbeff.xsd: ISO 19785-3 ed-2 namespace, nested face BIR.
    assert '<BIR xmlns="http://standards.iso.org/iso-iec/19785/-3/ed-2/">' in xml
    assert "<Format><Organization>Mosip</Organization><Type>8</Type></Format>" in xml
    assert "<Type>Face</Type>" in xml and "<Level>Raw</Level>" in xml
    assert "<BDB>" in xml

    ns = "{http://standards.iso.org/iso-iec/19785/-3/ed-2/}"
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    face = root.find(f"{ns}BIR")
    assert face is not None and face.find(f"{ns}BDBInfo/{ns}Type").text == "Face"
    assert face.find(f"{ns}BDB").text

    parsed = parse_cbeff_xml(xml)
    assert parsed["formatOwner"] == "Mosip"
    assert parsed["formatType"] == "8"
    assert parsed["rawBytesLength"] > 0


def test_cbeff_carries_face_descriptors_for_verify():
    """A real MOSIP IDRepo has no template endpoint, so the descriptors ride in the CBEFF `others` section."""
    from register_id.cbeff import descriptors_from_cbeff

    vectors = [[0.1] * 128, [0.25] * 128]
    xml = build_cbeff_xml(uin="2459857015", jpeg_bytes=b"jpeg", descriptors=vectors)
    assert '<entry key="face-api-128#0">' in xml
    # `others` must follow BDB inside the face BIR (XSD sequence order).
    assert xml.index("<BDB>") < xml.index("<others>") < xml.index("</BIR>")
    assert descriptors_from_cbeff(xml) == vectors
    assert descriptors_from_cbeff(build_cbeff_xml(uin="1", jpeg_bytes=b"jpeg")) == []
    assert descriptors_from_cbeff("not xml") == []
