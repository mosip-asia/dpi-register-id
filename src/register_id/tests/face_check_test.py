import base64

import pytest

from register_id.embedder import CAN_IDENTIFY_FACE, ENGINE_NAME, embed_face_image
from register_id.face_check import (
    assess_capture,
    compare_probe,
    engine_can_identify_face,
    estimate_yaw_degrees,
    may_store_biometric_record,
)


def _data_url(payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def test_hash_embedder_declares_it_cannot_identify_a_face():
    assert ENGINE_NAME == "hash"
    assert CAN_IDENTIFY_FACE is False


def test_unset_and_hash_engines_cannot_identify_a_face(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FACE_ENGINE", raising=False)
    assert engine_can_identify_face() is False

    monkeypatch.setenv("FACE_ENGINE", "hash")
    assert engine_can_identify_face() is False

    monkeypatch.setenv("FACE_ENGINE", "  HASH  ")
    assert engine_can_identify_face() is False

    monkeypatch.setenv("FACE_ENGINE", "")
    assert engine_can_identify_face() is False


def test_hash_engine_is_not_a_face_match(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FACE_ENGINE", raising=False)
    stored = embed_face_image(_data_url(b"citizen-face-alpha"))
    probe = embed_face_image(_data_url(b"citizen-face-beta"))

    result = compare_probe([stored], probe)

    assert result.is_face_match is False
    assert result.duplicate_of_stored is False
    assert result.distance is None
    assert result.score is None
    assert result.threshold is None
    assert result.engine == "hash"


def test_duplicate_hash_sets_duplicate_of_stored_and_is_not_a_face_match():
    vector = embed_face_image(_data_url(b"same-jpeg-bytes"))
    other = embed_face_image(_data_url(b"different-jpeg-bytes"))

    result = compare_probe([other, vector], list(vector))

    assert result.duplicate_of_stored is True
    assert result.is_face_match is False
    assert result.distance is None
    assert result.score is None
    assert result.threshold is None
    assert result.engine == "hash"


def test_named_face_engine_still_does_not_match(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FACE_ENGINE", "insightface")
    assert engine_can_identify_face() is True

    vector = embed_face_image(_data_url(b"same-jpeg-bytes"))
    result = compare_probe([vector], vector)

    assert result.is_face_match is False
    assert result.duplicate_of_stored is True
    assert result.distance is None
    assert result.score is None
    assert result.engine == "hash"


def test_client_yaw_is_not_yaw_measured():
    images = [_data_url(b"frame-left"), _data_url(b"frame-front"), _data_url(b"frame-right")]
    client_yaws = [-32.0, 0.0, 28.5]

    assert estimate_yaw_degrees(images) is None

    assessment = assess_capture(images, client_yaws)

    assert assessment.yaw_measured is False
    assert assessment.yaw_degrees is None
    assert assessment.presentation_passed is False
    assert assessment.presentation_detail == (
        "The server did not measure the head turn or liveness from the pixels."
    )
    assert client_yaws == [-32.0, 0.0, 28.5]


def test_may_store_biometric_record_is_false_for_the_current_engine(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("FACE_ENGINE", raising=False)
    assessment = assess_capture([_data_url(b"front")], [0.0])

    assert assessment.presentation_passed is False
    assert engine_can_identify_face() is False
    assert (
        may_store_biometric_record(
            assessment.presentation_passed,
            engine_can_identify_face(),
        )
        is False
    )
    assert may_store_biometric_record(True, False) is False
    assert may_store_biometric_record(False, True) is False
    assert may_store_biometric_record(False, False) is False
    assert may_store_biometric_record(True, True) is True
