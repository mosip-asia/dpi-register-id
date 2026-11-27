# Running the real MOSIP ID Repository next to register-id

A step-by-step manual. Last update 27 Nov 2026, on the ASUS Vivobook (16 GB RAM, Docker gets ~7.6 GB).

**Result:** register-id's own client code **saves an identity in the real MOSIP ID Repository and reads it back.**

---

## 1. What Phi Jo asked for

From the call (27 Nov):

1. **Replace our mock IDRepo with the real MOSIP ID Repository**, the one at
   <https://github.com/mosip/id-repository>. "This is the one we mocked up. Use it as a reference."
2. **Do not run the full MOSIP.** Only the ID Repository, because it has the face biometric API.
3. **Find out what else it needs**: which other MOSIP services, and which **environment variables / settings**,
   "so that when we integrate with Mehul, we know what we need".
4. It "might need the biometric SDK". Check that. → **Yes, it cannot start without one.**
5. Run in **Docker with a memory limit**, watch RAM.
6. **Keep the mock** and switch back to it after integration.

Context: **Mehul** (Sandbox Kit team) runs the real MOSIP environment, wrote the A1–D1 review, and will test
register-id with us on **Tue/Wed**.

**Answer in one line:** the ID Repository alone is not enough. To **save** one identity it needs, besides itself:
a BioSDK, its databases, Keycloak, **masterdata** (for the identity schema) and **keymanager** (for encryption).
Full list: `FINDINGS.md`.

---

## 2. How the GitHub repo link relates to what we run

`github.com/mosip/id-repository` is the **source code**. We do not build it; MOSIP publishes everything:

| From MOSIP | Used for |
|---|---|
| Image `mosipid/id-repository-identity-service:1.2.0.1` (built from that repo) | The real ID Repository |
| `db_scripts/mosip_idrepo`, `mosip_idmap` in that repo | Its databases |
| `github.com/mosip/mosip-config` tag `v1.2.0.1` | Settings + files it downloads at startup |
| Maven Central `io.mosip.*` 1.2.0.1 jars | Jars the images normally fetch from MOSIP's private "artifactory" |
| Image `mosipid/biosdk-server` + Maven `mock-sdk` | Biometric SDK (open-source mock) |
| Image `mosipid/kernel-masterdata-service` + `admin-services` DB scripts + `mosip-data` identity schema | Identity schema |
| Image `mosipid/kernel-keymanager-service` + `keymanager` DB scripts | Encryption keys |

Everything is version **1.2.0.1** so the parts match.

---

## 3. Before you start

| Need | Check |
|---|---|
| register-id running in Docker (app, Postgres, Redis, Keycloak) | `docker ps` shows `register-id-*` |
| Keycloak realm `mosip` with client `register-id-idrepo` (roles `ID_REPOSITORY`, `REGISTRATION_PROCESSOR`) | already set up locally |
| **Git Bash** (scripts are bash) | open "Git Bash" |
| `uv` (for the 2 Python steps) | `uv --version` |
| ~3.5 GB free Docker memory, ~4 GB disk on D: | `docker stats --no-stream` |

Close heavy apps (Chrome tabs) first. Everything lives in `tools/real-idrepo/` of the register-id repo.
Secrets (`idrepo.env`, `keystore/`, `objectstore-s3.json`) and downloads (jars, MOSIP config, DB scripts) are
created there by the scripts and kept out of git by `tools/real-idrepo/.gitignore`. Never commit them.

---

## 4. Files

