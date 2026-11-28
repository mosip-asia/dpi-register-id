# Real MOSIP ID Repository next to register-id: findings

Last update: 27 Nov 2026. All MOSIP parts at **1.2.0.1** (images `mosipid/*:1.2.0.1`, config `mosip-config` tag `v1.2.0.1`).
Laptop: 16 GB RAM, Docker gets 7.6 GB. Each MOSIP container has a memory limit.

## Result

| Check | Status |
|---|---|
| Real ID Repository starts, health UP, database connected | ✅ |
| Accepts register-id's Keycloak token | ✅ `offline verification done` |
| Validates register-id's identity against the identity schema from real masterdata | ✅ |
| **Saves the identity** (data encrypted by real keymanager) | ✅ `saved: True`, row in `idrepo.uin`, status `ACTIVATED` |
| **Reads it back** with register-id's client | ✅ after fixing the read path (see bugs) |

## What the ID Repository needs (found by running it, in the order it failed)

| # | Needed | Error without it | When |
|---|---|---|---|
| 1 | Config: `application-default.properties`, `id-repository-default.properties` | – | startup |
| 2 | The 2 encrypted `{cipher}` values replaced (or a config server that decrypts them) | `Cannot decrypt: key=mosip.kernel.pdf_owner_password` | startup |
| 3 | Files over HTTP from the config-server URL: `identity-mapping.json`, `mosip-cbeff.xsd`, VID policy JSON | `UnknownHostException dev.mosip.net`, `FileNotFoundException` | startup |
| 4 | Jars `kernel-auth-adapter`, `kernel-ref-idobjectvalidator` (normally from MOSIP artifactory) | image cannot start without artifactory | startup |
| 5 | **BioSDK client jar** `biosdk-client` 1.2.0.1 | `BIO_SDK_007 SDK provider registry is empty` | startup |
| 6 | **BioSDK server** `mosipid/biosdk-server` + **mock SDK** (`io.mosip.mock.sdk.impl.SampleSDKV2`) | `bioAPIFactory … rest call failed` | startup |
| 7 | Postgres **`mosip_idrepo`, `mosip_idmap`** (MOSIP scripts) | health DOWN | runtime |
| 8 | **1000 salts** in `uin_hash_salt`, `uin_encrypt_salt` (both DBs) (MOSIP salt-generator job) | – | first write |
| 9 | Keycloak keys at `<issuer>/protocol/openid-connect/certs` (token check is offline) | `401 KER-ATH-401 Cannot obtain jwks` | every call |
| 10 | Caller token with an **`aud`** listed in `auth.server.admin.allowed.audience` | `500 NullPointerException validateAudience` | every call |
| 11 | **Its own Keycloak client `mosip-idrepo-client`** (client_credentials, audience, roles) | `IDR-IDC-004 Self cached auth token is null` | every write |
| 12 | **Masterdata** (`mosipid/kernel-masterdata-service`) + **`mosip_master`** DB + one published **identity schema** whose `id_version` = the request's `IDSchemaVersion` | `UnknownHostException masterdata`, then `KER-SCH-007 Identity schema not found` | every write |
| 13 | **Keymanager** (`mosipid/kernel-keymanager-service`) + **`mosip_keymgr`** DB (with key policies) + keystore (PKCS12 locally, HSM in production) + **master keys ROOT, KERNEL, ID_REPO** | `UnknownHostException keymanager` | every write |
| 14 | WebSub: reachable, or failing fast | not blocking, but an unreachable host adds ~8 s to every create | every write |
| 15 | Audit manager | only logged (`UnknownHostException auditmanager`), not blocking | every call |
| – | ID generator | not called by IDRepo for create; register-id calls it | – |
| 16 | **S3 object store** (MOSIP: MinIO; locally SeaweedFS because MinIO images left Docker Hub) at `object.store.s3.url`, keys `s3.accesskey/secretkey` | enrol with a face hangs (client times out) or `IDR-IDS-004 Failed to store/retrieve files in Object Store` | enrol with a face |
| – | Credential services | not needed | – |

Masterdata itself needed: `kernel-default.properties`, files `applicanttype.mvel`, `hazelcast_*.xml`.
Keymanager itself needed: `mosip.kernel.tokenid.uin.salt` / `partnercode.salt`.

## Memory (everything running)

