# 📘 User Manual & Hands-On Guide: Citizen Registration Gateway (`register-id`)

> **Part of the MOSIP Asia Digital Public Infrastructure (DPI) Suite**  
> **Target Audience:** Internal Engineering Team, Solution Architects & Evaluators  
> **Status:** Verified Working (POC Tier)

---

## 📌 1. Overview & What This POC Proves

The **Citizen Registration Gateway (`register-id`)** demonstrates modern, sovereign **zero-hardware citizen onboarding** for Digital Public Infrastructure (DPI). Traditionally, national identity enrollment required heavy desktop registration clients (`regclient`), proprietary optical fingerprint/iris scanners, and multi-hour asynchronous batch ingestion pipelines (`regproc`).

This proof-of-concept proves that a citizen can be securely proofed and registered from **any modern web browser**:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        REGISTER-ID: ZERO-HARDWARE ONBOARDING LOOP                      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  [ CITIZEN BROWSER ]                                                                   │
│  • WebRTC Camera Feed or High-Res Photo Upload                                         │
│  • Client-Side AI (@vladmandic/face-api): SSD MobileNet V1 + 68 Facial Landmarks       │
│  • Real-Time Presentation Attack Detection: Eye Aspect Ratio (EAR) Blink Dynamics     │
│                                │                                                       │
│                                ▼ HTTPS / JSON                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ register-id APPLICATION GATEWAY (FastAPI / Django Core)                          │  │
│  │ • Normalizes Face Image & Extracts 128-D Biometric Descriptor                    │  │
│  │ • Serializes ISO/IEC 19794-5 (FAC\0) Record inside ISO 19785-3 CBEFF XML         │  │
│  └───────┬──────────────────────────────────────────────────────────┬───────────────┘  │
│          │                                                          │                  │
│          ▼ POST /idrepository/v1/identity                           ▼ Admin REST API   │
│  ┌──────────────────────────────┐                         ┌─────────────────────────┐  │
│  │ MOSIP IDRepo Service         │                         │ Keycloak 24 IAM Server  │  │
│  │ (mock.idrepo / Official API) │                         │ (mosip realm)           │  │
│  │ • Allocates Sovereign UIN    │                         │ • Provisions Citizen    │  │
│  │ • Persists Demographics      │                         │ • Sets uin Attribute    │  │
│  │ • Stores CBEFF Biometrics    │                         │ • Grants Bio Claim      │  │
│  └──────────────┬───────────────┘                         └────────────┬────────────┘  │
│                 │                                                      │               │
│                 ▼                                                      ▼               │
│  ┌──────────────────────────────┐                         ┌─────────────────────────┐  │
│  │ PostgreSQL 15 Database       │                         │ eSignet OIDC / Wallet   │  │
│  │ Schema: mosip_idrepo         │                         │ (login.id.<domain>)     │  │
│  └──────────────────────────────┘                         └─────────────────────────┘  │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Key Technical Capabilities Demonstrated:
1. **Zero Proprietary Hardware:** Runs in standard HTML5/WebRTC browsers without dedicated USB fingerprint or iris devices.
2. **ISO/IEC 30107-3 Liveness (PAD):** Real-time Eye Aspect Ratio (EAR) micro-motion tracking prevents spoofing with static photos or printed paper.
3. **ISO 19794-5 & ISO 19785-3 CBEFF Serialization:** Packages biometrics in standard binary face records wrapped in XML containers with MOSIP Format Owner `257` and Format Type `8`.
4. **Decoupled IDRepo REST Interface:** The gateway never touches the SQL database directly; all identity operations strictly use the official MOSIP IDRepo REST contract (`/idrepository/v1/identity`).
5. **Keycloak eSignet IAM Sync:** Instantly provisions the citizen in the `mosip` realm so they can log in via eSignet on Resident and Health portals.
6. **1:1 Facial Verification:** Compares live probe embeddings against stored gallery records using Euclidean distance thresholding ($T < 0.50$).

---

## 💻 2. System Requirements & Prerequisites

