"""
ISO/IEC 19794-5 (Face Image Data) & ISO 19785-3 CBEFF XML Serialization.

Packages citizen face biometric images into standard MOSIP-compliant
CBEFF envelopes for upstream IDRepo and BioSDK interoperability.
"""

import base64
import struct
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


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
) -> str:
    """
    Wraps an ISO/IEC 19794-5 binary face record into an ISO 19785-3 CBEFF XML structure.
    MOSIP Format Owner: 257 (0x0101)
    MOSIP Format Type: 8 (Face)
    """
    iso_record = build_iso19794_5_record(jpeg_bytes, width=width, height=height)
    bdb_base64 = base64.b64encode(iso_record).decode("utf-8")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<BIR xmlns="http://standards.iso.org/iso-iec/19785/-3/ed-1/">',
        '  <Version>',
        '    <Major>1</Major>',
        '    <Minor>1</Minor>',
        '  </Version>',
        '  <CBEFFVersion>',
        '    <Major>2</Major>',
        '    <Minor>0</Minor>',
        '  </CBEFFVersion>',
        '  <BIRInfo>',
        '    <Integrity>false</Integrity>',
        '  </BIRInfo>',
        '  <BDBInfo>',
        f'    <Format Owner="257" Type="8" />',
        '    <Type>Face</Type>',
        '    <Subtype>Frontal</Subtype>',
        '    <Purpose>Enroll</Purpose>',
        '    <Quality>90</Quality>',
        f'    <CreationDate>{now_iso}</CreationDate>',
        '  </BDBInfo>',
        f'  <BDB>{bdb_base64}</BDB>',
        '</BIR>',
    ]
    return "\n".join(xml_lines)


def parse_cbeff_xml(xml_content: str) -> dict:
    """
    Parses a CBEFF XML document and extracts BDB payload and metadata.
    """
    root = ET.fromstring(xml_content)
    # Strip XML namespace if present
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]

    bdb_elem = root.find("BDB")
    bdb_base64 = bdb_elem.text.strip() if bdb_elem is not None and bdb_elem.text else ""

    return {
        "version": "1.1",
        "formatOwner": "257",
        "formatType": "8",
        "bdbBase64": bdb_base64,
        "rawBytesLength": len(base64.b64decode(bdb_base64)) if bdb_base64 else 0,
    }
