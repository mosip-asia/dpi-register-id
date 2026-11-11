import base64
import pytest
from fastapi.testclient import TestClient
from mock.idrepo.app import idrepo_app
from register_id.cbeff import build_cbeff_xml
from register_id.idrepo_client import IDRepoClient

mock_client = TestClient(idrepo_app)


def test_mock_idrepo_generate_uin():
    res = mock_client.get("/v1/idgenerator/uin")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "mosip.idgenerator.uin"
    assert "uin" in data["response"]
    assert len(data["response"]["uin"]) == 10


def test_mock_idrepo_health():
    res = mock_client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UP"
    assert data["service"] == "mosip-id-repository"


def test_idrepo_client_crud_flow():
    client = IDRepoClient(enable_inprocess_fallback=True)

    uin = client.generate_uin()
    assert len(uin) == 10

    mock_jpeg_bytes = b"mock-jpeg-bytes-for-cbeff"
    cbeff_xml = build_cbeff_xml(uin=uin, jpeg_bytes=mock_jpeg_bytes)
    mock_embedding = [0.12] * 128

    # 1. Enroll citizen via MOSIP AddIdentity REST interface
    success = client.add_identity(
        uin=uin,
        full_name="Somchai Jaidee",
        email="somchai@dopa.gov.th",
        face_image="data:image/jpeg;base64,bW9jay1mYWNl",
        face_embedding=mock_embedding,
        cbeff_xml=cbeff_xml,
    )
    assert success is True

    # 2. Retrieve identity via MOSIP GetIdentity REST interface
    identity = client.get_identity(uin)
    assert identity is not None
    assert identity["uin"] == uin
    assert identity["full_name"] == "Somchai Jaidee"
    assert identity["email"] == "somchai@dopa.gov.th"
    assert identity["face_embedding"] == mock_embedding
    assert "<BIR" in identity["cbeff_xml"]

    # 3. List identities
    identities = client.list_identities(limit=10)
    assert any(i["uin"] == uin for i in identities)
