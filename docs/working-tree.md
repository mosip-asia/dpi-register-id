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
