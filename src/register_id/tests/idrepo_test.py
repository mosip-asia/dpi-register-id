import json
import logging
from pathlib import Path

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
    # Unreachable base URL so enroll lands in the in-process mock this file reads.
    client = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)

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
    assert client.last_backend == "inprocess-idrepo"

    identity = client.get_identity(uin, include_biometrics=True)
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
    assert "faceImage" not in raw_identity
    assert "faceEmbedding" not in raw_identity
    assert "faceViews" not in raw_identity
    assert raw.json()["response"]["documents"] == []

    explicit = mock_client.get(
        f"/idrepository/v1/identity/uin/{uin}",
        params={"includeBiometrics": "true"},
    )
    assert explicit.json()["response"]["identity"]["faceImage"] == "data:image/jpeg;base64,bW9jay1mYWNl"
    assert explicit.json()["response"]["documents"]

    withheld = mock_client.get(f"/ida/v1/face-template/uin/{uin}")
    assert withheld.status_code == 200
    assert withheld.json()["templates"] == []

    template_res = mock_client.get(
        f"/ida/v1/face-template/uin/{uin}",
        params={"includeBiometrics": "true"},
    )
    assert template_res.status_code == 200
    assert set(template_res.json()) == {"templates"}

    stored_templates = client.get_face_templates(uin)
    by_sector = {item["sector"]: item["embedding"] for item in stored_templates}
    assert by_sector["front"] == [0.13] * 128
    assert set(by_sector) == {"far-left", "left", "front", "right", "far-right"}

    # Same-second inserts share CURRENT_TIMESTAMP. A short page can omit the
    # row just written when the suite enrolls more than `limit` identities.
    identities = client.list_identities(limit=200)
    assert any(i["uin"] == uin for i in identities)

    missing = mock_client.get("/ida/v1/face-template/uin/0000-not-enrolled")
    assert missing.status_code == 404


def test_add_identity_fails_without_inprocess_fallback_when_remote_is_down():
    uin = "9000000502"
    client = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=False)
    saved = client.add_identity(
        uin=uin,
        full_name="No Fallback",
        email="nofallback@example.com",
        face_image="data:image/jpeg;base64,bW9jay1mYWNl",
    )
    assert saved is False
    assert client.last_backend is None
    assert client.last_status == 503
    assert client.last_error
    assert "127.0.0.1:9" in client.last_error
    missing = mock_client.get(f"/idrepository/v1/identity/uin/{uin}")
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
    assert "faceImage" not in body
    assert "faceEmbedding" not in body
    assert "faceViews" not in body
    assert identity.json()["response"]["documents"] == []

    explicit = mock_client.get(
        f"/idrepository/v1/identity/uin/{uin}",
        params={"includeBiometrics": "true"},
    )
    explicit_body = explicit.json()["response"]["identity"]
    assert "faceEmbedding" not in explicit_body
    assert "faceViews" not in explicit_body
    assert explicit_body["faceImage"] == face_image

    withheld = mock_client.get(f"/ida/v1/face-template/uin/{uin}")
    assert withheld.status_code == 200
    assert withheld.json()["templates"] == []

    templates = mock_client.get(
        f"/ida/v1/face-template/uin/{uin}",
        params={"includeBiometrics": "true"},
    )
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
    assert mock_client.get(
        "/ida/v1/face-template/uin/5566-7788-9901",
        params={"includeBiometrics": "true"},
    ).status_code == 404