| File | Step | What it does |
|---|---|---|
| `01-download.sh` | 1 | 4 images, 4 jars, config, startup files, DB scripts, schema seed |
| `02-make-secrets.sh` | 2 | `idrepo.env` with random local secrets |
| `03-identity-schema.py` | 3 | SQL for MOSIP's identity schema (version + required list matching register-id / the Kit) |
| `04-setup-db.sh` | 4 | Databases `mosip_idrepo`, `mosip_idmap`, `mosip_master`, `mosip_keymgr`; salts; key policies; schema |
| `05-run-config-files.sh` | 5 | Small web server for the files services download at startup |
| `06-keycloak-clients.py` | 6 | Audience on register-id's client; creates IDRepo's own client `mosip-idrepo-client` |
| `07-run-biosdk.sh` | 7 | BioSDK server with the mock SDK (1 GB limit) |
| `08-run-kernel.sh` | 8 | Masterdata or keymanager (1.5 GB limit each) |
| `09-generate-keys.sh` (+ `.py`) | 9 | Keymanager master keys ROOT, KERNEL, ID_REPO |
| `10-run-idrepo.sh` | 10 | The real ID Repository (2 GB limit) |
| `11-test-create.sh` | 11 | Health, create one identity, read it back |
| `mosip_uin.py` | – | Makes UINs that pass MOSIP's UIN rules (used by step 11) |
| `why.sh` | any | Root cause of a failed start: `bash why.sh <container>` |
| `config/local.properties` | – | Local settings for all services (passed as `-D`) |
| `config/local-kernel.properties`, `config/local-keymanager.properties` | – | Extra settings for masterdata / keymanager |
| `idrepo.env` | – | Local secrets. **Do not commit or share.** |
| `FINDINGS.md` | – | Dependencies, settings, bugs found |

---

## 5. Step by step

Open **Git Bash**:

```bash
cd tools/real-idrepo
```

**From PowerShell instead:** typing `bash` there starts **WSL** (`C:\WINDOWS\system32\bash.exe`), which cannot see
`/d/...` paths ("No such file or directory"). Call Git Bash explicitly:

```powershell
& "C:\Program Files\Git\bin\bash.exe" tools/real-idrepo/13-which-idrepo.sh
```

