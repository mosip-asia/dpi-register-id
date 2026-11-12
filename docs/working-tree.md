# Feature commits on `feat/identity-split-and-sweep`

Work that was sitting uncommitted on `dev` at `ce05d78` now lives on `feat/identity-split-and-sweep`. `dev` itself was not moved. Each commit is one feat.

| Commit | Feat |
|---|---|
| `docs(branding)` | AIT color, type, and logo rules in `branding/`. Reference only. The web UI does not use them yet. |
| `chore(scripts)` | `scripts/web-local.sh`, `web-docker.sh`, `web-docker-restart.sh`, `web-reload.sh`. |
| `docs` | Current enroll and verify diagram in `docs/diagrams/`. Compile `current-system.tex` with `lualatex` from that directory. |
| `feat(embedder)` | Hash a JPEG into a 128-D unit vector. Same bytes match. Different bytes fall past the `0.50` distance. This does not recognize a face. |
| `feat(matcher)` | `match_gallery()` scores a probe by the closest stored vector. |
| `fix(liveness)` | EAR closure and delta limits follow the shallow blinks face-api actually reports. |
| `feat(idrepo)` | `citizen_identity` keeps the person, the image, and CBEFF. Match vectors go to `mosip_ida.face_template`. The server builds the frontal template. Authentication at this commit still does a 1:1 distance check against that template. |
| `feat(api)` | `POST /api/enroll` no longer takes a password. `POST /api/credentials` sends it to Keycloak afterward. There is no `CitizenPass123!` default. |
| `feat(sweep)` | Verification is five poses, left shoulder to right, bound to a 90-second single-use challenge. Blinks stay on the page as diagnostics. A pass means the challenge was valid, the client yaw labels step left to right, and the five images are distinct. Yaw is not measured from the pixels. `isFaceMatch` and `livenessPassed` stay false. |

`.winnow/` is local session state and is not part of this branch.