def test_posted_identity_fields_round_trip():
    required = json.loads(
        (Path(__file__).parent / "fixtures" / "identity-required.json").read_text(encoding="utf-8")
    )
    client = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    uin = client.generate_uin()
    face = "data:image/jpeg;base64,bW9jay1mYWNl"
    cbeff_xml = build_cbeff_xml(uin=uin, jpeg_bytes=b"kit-face")
    assert client.add_identity(
        uin=uin,
        full_name="Ada Lovelace",
        date_of_birth="1990-12-10",
        gender="Female",
        email="ada@example.com",
        phone="0812345678",
        address_line1="1 Register Road",
        address_line2="Floor 2",
        address_line3="Room 3",
        region="Bangkok",
        province="Bangkok",
        city="Pathum Wan",
        zone="1",
        postal_code="10330",
        reference_identity_number="REF-1",
        face_image=face,
        cbeff_xml=cbeff_xml,
        templates=[{"sector": "front", "embedding": [0.2, 0.3]}],
    ) is True

    plain = mock_client.get(f"/idrepository/v1/identity/uin/{uin}")
    assert plain.status_code == 200
    body = plain.json()["response"]["identity"]
    names = set(required)
    assert [key for key in body if key in names] == required
    assert body["IDSchemaVersion"] == 1.1
    assert body["dateOfBirth"] == "1990/12/10"
    assert body["gender"] == [{"language": "eng", "value": "Female"}]
    assert body["phone"] == "0812345678"
    assert body["addressLine1"] == [{"language": "eng", "value": "1 Register Road"}]
    assert body["addressLine2"] == [{"language": "eng", "value": "Floor 2"}]
    assert body["postalCode"] == "10330"
    assert body["referenceIdentityNumber"] == "REF-1"
    assert "faceImage" not in body
    assert plain.json()["response"]["documents"] == []

    explicit = mock_client.get(
        f"/idrepository/v1/identity/uin/{uin}",
        params={"includeBiometrics": "true"},
    )
    explicit_body = explicit.json()["response"]
    assert explicit_body["identity"]["faceImage"] == face
    assert explicit_body["identity"]["dateOfBirth"] == "1990/12/10"
    assert "<BIR" in base64.urlsafe_b64decode(
        explicit_body["documents"][0]["value"] + "=" * (-len(explicit_body["documents"][0]["value"]) % 4)
    ).decode()
    templates = mock_client.get(
        f"/ida/v1/face-template/uin/{uin}",
        params={"includeBiometrics": "true"},
    )
    assert templates.status_code == 200
    assert templates.json()["templates"][0]["sector"] == "front"

    assert client.update_demographics(uin, "Ada Byron", "ada.byron@example.com") is True
    corrected = mock_client.get(f"/idrepository/v1/identity/uin/{uin}").json()["response"]["identity"]
    assert corrected["fullName"] == [{"language": "eng", "value": "Ada Byron"}]
    assert corrected["email"] == "ada.byron@example.com"
    assert corrected["gender"] == body["gender"]
    assert corrected["dateOfBirth"] == "1990/12/10"
    assert corrected["phone"] == "0812345678"
    assert corrected["addressLine1"] == body["addressLine1"]
    assert "faceImage" not in corrected


