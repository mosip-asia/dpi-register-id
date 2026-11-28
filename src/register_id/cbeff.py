"""
ISO/IEC 19794-5 (Face Image Data) & ISO 19785-3 CBEFF XML Serialization.

Packages citizen face biometric images into standard MOSIP-compliant
CBEFF envelopes for upstream IDRepo and BioSDK interoperability.
"""

import base64
import json
import struct
import uuid
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

CBEFF_NAMESPACE = "http://standards.iso.org/iso-iec/19785/-3/ed-2/"
FORMAT_ORGANIZATION = "Mosip"
FORMAT_TYPE_FACE = "8"


def extract_jpeg_bytes(data_url_or_base64: str) -> bytes:
    """
    Extracts raw image bytes from either a base64 Data URL (e.g. data:image/jpeg;base64,...)
    or a plain base64 string.
    """
    if "," in data_url_or_base64:
        _, encoded = data_url_or_base64.split(",", 1)
    else:
        encoded = data_url_or_base64
    return base64.b64decode(encoded.strip())


def build_iso19794_5_record(
    jpeg_bytes: bytes,
    width: int = 640,
    height: int = 480,
) -> bytes:
    """
    Constructs an ISO/IEC 19794-5 binary face record:
    - 4-byte Magic Identifier: b'FAC\\x00'
    - 4-byte Version: b'010\\x00'
    - 4-byte Total Record Length
    - 2-byte Number of Facial Images: 1
    - 1-byte Record Header Length: 14
    - Image Information Header:
        - 4-byte Image Data Length
        - 2-byte Width
        - 2-byte Height
        - 1-byte Image Data Type: 0 (JPEG)
    - Raw JPEG bytes
    """
    header_magic = b"FAC\x00"
    header_version = b"010\x00"
    num_images = 1
    record_header_len = 14
    image_data_type = 0  # 0 = JPEG, 1 = JPEG2000

    img_data_len = len(jpeg_bytes)
    total_length = record_header_len + 9 + img_data_len

    # Pack record header (4 + 4 + 4 + 2 = 14 bytes)
    record_header = struct.pack(
        ">4s4sIH",
        header_magic,
        header_version,
        total_length,
        num_images,
    )

    # Pack facial information header (4 + 2 + 2 + 1 = 9 bytes)
    facial_info_header = struct.pack(
        ">IHHB",
        img_data_len,
        width,
        height,
        image_data_type,
    )

    return record_header + facial_info_header + jpeg_bytes


def build_cbeff_xml(
    uin: str,
    jpeg_bytes: bytes,
    width: int = 640,
    height: int = 480,
    descriptors: list[list[float]] | None = None,
    descriptor_engine: str = "face-api-128",
) -> str:
    """
    Wraps an ISO/IEC 19794-5 binary face record into the CBEFF XML a MOSIP ID Repository accepts.

    Layout follows mosip-config `mosip-cbeff.xsd` (ISO/IEC 19785-3 ed-2 namespace): an outer BIR with
    BIRInfo, holding one face BIR with BDBInfo (Index, Format Mosip/8, CreationDate, Type Face,
    Level Raw, Purpose Enroll, Quality) and the BDB. The real IDRepo validates the document against
    that XSD and rejects other shapes ("Cannot find the declaration of element 'BIR'").

    `descriptors` (the browser's face-api match vectors) go in the face BIR's `others` section as
    `<entry key="face-api-128#0">[...]</entry>`, which the XSD allows. The real ID Repository has no
    endpoint for app-specific match templates, so this is how verify finds them there.
    """
    iso_record = build_iso19794_5_record(jpeg_bytes, width=width, height=height)
    bdb_base64 = base64.b64encode(iso_record).decode("utf-8")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index = str(uuid.uuid4())
    del uin  # the UIN is not part of a CBEFF record

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<BIR xmlns="{CBEFF_NAMESPACE}">',
        '  <Version><Major>1</Major><Minor>1</Minor></Version>',
        '  <CBEFFVersion><Major>1</Major><Minor>1</Minor></CBEFFVersion>',
        '  <BIRInfo><Integrity>false</Integrity></BIRInfo>',
        '  <BIR>',
        '    <Version><Major>1</Major><Minor>1</Minor></Version>',
        '    <CBEFFVersion><Major>1</Major><Minor>1</Minor></CBEFFVersion>',
        '    <BIRInfo><Integrity>false</Integrity></BIRInfo>',
        '    <BDBInfo>',
        f'      <Index>{index}</Index>',
        f'      <Format><Organization>{FORMAT_ORGANIZATION}</Organization><Type>{FORMAT_TYPE_FACE}</Type></Format>',
        f'      <CreationDate>{now_iso}</CreationDate>',
        '      <Type>Face</Type>',
        '      <Subtype></Subtype>',
        '      <Level>Raw</Level>',
        '      <Purpose>Enroll</Purpose>',
        '      <Quality><Algorithm><Organization>HMAC</Organization><Type>SHA-256</Type></Algorithm>'
        '<Score>90</Score></Quality>',
        '    </BDBInfo>',
        f'    <BDB>{bdb_base64}</BDB>',
    ]
    if descriptors:
        xml_lines.append('    <others>')
        for i, vector in enumerate(descriptors):
            values = json.dumps([float(v) for v in vector], separators=(",", ":"))
            xml_lines.append(f'      <entry key="{escape(descriptor_engine)}#{i}">{values}</entry>')
        xml_lines.append('    </others>')
    xml_lines += [
        '  </BIR>',
        '</BIR>',
    ]
    return "\n".join(xml_lines)


def descriptors_from_cbeff(xml_content: str, descriptor_engine: str = "face-api-128") -> list[list[float]]:
    """Return the match vectors stored by build_cbeff_xml(descriptors=...). Missing or broken entries are skipped."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []
    vectors = []
    for elem in root.iter():
        if elem.tag.split("}", 1)[-1] != "entry":
            continue
        key = elem.get("key", "")
        if not key.startswith(f"{descriptor_engine}#") or not elem.text:
            continue
        try:
            values = json.loads(elem.text)
        except ValueError:
            continue
        if isinstance(values, list) and all(isinstance(v, (int, float)) for v in values):
            vectors.append([float(v) for v in values])
    return vectors


def parse_cbeff_xml(xml_content: str) -> dict:
    """
    Parses a CBEFF XML document and extracts BDB payload and metadata.
    """
    root = ET.fromstring(xml_content)
    # Strip XML namespace if present
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]

    # The face BDB sits in a nested BIR (MOSIP layout); older single-BIR documents keep it at the top.
    bdb_elem = next((e for e in root.iter("BDB") if e.text and e.text.strip()), None)
    bdb_base64 = bdb_elem.text.strip() if bdb_elem is not None else ""
    fmt = next(root.iter("Format"), None)
    organization = fmt.findtext("Organization") if fmt is not None else None
    format_type = fmt.findtext("Type") if fmt is not None else None

    return {
        "version": "1.1",
        "formatOwner": organization or (fmt.get("Owner") if fmt is not None else None) or FORMAT_ORGANIZATION,
        "formatType": format_type or (fmt.get("Type") if fmt is not None else None) or FORMAT_TYPE_FACE,
        "bdbBase64": bdb_base64,
        "rawBytesLength": len(base64.b64decode(bdb_base64)) if bdb_base64 else 0,
    }