The two Python steps run from the register-id folder (they read register-id's `.env` and fixtures):

```bash
R=$(git rev-parse --show-toplevel)  # the register-id folder
```

### Step 1 – Download (≈ 15 min, ≈ 3 GB)

```bash
bash 01-download.sh
```

Check: `ls jars` → 3 jars; `ls db_scripts` → `mosip_idmap mosip_idrepo mosip_keymgr mosip_master`; `ls seed` → `identity_schema.xlsx`.

### Step 2 – Local secrets

```bash
bash 02-make-secrets.sh
```

### Step 3 – Identity schema SQL

```bash
(cd $R && uv run --with openpyxl python tools/real-idrepo/03-identity-schema.py)
```

Expect: `id_version = 1.1 (register-id SCHEMA_VERSION; MOSIP seed has 0.1)` and the 16-field required list.
Why: IDRepo asks masterdata for the schema whose version **equals** the `IDSchemaVersion` register-id sends.

### Step 4 – Databases (≈ 2 min)

```bash
bash 04-setup-db.sh
```

Expect: 4 databases created, `1000 rows` four times, `rows: 1` for the schema. Re-running skips existing databases.

### Step 5 – File server

```bash
bash 05-run-config-files.sh
```

(Docker may show it as `unhealthy`; that is only the image's own health check and can be ignored.)

### Step 6 – Keycloak clients

```bash
(cd $R && uv run python tools/real-idrepo/06-keycloak-clients.py .env tools/real-idrepo/idrepo.env)
```

Expect: `register-id-idrepo token aud=register-id-idrepo …` and `mosip-idrepo-client token aud=['mosip-idrepo-client', …] roles=[… ID_REPOSITORY …]`.

### Step 7 – BioSDK

```bash
bash 07-run-biosdk.sh
```

After ~40 s: `docker logs biosdk-service 2>&1 | grep "Started SdkApplication"`.

### Step 8 – Masterdata and keymanager (≈ 1.5 min each)

```bash
bash 08-run-kernel.sh masterdata
bash 08-run-kernel.sh keymanager
```

Wait until both show `Started …` (`bash why.sh masterdata`, `bash why.sh keymanager`).

### Step 9 – Master keys

```bash
bash 09-generate-keys.sh
```

Expect: `ROOT: key ready`, `KERNEL: key ready`, `ID_REPO: key ready`; file `keystore/keystore.p12` appears.

### Step 10 – The real ID Repository (≈ 2 min)

```bash
bash 10-run-idrepo.sh
```

Wait until `docker logs idrepo-real 2>&1 | grep '"message":"Started'` shows `Started IdRepoBootApplication`.

### Step 11 – Test

```bash
bash 11-test-create.sh
```

Expected:

```
== Health
200 {"status":"UP", … "db":{"status":"UP" …
== Create one identity with register-id's IDRepoClient, then read it back
uin: 3623052180
saved: True | backend: mosip-idrepo-rest | error: None
read back: found | name: Real Repo Test
```

To see the stored (encrypted) row:

```bash
MSYS_NO_PATHCONV=1 docker exec register-id-postgres psql -U postgres -d mosip_idrepo -c "select reg_id, status_code, cr_dtimes from idrepo.uin"
```

---

## 6. Problems hit, and the fix (in order)

| # | Error | Cause | Fix |
|---|---|---|---|
| 1 | `Cannot decrypt: key=mosip.kernel.pdf_owner_password` | `{cipher}` value needs a config server | replaced in step 1 |
| 2 | `UnknownHostException: dev.mosip.net` | default config-server URL | own file server (step 5) |
| 3 | `FileNotFoundException …identity-mapping.json / mosip-cbeff.xsd / applicanttype.mvel` | files downloaded at startup | all `.json .xsd .mvel .xml` from mosip-config (step 1, 5) |
| 4 | `BIO_SDK_007 SDK provider registry is empty` | no BioSDK client jar | `biosdk-client.jar` |
| 5 | `bioAPIFactory … rest call failed` | no BioSDK server / wrong URL | step 7 + `mosip.biosdk.default.service.url` |
| 6 | my settings ignored | `application-default.properties` outranks extra files | every local setting passed as `-D` |
| 7 | `MalformedURLException …8000mosip-cbeff.xsd` | missing trailing `/` | `mosip.kernel.xsdstorage-uri=http://config-files:8000/` |
| 8 | health DOWN, password failed for `idrepouser` | no databases | step 4 |
| 9 | `401 KER-ATH-401`, `Cannot obtain jwks …/auth/realms/mosip` | MOSIP expects `/auth`; local Keycloak 24 has none | issuer settings in `local.properties` |
| 10 | `500 NullPointerException validateAudience` | token without `aud` | step 6 (audience mapper) |
| 11 | `IDR-IDC-002 DateTimeParseException` | **register-id bug**: `requesttime` format | fixed in register-id |
| 12 | `IDR-IDC-004 Self cached auth token is null` | IDRepo has no own client | step 6 (`mosip-idrepo-client`) |
| 13 | `UnknownHostException: masterdata` | needs masterdata | step 8 |
| 14 | `KER-SCH-007 Identity schema not found` | schema version 0.1 ≠ requested 1.1 | step 3 sets 1.1 |
| 15 | `KER-IOV-004 … referenceIdentityNumber` | schema rule: 10–30 digits | test sends a 10-digit value |
| 16 | `IDR-IDC-002 Invalid Input Parameter - UIN` | mock UIN generator ignores MOSIP UIN rules | `mosip_uin.py` (rules + checksum from MOSIP source) |
| 17 | `UnknownHostException: keymanager` | needs keymanager | steps 8–9 |
| 18 | `IDR-IDC-012 Record already exists` although saved | unreachable WebSub made create take ~8 s; client timed out at 10 s and retried | `mosip.websub.url` points at the file server so it fails fast (and see FINDINGS bug 4) |
| 19 | read back `NOT found` | **register-id bug**: read path `/uin/{uin}` exists only in the mock | fixed: `/idvid/{uin}` |

---

## 7. Changes made in register-id (not committed yet)

| File | Change |
|---|---|
| `src/register_id/idrepo_client.py` | `requesttime` in MOSIP format `yyyy-MM-ddTHH:mm:ss.SSSZ`; read via `GET /idrepository/v1/identity/idvid/{uin}?type=demo&idType=UIN`; HTTP 200 with `errors` = not found |
| `src/mock/idrepo/app.py` | mock also serves `GET /idrepository/v1/identity/idvid/{id}` |
| `src/register_id/tests/idrepo_test.py` | 2 new tests (14 pass) |

Still open (design work, see `FINDINGS.md`): face templates (`/ida/v1/face-template` does not exist in real IDRepo),
list, update, delete-face paths, `referenceIdentityNumber` in the portal, and create retry after a timeout.

---

## 8. Answers for Mehul

- **IDRepo needs:** BioSDK (client + server), its DBs + salts, Keycloak (offline token check), its own client
  `mosip-idrepo-client`, **masterdata** (published identity schema), **keymanager** (master keys ROOT/KERNEL/ID_REPO).
  WebSub and audit only log errors, but WebSub should be reachable or fail fast.
- **register-id needs from the Kit:** a client whose token has an `aud` in `auth.server.admin.allowed.audience`;
  roles `ID_REPOSITORY`/`REGISTRATION_PROCESSOR`; matching `/auth` issuer; identity schema version **1.1** with the
  16-field required list; UINs from the real idgenerator.
- **Already fixed in register-id:** `requesttime` format, read path, error envelope.

---

## 9. Switch register-id between mock and real

**Now: register-id uses the REAL ID Repository** (since 27 Nov evening). The portal's enroll (with face) and
Prove (verify) both work against it.

How the switch works: `docker-compose.mosip.yml` hard-codes the mock URL, so a small overlay file
`tools/real-idrepo/docker-compose.real-idrepo.yml` sets `MOSIP_IDREPO_BASE_URL=http://idrepo-real:8090`.
It is turned on by the **`COMPOSE_FILE` line in register-id's `.env`**:

| Use | `COMPOSE_FILE=` in register-id `.env` |
|---|---|
| **Real** (now) | `docker-compose.yml:docker-compose.mosip.yml:tools/real-idrepo/docker-compose.real-idrepo.yml` |
| **Mock** | `docker-compose.yml:docker-compose.mosip.yml` |

After changing it, from the register-id folder:

```bash
docker compose up -d app
```

(`.env.bak-2026-11-27` is the `.env` before the switch.) UINs still come from the mock generator, which now
follows MOSIP's UIN rules, so the real IDRepo accepts them.

**Extra container for faces:** step 7b, `bash 07b-run-object-store.sh` (S3 store for the face CBEFF; SeaweedFS,
because MinIO images are no longer on Docker Hub).

### How to know register-id is running on the real one

1. Run `bash 13-which-idrepo.sh`. First line must say `= REAL MOSIP ID Repository`.
2. Enrol someone in the portal, run it again: `records` in `mosip_idrepo.idrepo.uin` goes up by 1, with
   `face_docs = 1`. Names are not visible there: the real IDRepo stores data **encrypted** (keymanager).
3. Watch the real IDRepo while you click **Create my ID** or verify:
   `docker logs -f idrepo-real 2>&1 | grep -i "offline verification done\|IDENTITY_CREATED"`
4. Look up one UIN directly in the real IDRepo: `bash 14-show-uin.sh <UIN>` → `REAL IDRepo: … FOUND`, name,
   whether a face is stored, and `MOCK IDRepo: … not found`.
5. Stop the real one (`docker stop idrepo-real`) and try to enrol: the portal now **fails** (503). With the mock it would not.
   Start it again with `docker start idrepo-real` (≈ 2 min).

### What does not work yet on the real one

Officer desk list, update (name/email/login flag) and delete-face use mock-only paths (FINDINGS bugs 6–8).
Email is off locally. Citizen sign-in redirect is broken locally (`/auth` path, unrelated to IDRepo).

**Stop the real stack (frees ~3.4 GB)** – switch register-id back to the mock first:

```bash
docker rm -f idrepo-real keymanager masterdata biosdk-service objectstore config-files
```

Databases, keys and stored faces stay. Next time start from step 5 (skip 1–4, 6, 9).

---

## 10. Memory (all running)

| Container | RAM | Limit |
|---|---|---|
| idrepo-real | 1.21 GB | 2 GB |
| keymanager | 0.81 GB | 1.5 GB |
| masterdata | 0.81 GB | 1.5 GB |
| biosdk-service | 0.43 GB | 1 GB |
| keycloak | 1.24 GB | – |
| register-id app, mock idrepo, Postgres, Redis, config-files | ~0.3 GB | – |
| **Total** | **~4.8 GB of 7.6 GB** | |

Watch with `docker stats --no-stream`.
