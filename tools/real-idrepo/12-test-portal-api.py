"""Step 12: the portal's own API calls, end to end, against whatever IDRepo register-id is pointed at.

enroll ticket -> face challenge (enroll) -> POST /api/enroll with 3 face descriptors + head-turn yaws
-> face challenge (check) -> POST /api/authenticate with a probe close to the enrolled face.

Descriptors are synthetic (not a real face): 128 numbers, the 3 enrol frames slightly different, the probe
close to them. This tests the register-id <-> IDRepo path, not the face model.
Usage: uv run python 12-test-portal-api.py   (app at http://localhost:8000)
"""

import random
import sys
import time

import requests

APP = "http://localhost:8000"
JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/yQALCAABAAEBAREA/8wABgAQEAX/2gAIAQEAAD8A0s8g/9k="

rng = random.Random(7)
base = [rng.uniform(-0.2, 0.2) for _ in range(128)]


def near(vec, spread):
    return [round(v + rng.uniform(-spread, spread), 6) for v in vec]


def post(path, body=None, headers=None):
    r = requests.post(f"{APP}{path}", json=body, headers=headers or {}, timeout=60)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:300]}
    return r.status_code, data


tag = rng.randint(1000, 9999)
ticket = post("/api/enroll/ticket")[1]["ticket"]
challenge = post("/api/face/challenge", {"purpose": "enroll"})[1]["challengeId"]
status, enrolled = post("/api/enroll", {
    "fullName": f"Portal Test {tag}", "email": f"portal.test{tag}@example.org",
    "gender": "Female", "dateOfBirth": "1994-04-04", "phone": "9876543210",
    "addressLine1": "Line 1", "addressLine2": "Line 2", "addressLine3": "Line 3",
    "region": "Region", "province": "Province", "city": "City", "zone": "Zone", "postalCode": "10200",
    "referenceIdentityNumber": f"{rng.randint(10**9, 10**10 - 1)}",
    "faceImage": JPEG,
    "faceDescriptors": [near(base, 0.01) for _ in range(3)],
    "liveness": {"challengeId": challenge, "engine": "face-api-128", "blinkCount": 0,
                 "sweepYaws": [-0.5, -0.25, 0.0, 0.25, 0.5]},
    "consent": {"accepted": True, "purpose": "Create a citizen ID and store the face image for this registration",
                "acceptedAt": time.time(), "language": "eng"},
}, {"x-enroll-ticket": ticket})
print("ENROLL:", status, enrolled.get("status") or enrolled.get("detail"),
      "| uin:", enrolled.get("uin"), "| backend:", enrolled.get("backend"),
      "| record:", enrolled.get("recordStatus"), "| cbeff:", enrolled.get("cbeffGenerated"))
if status != 200:
    sys.exit(1)

uin = enrolled["uin"]
challenge = post("/api/face/challenge", {"purpose": "check"})[1]["challengeId"]
status, verdict = post("/api/authenticate", {
    "uin": uin, "probeDescriptor": near(base, 0.01),
    "liveness": {"challengeId": challenge, "engine": "face-api-128", "blinkCount": 0,
                 "sweepYaws": [-0.5, -0.25, 0.0, 0.25, 0.5]},
})
print("VERIFY:", status, verdict.get("status") or verdict.get("detail"), "| match:", verdict.get("isFaceMatch"),
      "| distance:", verdict.get("euclideanDistance"), "|", (verdict.get("message") or "")[:160])

# A different face (far from the enrolled vectors) must not match.
other = [rng.uniform(-0.2, 0.2) for _ in range(128)]
challenge = post("/api/face/challenge", {"purpose": "check"})[1]["challengeId"]
status, verdict = post("/api/authenticate", {
    "uin": uin, "probeDescriptor": other,
    "liveness": {"challengeId": challenge, "engine": "face-api-128", "blinkCount": 0,
                 "sweepYaws": [-0.5, -0.25, 0.0, 0.25, 0.5]},
})
print("OTHER FACE:", status, verdict.get("status") or verdict.get("detail"), "| match:", verdict.get("isFaceMatch"),
      "| distance:", verdict.get("euclideanDistance"))