class _EnrollResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = body if isinstance(body, str) else str(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


def _enroll_against(monkeypatch, response):
    client = IDRepoClient(base_url="http://idrepo.test", enable_inprocess_fallback=False)

    def _post(*_args, **_kwargs):
        return response

    monkeypatch.setattr("register_id.idrepo_client.requests.post", _post)
    saved = client.add_identity(
        uin="9000000503",
        full_name="Leak Check",
        email="leak@example.com",
        face_image="data:image/jpeg;base64,bW9jay1mYWNl",
    )
    return client, saved


def test_remote_enroll_success_is_labeled_mosip_idrepo_rest(monkeypatch):
    response = _EnrollResponse(200, {"response": {"uin": "9000000503"}})
    client, saved = _enroll_against(monkeypatch, response)
    assert saved is True
    assert client.last_backend == "mosip-idrepo-rest"


def test_enroll_failure_log_keeps_status_and_code_only(monkeypatch, caplog):
    leaked = "data:image/jpeg;base64,LEAKED-FACE-BYTES"
    response = _EnrollResponse(
        400,
        {
            "errors": [{
                "errorCode": "IDR-IDC-007",
                "message": f"rejected faceImage {leaked}",
            }],
            "request": {"faceImage": leaked},
        },
    )
    with caplog.at_level(logging.WARNING, logger="register_id.idrepo_client"):
        client, saved = _enroll_against(monkeypatch, response)

    assert saved is False
    assert client.last_error == "MOSIP IDRepo returned HTTP 400: IDR-IDC-007"
    assert leaked not in (client.last_error or "")
    assert leaked not in caplog.text
    assert "IDR-IDC-007" in caplog.text


def test_enroll_failure_log_drops_non_json_body(monkeypatch, caplog):
    leaked = "<BIR>SECRET-FACE-CBEFF"
    response = _EnrollResponse(502, f"upstream echoed {leaked}")
    with caplog.at_level(logging.WARNING, logger="register_id.idrepo_client"):
        client, saved = _enroll_against(monkeypatch, response)

    assert saved is False
    assert client.last_error == "MOSIP IDRepo returned HTTP 502"
    assert leaked not in (client.last_error or "")
    assert leaked not in caplog.text


def test_remote_read_sends_keycloak_cookie(monkeypatch):
    secret = "idrepo-secret-do-not-log"
    monkeypatch.setenv("KEYCLOAK_INTERNAL_URL", "http://keycloak.test/auth")
    monkeypatch.setenv("KEYCLOAK_REALM", "mosip")
    monkeypatch.setenv("IDREPO_CLIENT_ID", "idrepo-client")
    monkeypatch.setenv("IDREPO_CLIENT_SECRET", secret)
    seen: dict[str, str] = {}
    posts: list[str] = []
    clock = {"now": 1_000.0}
    monkeypatch.setattr("register_id.idrepo_client.time.monotonic", lambda: clock["now"])

    class Response:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    def post(url, data=None, timeout=None, **kwargs):
        assert "json" not in kwargs
        assert url == "http://keycloak.test/auth/realms/mosip/protocol/openid-connect/token"
        assert data == {
            "grant_type": "client_credentials",
            "client_id": "idrepo-client",
            "client_secret": secret,
        }
        posts.append(url)
        return Response({"access_token": "tok-1", "expires_in": 90})

    def get(url, params=None, headers=None, timeout=None):
        seen["cookie"] = headers["Cookie"]
        seen["url"] = url
        return Response({"response": {"identity": {"UIN": "1234567890", "fullName": "Ada"}}})

    monkeypatch.setattr("register_id.idrepo_client.requests.post", post)
    monkeypatch.setattr("register_id.idrepo_client.requests.get", get)
    client = IDRepoClient(base_url="http://idrepo.test", enable_inprocess_fallback=False)
    record = client.get_identity("1234567890")
    assert record is not None
    assert record["uin"] == "1234567890"
    assert seen["cookie"] == "Authorization=tok-1"
    assert secret not in seen["cookie"]

    clock["now"] = 1_059.0
    client.get_identity("1234567890")
    assert len(posts) == 1

    clock["now"] = 1_060.0
    client.get_identity("1234567890")
    assert len(posts) == 2


def test_generate_uin_without_fallback_does_not_invent_a_uin(monkeypatch):
    monkeypatch.delenv("IDREPO_CLIENT_ID", raising=False)
    monkeypatch.delenv("IDREPO_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("KEYCLOAK_INTERNAL_URL", raising=False)
    monkeypatch.delenv("MOSIP_IDGENERATOR_BASE_URL", raising=False)
    called = []

    def down(*args, **kwargs):
        called.append(args[0] if args else kwargs.get("url"))
        raise RuntimeError("idgenerator down")

    monkeypatch.setattr("register_id.idrepo_client.requests.get", down)
    client = IDRepoClient(base_url="http://idrepo.test", enable_inprocess_fallback=False)
    assert client.generate_uin() == ""
    assert client.last_status == 503
    assert client.last_error == "No IDRepo token: IDREPO_CLIENT_ID / IDREPO_CLIENT_SECRET is not set"
    assert called == []


def test_generate_uin_without_fallback_calls_kernel_not_idrepo(monkeypatch):
    monkeypatch.delenv("MOSIP_IDGENERATOR_BASE_URL", raising=False)
    monkeypatch.setenv("KEYCLOAK_INTERNAL_URL", "http://keycloak.test/auth")
    monkeypatch.setenv("KEYCLOAK_REALM", "mosip")
    monkeypatch.setenv("IDREPO_CLIENT_ID", "idrepo-client")
    monkeypatch.setenv("IDREPO_CLIENT_SECRET", "idrepo-secret-do-not-log")
    seen: dict[str, str] = {}

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def post(url, data=None, timeout=None):
        assert data["grant_type"] == "client_credentials"
        return Response(200, {"access_token": "tok-1", "expires_in": 300})

    def get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["cookie"] = (headers or {}).get("Cookie", "")
        return Response(200, {"response": {}})

    monkeypatch.setattr("register_id.idrepo_client.requests.post", post)
    monkeypatch.setattr("register_id.idrepo_client.requests.get", get)
    client = IDRepoClient(base_url="http://idrepo.test", enable_inprocess_fallback=False)
    assert client.generate_uin() == ""
    assert client.last_status == 503
    assert client.last_error == "MOSIP idgenerator did not return a UIN"
    assert seen["url"] == "http://idgenerator.kernel/v1/idgenerator/uin"
    assert seen["cookie"] == "Authorization=tok-1"
    assert "idrepo.test" not in seen["url"]


def test_get_identity_uses_the_mosip_idvid_path():
    """MOSIP IDRepo 1.2 serves reads at /idvid/{id}; /uin/{uin} exists only in the mock."""
    client = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    uin = client.generate_uin()
    assert client.add_identity(uin=uin, full_name="Idvid Reader", email="idvid@example.org",
                               face_image="data:image/jpeg;base64,bW9jay1mYWNl")

    demo = mock_client.get(f"/idrepository/v1/identity/idvid/{uin}", params={"type": "demo", "idType": "UIN"})
    assert demo.status_code == 200
    assert "faceImage" not in demo.json()["response"]["identity"]

    full = mock_client.get(f"/idrepository/v1/identity/idvid/{uin}", params={"type": "all"})
    assert full.json()["response"]["identity"]["faceImage"] == "data:image/jpeg;base64,bW9jay1mYWNl"

    assert client.get_identity(uin)["full_name"] == "Idvid Reader"


def test_get_identity_treats_a_mosip_error_envelope_as_not_found(monkeypatch):
    """The real IDRepo answers HTTP 200 with an errors list for an unknown UIN."""

    class _Reply:
        status_code = 200

        @staticmethod
        def json():
            return {"response": None, "errors": [{"errorCode": "IDR-IDC-007", "message": "No Record(s) found"}]}

    client = IDRepoClient(base_url="http://idrepo.example", enable_inprocess_fallback=False)
    seen = {}

    def fake_send(method, url, **kwargs):
        seen["url"] = url
        seen["params"] = kwargs.get("params")
        return _Reply()

    monkeypatch.setattr(client, "_send", fake_send)
    assert client.get_identity("2459857015") is None
    assert seen["url"] == "http://idrepo.example/idrepository/v1/identity/idvid/2459857015"
    assert seen["params"] == {"type": "demo", "idType": "UIN"}


def test_mock_generator_uins_pass_mosip_uin_rules():
    """A real MOSIP ID Repository rejects UINs that break the kernel UIN validator (IDR-IDC-002)."""
    from mock.idrepo.uin import checksum_digit, is_valid_uin

    assert is_valid_uin("2459857015")
    assert is_valid_uin("3623052180")
    assert not is_valid_uin("5219473140")  # wrong checksum
    assert not is_valid_uin("1459857015")  # starts with 1
    assert not is_valid_uin("2345678901")  # ascending run
    body = "245985701"
    assert checksum_digit(body) == "5"
    for _ in range(50):
        uin = mock_client.get("/v1/idgenerator/uin").json()["response"]["uin"]
        assert is_valid_uin(uin), uin


def test_face_templates_fall_back_to_the_cbeff_when_idrepo_has_no_template_endpoint(monkeypatch):
    """Real MOSIP IDRepo answers 404 for /ida/v1/face-template; verify then reads the CBEFF document."""
    from register_id.cbeff import build_cbeff_xml

    cbeff = build_cbeff_xml(uin="2459857015", jpeg_bytes=b"jpeg", descriptors=[[0.3] * 128])

    class _NotFound:
        status_code = 404

    client = IDRepoClient(base_url="http://idrepo.example", enable_inprocess_fallback=False)
    monkeypatch.setattr(client, "_send", lambda method, url, **kwargs: _NotFound())
    monkeypatch.setattr(client, "get_identity", lambda uin, include_biometrics=False: {"cbeff_xml": cbeff})

    rows = client.get_face_templates("2459857015")
    assert rows == [{"sector": "front", "engine": "face-api-128", "embedding": [0.3] * 128}]


def test_create_adds_the_individual_biometrics_reference_when_a_cbeff_is_sent(monkeypatch):
    """MOSIP rejects a document whose category is not also an identity key."""
    sent = {}

    class _Ok:
        status_code = 200

        @staticmethod
        def json():
            return {"response": {"status": "ACTIVATED"}, "errors": None}

    def fake_send(method, url, **kwargs):
        sent["body"] = kwargs.get("json_body")
        return _Ok()

    client = IDRepoClient(base_url="http://idrepo.example", enable_inprocess_fallback=False)
    monkeypatch.setattr(client, "_send", fake_send)
    assert client.add_identity(uin="2459857015", full_name="With Face", email="f@example.org",
                               cbeff_xml="<BIR/>", status="biometric")
    identity = sent["body"]["request"]["identity"]
    assert identity["individualBiometrics"]["format"] == "cbeff"
    assert sent["body"]["request"]["documents"][0]["category"] == "individualBiometrics"


def test_create_retry_that_finds_this_enrolment_already_saved_counts_as_saved(monkeypatch):
    """Slow first save + client timeout + retry => IDR-IDC-012. Same UIN and name means it was saved."""

    class _Exists:
        status_code = 200

        @staticmethod
        def json():
            return {"response": None, "errors": [{"errorCode": "IDR-IDC-012", "message": "Record already exists in DB"}]}

    client = IDRepoClient(base_url="http://idrepo.example", enable_inprocess_fallback=False)
    monkeypatch.setattr(client, "_send", lambda method, url, **kwargs: _Exists())

    monkeypatch.setattr(client, "get_identity", lambda uin, include_biometrics=False: {"full_name": "Aye Chan Myint"})
    assert client.add_identity(uin="2459857015", full_name="Aye Chan Myint", email="a@example.org") is True
    assert client.last_backend == "mosip-idrepo-rest"

    # A different person under that UIN is a real conflict.
    monkeypatch.setattr(client, "get_identity", lambda uin, include_biometrics=False: {"full_name": "Someone Else"})
    assert client.add_identity(uin="2459857015", full_name="Aye Chan Myint", email="a@example.org") is False
