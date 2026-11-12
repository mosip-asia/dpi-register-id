"""
Deterministic 128-D face embedding derived from image bytes.

Identical payloads produce the same unit vector. Different payloads land far
apart in Euclidean distance, which is what the 0.50 match threshold expects
until a real face model is wired in.
"""

import hashlib
import math

from register_id.cbeff import extract_jpeg_bytes


def embed_face_image(data_url_or_base64: str) -> list[float]:
    """
    Hash image bytes into a 128-D unit vector in [-1, 1].

    Empty input, undecodable input, and empty decoded bytes raise ValueError.
    """
    if not isinstance(data_url_or_base64, str) or not data_url_or_base64.strip():
        raise ValueError("face image is empty")

    try:
        data = extract_jpeg_bytes(data_url_or_base64)
    except Exception as exc:
        raise ValueError("face image could not be decoded") from exc

    if not data:
        raise ValueError("face image is empty")

    raw = bytearray()
    counter = 0
    while len(raw) < 128:
        raw.extend(hashlib.sha256(data + counter.to_bytes(4, "big")).digest())
        counter += 1

    # Map each hash byte onto [-1, 1]. 127.5 is not an integer, so no byte
    # lands on exactly zero and the pre-normalization vector cannot vanish.
    coords = [(byte / 127.5) - 1.0 for byte in raw[:128]]
    norm = math.sqrt(sum(value * value for value in coords))
    if norm == 0.0:
        raise ValueError("face embedding norm is zero")
    return [value / norm for value in coords]