| Container | RAM | Limit |
|---|---|---|
| idrepo-real | 1.21 GB | 2 GB |
| keymanager | 0.81 GB | 1.5 GB |
| masterdata | 0.81 GB | 1.5 GB |
| biosdk-service | 0.43 GB | 1 GB |
| keycloak | 1.24 GB | – |
| register-id app, mock idrepo, Postgres, Redis, config-files | ~0.3 GB | – |
| **Total** | **~4.8 GB of 7.6 GB** | |

## For Mehul / the Kit

1. register-id's Keycloak client must issue tokens with an **`aud`** that is in IDRepo's `auth.server.admin.allowed.audience`
   (audience mapper; or use a client already in the list, e.g. `mosip-regproc-client`).
2. Roles `ID_REPOSITORY` / `REGISTRATION_PROCESSOR` on that client's service account.
3. MOSIP Keycloak issuer is `…/auth/realms/mosip`; `KEYCLOAK_INTERNAL_URL` must match it.
4. The Kit's published identity schema **version** must equal register-id's `SCHEMA_VERSION` (1.1), and its
   `required` list must match what the portal sends. MOSIP's default seed is version 0.1 and also requires
   `proofOfIdentity` and `individualBiometrics`.
5. Field rules from the schema that register-id must meet: `referenceIdentityNumber` **10–30 digits**,
   `phone` `^[+]*([0-9]{1})([0-9]{9})$`, `postalCode` 5 letters/digits or `NA`, `dateOfBirth` `yyyy/MM/dd`,
   `fullName` 3–50 characters.
6. UINs must come from the **real idgenerator** (MOSIP checksum and number rules). register-id's mock generator
   returns plain random numbers, which IDRepo rejects (`IDR-IDC-002 Invalid Input Parameter - UIN`).

## Bugs found in register-id (the mock never caught them)

| # | Bug | Effect on real IDRepo | Status |
|---|---|---|---|
| 1 | `requesttime` sent as `…11:03:23.611440+00:00` | `IDR-IDC-002` (`DateTimeParseException`) | **Fixed** (`idrepo_client._now_iso` → `…SSSZ`) |
| 2 | Read used `GET /identity/uin/{uin}` (mock only) | read never finds anyone (Prove flow) | **Fixed** → `GET /identity/idvid/{uin}?type=demo&idType=UIN`; mock serves both |
| 3 | Read treated HTTP 200 as success | real IDRepo returns 200 + `errors` for unknown UIN | **Fixed** (errors → not found) |
| 4 | Create is retried after a client timeout | a slow first attempt that succeeded → retry gets `IDR-IDC-012 Record already exists` → enrol reported as failed | Open: treat `IDR-IDC-012` on a retry of the same registration id as success, or raise the create timeout |
| 5 | Face templates read from `GET /ida/v1/face-template/uin/{uin}` | **does not exist** in real IDRepo → Prove face match has no gallery | **Fixed**: descriptors stored in the CBEFF `others` entries (`face-api-128#n`); verify falls back to reading the CBEFF via `/idvid?type=all` |
| 10 | CBEFF used ISO 19785-3 **ed-1** namespace and a flat layout | `Cannot find the declaration of element 'BIR'` | **Fixed**: ed-2, outer BIR + face BIR, Format/Quality as elements; validated against `mosip-cbeff.xsd` |
| 11 | Identity lacked the `individualBiometrics` reference for the document | `validateDocuments failed for individualBiometrics` | **Fixed**: `{"format":"cbeff","version":1.0,"value":"individualBiometrics_bio.cbeff"}` |
| 12 | Mock UIN generator returned plain random numbers | `IDR-IDC-002 Invalid Input Parameter - UIN` | **Fixed**: `src/mock/idrepo/uin.py` follows MOSIP's UIN validator + checksum |
| 6 | Officer list `GET /identity/` | does not exist in real IDRepo | Open |
| 7 | Update `PATCH /identity/uin/{uin}` (name, email, login flag) | real IDRepo uses `PATCH /identity/` with the UIN in the body | Open |
| 8 | Delete face `DELETE /identity/uin/{uin}/biometrics` | does not exist in real IDRepo | Open |
| 9 | `referenceIdentityNumber` may be empty | schema requires 10–30 digits | Open: portal must collect it, or Kit schema must not require it |

## Files

See `MANUAL.md`. Scripts `01` … `11` run in order. `idrepo.env` holds local secrets; do not share it.
