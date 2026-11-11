## Description

<!-- Provide a brief description of the changes introduced by this pull request. -->

---

## Promotion & Target Branch

Please select the promotion tier for this PR:
- [ ] **Feature PR (`feature/*` -> `dev`)**: Day-to-day development integration.
- [ ] **Staging Promotion (`dev` -> `stg`)**: Merging triggers automated deployment to the `staging` environment.
- [ ] **Production Promotion (`stg` -> `main`)**: Merging triggers automated deployment to the `production` environment.

---

## Pre-Submission Verification Checklist

Before opening or merging this PR, confirm the following:
- [ ] Executed local pre-push checks (`bash scripts/check.sh`) and all tests passed.
- [ ] Sensitive data guard verified: no credentials, real user PII, database dumps, or raw spreadsheets are committed.
- [ ] If promoting to `stg` or `main`:
  - [ ] A release tag was cut on `dev` via `bash scripts/release.sh vX.Y.Z`.
  - [ ] Docker image built and pushed to GHCR successfully.
  - [ ] Target environment secrets and variables are configured in GitHub Settings > Environments (`staging` / `production`).
- [ ] Post-deployment smoke tests passed on previous environment.
