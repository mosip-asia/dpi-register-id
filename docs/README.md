# 📖 Documentation Directory (`docs/`)

This directory contains technical architecture specifications, deployment procedures, and foundation tutorials for the **`register-id`** repository.

---

## 🏛️ Architecture & Guides

| Document | Description |
|---|---|
| **[`user-manual.md`](user-manual.md)** | **Hands-On User Manual:** Step-by-step walkthrough for developers to spin up the stack, test WebRTC liveness, enroll citizen biometrics into IDRepo, verify 1:1 match, and test spoof rejection. |
| **[`objectives-and-milestones.md`](objectives-and-milestones.md)** | **Primary Project Specification:** Zero-hardware citizen onboarding, ISO/IEC 30107-3 PAD liveness, ISO 19794-5 CBEFF packaging, MOSIP IDRepo & Keycloak IAM bridge, RACI matrix, and 8-week delivery milestones (Weeks 1–8). |
| **[`deployment.md`](deployment.md)** | **Deployment & Infrastructure Guide:** GitHub Actions multi-environment CD pipeline (`cd.yml`), NetBird VPN mesh setup, Traefik reverse proxy overlay, and automated host rollbacks (`.deploy_success`). |
| **[`../branding/README.md`](../branding/README.md)** | **Branding kit:** Official AIT color, type, and logo rules for register-id. Reference only; not applied to the web UI yet. |
| **[`../AGENTS.md`](../AGENTS.md)** | **Operational Invariants:** Coding guidelines, branching model (`dev` -> `stg` -> `main`), sensitive data guard rules, and release automation. |

---

## 🎓 Template Tutorials (`docs/tutorial/`)

The starter template includes foundational guides for the hybrid Python stack:

| Tutorial | Description |
|---|---|
| **[`tutorial/fastapi-web.md`](tutorial/fastapi-web.md)** | Running FastAPI REST endpoints, Jinja2 template rendering, and `/health` checks. |
| **[`tutorial/celery-processor.md`](tutorial/celery-processor.md)** | Distributed background task queue with Celery and Redis. |
| **[`tutorial/django.md`](tutorial/django.md)** | Reusable Django modular apps, `django_manage.py` commands, and dev harness. |
