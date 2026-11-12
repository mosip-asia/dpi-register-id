import base64
import math

import pytest

from register_id.embedder import embed_face_image


def _data_url(payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def test_identical_bytes_produce_the_same_unit_vector():
    data_url = _data_url(b"same-face-bytes")
    plain = base64.b64encode(b"same-face-bytes").decode("utf-8")

    first = embed_face_image(data_url)
    second = embed_face_image(data_url)
    from_plain = embed_face_image(plain)

    assert first == second
    assert first == from_plain
    assert _distance(first, second) == 0.0
    assert len(first) == 128
    assert abs(math.sqrt(sum(value * value for value in first)) - 1.0) < 1e-9
    assert all(-1.0 <= value <= 1.0 for value in first)


def test_different_bytes_are_farther_than_the_match_threshold():
    left = embed_face_image(_data_url(b"citizen-face-alpha"))
    right = embed_face_image(_data_url(b"citizen-face-beta"))

    assert len(left) == 128
    assert len(right) == 128
    assert _distance(left, right) >= 0.50


def test_empty_input_raises_value_error():
    with pytest.raises(ValueError):
        embed_face_image("")
    with pytest.raises(ValueError):
        embed_face_image("   ")
    with pytest.raises(ValueError):
        embed_face_image("data:image/jpeg;base64,")
