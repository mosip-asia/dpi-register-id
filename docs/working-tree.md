# Feature commits on `dev`

These commits were rebased onto `origin/dev` (`8fb1efb`, skip-blink and the relaxed EAR limits) and fast-forwarded onto `dev`.

| Commit | Feat |
|---|---|
| `docs(branding)` | AIT color, type, and logo rules in `branding/`. Reference only. The web UI does not use them yet. |
| `chore(scripts)` | `scripts/web-local.sh`, `web-docker.sh`, `web-docker-restart.sh`, `web-reload.sh`. |
| `docs` | Current enroll and verify diagram in `docs/diagrams/`. Compile `current-system.tex` with `lualatex` from that directory. |
| `feat(embedder)` | Hash a JPEG into a 128-D unit vector. Same bytes match. Different bytes fall past the `0.50` distance. This does not recognize a face. |
| `feat(matcher)` | `match_gallery()` scores a probe by the closest stored vector. |
| `feat(idrepo)` | `citizen_identity` keeps the person, the image, and CBEFF. Match vectors go to `mosip_ida.face_template`. The server builds the frontal template. Authentication at this commit still does a 1:1 distance check against that template. |
| `feat(api)` | `POST /api/enroll` no longer takes a password. `POST /api/credentials` sends it to Keycloak afterward. There is no `CitizenPass123!` default. |
| `feat(sweep)` | Verification is five poses, left shoulder to right, bound to a 90-second single-use challenge. Blinks stay on the page as diagnostics. **Skip Blink** records a blink override and does not replace the sweep. A pass means the challenge was valid, the client yaw labels step left to right, and the five images are distinct. Yaw is not measured from the pixels. `isFaceMatch` and `livenessPassed` stay false. |

The separate EAR-threshold commit was dropped on rebase. `8fb1efb` already uses a minimum EAR under `0.25`, a delta of at least `0.04`, and `bypassLiveness`.

## Citizen portal and registry gates

`feat: serve the citizen portal and keep identity claims bounded` is on `dev`. `dev-local` carried the work and was fast-forwarded. It is not a release branch and was not pushed.

### Citizen portal

`web/` is a Vite, React, and TanStack Router app, installed with pnpm. The image builds it in a Node stage and copies `web/dist` into the runner. FastAPI serves that build at `/` when `web/dist/index.html` exists. `/lab` remains the Jinja test page. `/example/{id}` is unchanged for the smoke test.

The portal is a desktop page: institute name, then register-id, then a step rail, a task column, and a side note. Under 800px the rail hides and the step line shows above the title. Type and color come from `branding/tokens.css`. Lime is only the top rule on the success panel after enrollment stores a number. There is no logo file in the repo, so the header is type only.

Enrollment order is consent, details, face-check instructions, camera, photo, review, then create. Later enrollment routes send the browser back when consent or the detail fields are missing. Gender, date of birth, and the research option stay in `sessionStorage`. The enroll request sends UIN, name, email, photo, and consent.

The ready screen shows the number only after `POST /api/enroll` succeeds. A typed UIN is not treated as enrolled. The page does not send email. A face check shows the server message on the same page when the server did not compare a face, and it does not spend an attempt for that result. `/prove/verified` renders only after `isFaceMatch` is true, and that flag is dropped on reload. `jwtToken` stays null. The portal does not start `/api/login/start`.

### Registry behavior

- Shared challenges for the sweep and the liveness nonce are single-use. They use Redis when `REDIS_URL` is set, and they fail closed when that URL is set and Redis is down.
- Enroll requires consent: accepted, a purpose, a time, and `eng` or `tha`. The audit line keeps the language, the time, and a short purpose. The identity row does not store the consent object.
- The hash embedder sets `CAN_IDENTIFY_FACE` false. Enroll stores a draft. A CBEFF packaging failure stores nothing. `isFaceMatch` and `livenessPassed` on authenticate stay false with this engine. The server does not copy client yaw into a measured yaw.
- `POST /api/credentials` returns 502 when Keycloak does not store the login. A 409 succeeds only for the same UIN, and then resets the password. Provisioning does not set `individualBiometrics`.
- `GET /api/citizens`, `GET /api/citizens/{uin}`, and `GET /api/audit` require `Authorization: Bearer` matching `REGISTER_ID_OPERATOR_TOKEN`. The role is `REGISTER_ID_OPERATOR_ROLE` (`reader` or `custodian`). An empty token is 401. Reads omit face bytes. A custodian can correct demographics, disable login in Keycloak and on the registry flag, and delete a face.
- Audit records enroll, credential, authenticate, and operator actions. It drops passwords, face images, embeddings, CBEFF, and tokens. The log is the Redis list `register-id:audit`, or `LOG_DIR/audit.jsonl` when Redis is unset.
- `GET /api/login/start` begins authorization-code PKCE. The callback stores the token in an HttpOnly cookie. Session and logout do not return that token to the page. The Jinja lab and the portal do not call this route.

Compose passes the OIDC client settings, the cookie flag, and the operator token from `.env`. Copy `.env.example` to `.env` before the next `docker compose up`. An empty operator token denies the operator routes.
