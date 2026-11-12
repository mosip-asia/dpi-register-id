import base64

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
    templates = [
        {"sector": "far-left", "embedding": [0.11] * 128},
        {"sector": "left", "embedding": [0.12] * 128},
        {"sector": "front", "embedding": [0.13] * 128},
        {"sector": "right", "embedding": [0.14] * 128},
        {"sector": "far-right", "embedding": [0.15] * 128},
    ]

    success = client.add_identity(
        uin=uin,
        full_name="Somchai Jaidee",
        email="somchai@dopa.gov.th",
        face_image="data:image/jpeg;base64,bW9jay1mYWNl",
        cbeff_xml=cbeff_xml,
        templates=templates,
    )
    assert success is True

    identity = client.get_identity(uin)
    assert identity is not None
    assert identity["uin"] == uin
    assert identity["full_name"] == "Somchai Jaidee"
    assert identity["email"] == "somchai@dopa.gov.th"
    assert "face_embedding" not in identity
    assert "face_views" not in identity
    assert "<BIR" in identity["cbeff_xml"]

    raw = mock_client.get(f"/idrepository/v1/identity/uin/{uin}")
    assert raw.status_code == 200
    raw_identity = raw.json()["response"]["identity"]
    assert "faceEmbedding" not in raw_identity
    assert "faceViews" not in raw_identity

    stored_templates = client.get_face_templates(uin)
    by_sector = {item["sector"]: item["embedding"] for item in stored_templates}
    assert by_sector["front"] == [0.13] * 128
    assert set(by_sector) == {"far-left", "left", "front", "right", "far-right"}

    template_res = mock_client.get(f"/ida/v1/face-template/uin/{uin}")
    assert template_res.status_code == 200
    assert set(template_res.json()) == {"templates"}

    identities = client.list_identities(limit=10)
    assert any(i["uin"] == uin for i in identities)

    missing = mock_client.get("/ida/v1/face-template/uin/0000-not-enrolled")
    assert missing.status_code == 404


def test_identity_post_does_not_persist_client_vectors():
    uin = "5566-7788-9900"
    face_image = "data:image/jpeg;base64," + base64.b64encode(b"direct-face").decode("utf-8")
    res = mock_client.post(
        "/idrepository/v1/identity/",
        json={
            "id": "mosip.id.create",
            "version": "v1",
            "request": {
                "status": "ACTIVATED",
                "identity": {
                    "UIN": uin,
                    "fullName": [{"language": "eng", "value": "Direct Citizen"}],
                    "email": "direct@citizen.asia",
                    "faceImage": face_image,
                    "faceEmbedding": [0.5] * 128,
                    "faceViews": [{"sector": "front", "embedding": [0.5] * 128}],
                },
                "templates": [{"sector": "front", "embedding": [0.25] * 128}],
            },
        },
    )
    assert res.status_code == 200

    identity = mock_client.get(f"/idrepository/v1/identity/uin/{uin}")
    body = identity.json()["response"]["identity"]
    assert "faceEmbedding" not in body
    assert "faceViews" not in body
    assert body["faceImage"] == face_image

    templates = mock_client.get(f"/ida/v1/face-template/uin/{uin}")
    assert templates.status_code == 200
    assert templates.json()["templates"] == [{"sector": "front", "embedding": [0.25] * 128}]

    bare = mock_client.post(
        "/idrepository/v1/identity/",
        json={
            "request": {
                "identity": {
                    "UIN": "5566-7788-9901",
                    "fullName": "No Templates",
                    "email": "none@citizen.asia",
                    "faceImage": face_image,
                }
            }
        },
    )
    assert bare.status_code == 200
    assert mock_client.get("/ida/v1/face-template/uin/5566-7788-9901").status_code == 404