* **Operating System:** macOS, Linux, or Windows (WSL2).
* **Docker & Docker Compose:** Docker Desktop or Docker Engine v24+.
* **Browser:** Chrome, Edge, Firefox, or Safari (with camera permissions granted for `http://localhost`).
* **Python (Optional for local CLI / hybrid mode):** Python 3.13 managed by [`uv`](https://github.com/astral-sh/uv).

---

## 🚀 3. Quickstart (Under 2 Minutes)

### Step 1: Clone and Configure
```bash
git clone https://github.com/mosip-asia/dpi-register-id.git
cd dpi-register-id

# Copy environment template
cp .env.example .env
```

### Step 2: Spin Up Full Docker Compose Stack
```bash
# Build local runner image and spin up complete stack
docker compose up -d --build
```

### Step 3: Verify Running Services
Run `docker compose ps` to ensure all 5 services are active:

| Service | Container Name | Host Port | Purpose |
|---|---|---|---|
| **Web Gateway** | `register-id-app` | `http://localhost:8000` | Citizen Registration UI & REST API |
| **MOSIP IDRepo** | `register-id-idrepo` | `http://localhost:8081` | MOSIP Identity Repository REST Interface |
| **Keycloak IAM** | `register-id-keycloak` | `http://localhost:8080` | MOSIP Realm & eSignet Identity Provider |
| **PostgreSQL** | `register-id-postgres` | `localhost:5432` | Master Database (`mosip_idrepo` schema) |
| **Redis** | `register-id-redis` | `localhost:6379` | Background task cache & Celery queue |

---

## 👤 4. Hands-On Walkthrough: Citizen Enrollment

### Step 4.1: Open the Gateway Portal
Open your browser to:
👉 **`http://localhost:8000`**

You will see the **Citizen Identity Enrollment** panel:

```
┌──────────────────────────────────────┬─────────────────────────────────────────┐
│              VIEWFINDER              │           CITIZEN ENROLLMENT            │
├──────────────────────────────────────┼─────────────────────────────────────────┤
│                                      │  Generated MOSIP UIN                    │
│   [ 📷 Live Camera Feed ]            │  [ 4368891129                         ] │
│                                      │                                         │
│   👁️ EAR: 0.31 | ✅ Live Motion OK   │  Full Legal Name                        │
│   [✓ Face Detected (ISO 19794-5)]    │  [ Somchai Jaidee                     ] │
│                                      │                                         │
│                                      │  Email Address                          │
│                                      │  [ somchai@dopa.gov.th                ] │
│                                      │                                         │
│                                      │  Keycloak Initial Password              │
│                                      │  [ ••••••••••••••                     ] │
│                                      │                                         │
│   [📷 Open Webcam] [📁 Upload]       │  [ ✨ Enroll Face into IDRepo         ] │
│   [⚡ Skip Blink]                     │                                         │
└──────────────────────────────────────┴─────────────────────────────────────────┘
```

### Step 4.2: Activate Camera & Observe Real-Time AI
1. Click **"📷 Open Webcam"** (allow camera permission in your browser).
   *(If you are running in a headless VM or don't have a webcam, click **"📁 Upload Photo"** and choose any clear selfie/portrait JPEG).*
2. Look at the camera.
3. Observe the client-side neural network (@vladmandic/face-api):
   - A bounding box locks onto your face in real time.
   - 68 facial landmarks trace your eyebrows, nose bridge, lips, and eye contours.
   - The top-right badge displays the live **Eye Aspect Ratio (EAR)**:
     $$\text{EAR} = \frac{\|p_2 - p_6\| + \|p_3 - p_5\|}{2 \|p_1 - p_4\|}$$
4. **Blink your eyes naturally:** Notice the badge instantly flash **"👁️ Blink Detected!"** and switch to **"✅ Live Motion OK"**.
5. **⚡ Skip Blink (Manual Test Override):** If your webcam has a low frame rate, heavy backlighting, or glasses that interfere with facial landmark EAR tracking, click **"⚡ Skip Blink"** to immediately satisfy the PAD challenge and unlock enrollment/verification.

### Step 4.3: Submit Enrollment
1. Notice the **Generated MOSIP UIN** is pre-allocated from the IDRepo service.
2. Enter a legal name (e.g. `Somchai Jaidee`) and email.
3. Click **"✨ Enroll Face into IDRepo"**.

### Step 4.4: Inspect What Happened
The browser outputs a success card:
* **UIN Registered:** `4368891129`
* **Backend Used:** `mosip-idrepo-rest` (routed via `POST http://idrepo:8080/idrepository/v1/identity/`)
* **ISO 19794-5 CBEFF Generated:** `true` (standard biometric envelope packaged)
* **Keycloak User Provisioned:** `true` (ready for eSignet OIDC login)

---

## 🛡️ 5. Hands-On Walkthrough: 1:1 Authentication & Spoof Detection

### Step 5.1: Positive Control (Legitimate Live Match)
1. At the top of the page, click the tab **"2. Live 1:1 Authentication & PAD"**.
2. From the dropdown **"Select Enrolled Citizen UIN"**, select the citizen you just enrolled (`Somchai Jaidee`).
3. Look at the webcam and blink naturally.
4. Click **"🛡️ Verify 1:1 Match & PAD"**.
5. **Expected Outcome: ✅ VERIFIED**
   - **Biometric Match:** `MATCHED` (Euclidean distance: `0.02` vs threshold `0.50`).
   - **ISO 30107-3 PAD:** `PASSED` (Confidence: `88.5%`).
   - **Verified Citizen JWT Session:** Issued and displayed.

### Step 5.2: Negative Control A (Presentation Attack / Photo Spoof)
1. Stay on the **"2. Live 1:1 Authentication & PAD"** tab.
2. Point your camera at a **static printed photo** or a **photo displayed on a smartphone screen**, OR hold your eyes wide open without blinking.
3. Click **"🛡️ Verify 1:1 Match & PAD"**.
4. **Expected Outcome: ❌ REJECTED (Spoof Detected)**
   - The system detects insufficient eye closure dynamics ($\Delta \text{EAR} < 0.04$ or $\text{EAR}_{\min} \ge 0.25$).
   - Returns: `Presentation Attack / Spoof Detected (Static photo or insufficient motion)`.
   - **Zero session tokens are issued.**

### Step 5.3: Negative Control B (Impostor Face)
1. Select Citizen A from the dropdown.
2. Have another colleague look into the camera (or hold up a photo of a different person).
3. Click **"🛡️ Verify 1:1 Match & PAD"**.
4. **Expected Outcome: ❌ REJECTED (Biometric Mismatch)**
   - Even if they blink (passing liveness), the facial embedding distance exceeds `0.50` (typically `0.75`–`0.95`).
   - Returns: `Biometric distance did not match enrolled template`.

---

## 🔍 6. Verification via CLI & Admin Consoles

You can verify all stored data using the built-in CLI commands or standard administrative consoles:

### 6.1 Check Backend Health
```bash
uv run register-id register_id check-backend
```
*Expected Output:*
```text
MOSIP IDRepo Endpoint: http://localhost:8081
MOSIP IDRepo Status:   UP (info: {'status': 'UP', 'service': 'mosip-id-repository', ...})
```

### 6.2 List Citizens via MOSIP IDRepo REST Interface
```bash
uv run register-id register_id list
```
*Expected Output:*
```text
          Enrolled Citizens via MOSIP IDRepo (http://localhost:8081)           
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ UIN           ┃ Full Name      ┃ Email               ┃ Enrolled At         ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ 4368891129    │ Somchai Jaidee │ somchai@dopa.gov.th │ 2026-11-11 07:36:02 │
└───────────────┴────────────────┴─────────────────────┴─────────────────────┘
```

### 6.3 Inspect Citizen CBEFF Biometrics
```bash
uv run register-id register_id show 4368891129
```
*Expected Output:*
```text
Citizen Details (4368891129)
  Full Name: Somchai Jaidee
  Email:     somchai@dopa.gov.th
  CBEFF XML: Present
```

### 6.4 Inspect Keycloak IAM Admin Console
1. Open **`http://localhost:8080`** in your browser.
2. Log in with:
   - **Username:** `admin`
   - **Password:** `admin`
3. In the top-left realm dropdown, select **`mosip`**.
4. In the left navigation, click **Users**.
5. Click on the citizen user (e.g., `4368891129` or `somchai@dopa.gov.th`).
6. Click the **Attributes** tab:
   - `uin`: `4368891129`
   - `individualBiometrics`: `VALID`

---

## 🧪 7. Automated Test Suite

Before making code changes, run the automated verification suite:

```bash
# Full verification: Data guard, pytest, and Django check
bash scripts/check.sh
```

All 22 unit and integration tests should pass:
```text
== data guard
check-data-guard: 99 files clean

== pytest
......................                                                   [100%]
22 passed in 20.39s

== django check
System check identified no issues (0 silenced).

✅ check: all checks passed!
```

---

## 🛠️ 8. Local Development & Hybrid Mode

If you are developing backend features and want hot-reloading without rebuilding Docker images:

```bash
# 1. Start datastores and mock IDRepo in Docker
docker compose up -d redis postgres keycloak idrepo

# 2. Run the Web Gateway locally on your host machine
uv run register-id web

# 3. (Optional) Run the Mock IDRepo service directly on host
uv run register-id mock idrepo serve --port 8081
```

---

## ❓ 9. Troubleshooting & FAQ

#### Q: The browser says "Webcam requires HTTPS or http://localhost"
Modern browsers enforce secure contexts for `navigator.mediaDevices.getUserMedia`. Ensure you access the application strictly via **`http://localhost:8000`** (or `http://127.0.0.1:8000`), not via an IP address.

#### Q: How do I test on a machine without a webcam?
Click the **"📁 Upload Photo"** button underneath the viewfinder. Any front-facing JPEG photo will be processed by `@vladmandic/face-api` to extract the 68 landmarks and 128-D descriptor.

#### Q: How do I wipe all test data and start fresh?
```bash
docker compose down -v
docker compose up -d
```
This removes the `postgres_data` volume and re-runs [`db/init-idrepo.sql`](../db/init-idrepo.sql) automatically on the next boot.

#### Q: How do we point `register-id` to an existing MOSIP Kubernetes cluster?
In `.env`, simply change:
```ini
MOSIP_IDREPO_BASE_URL="http://idrepo.mosip-core.svc.cluster.local:8080"
KEYCLOAK_URL="http://keycloak.keycloak.svc.cluster.local:8080/auth"
```
The application code does not change because it speaks standard MOSIP IDRepo REST contracts.
