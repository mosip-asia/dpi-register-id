# FastAPI Web Service & REST API

The web module provides a lightweight REST API and HTML template rendering engine powered by **FastAPI** and **Jinja2**.

---

## Directory Structure

```
src/project/web/
├── __init__.py          # Web package root
├── py.typed             # PEP 561 typing marker
├── router.py            # Route definitions and FastAPI app instance
└── templates/           # Jinja2 HTML templates
    ├── base.html        # Base HTML layout
    ├── index.html       # Landing page (with environment & version badges)
    └── example.html     # Dynamic template example
```

---

## Key Endpoints

- **`GET /health`**:
  Health check endpoint required by Docker container probes, CI/CD runners, and post-deployment smoke tests.
  ```json
  {
    "status": "ok",
    "environment": "dev",
    "version": "0.1.0-dev"
  }
  ```
- **`GET /`**:
  Renders the interactive landing page (`index.html`) displaying project metadata and environment status.
- **`GET /example/{example_id}`**:
  Demonstrates dynamic URL parameter handling and template rendering.

---

## Running the Web Service

### Local Development (Direct)
```bash
uv run uvicorn project.web:app --host 0.0.0.0 --port 8000 --reload
```

### Via Root CLI
```bash
uv run register-id web
```

### In Docker
The container runs the production runner stage via `uvicorn`:
```bash
docker compose up -d app
```
Service will be available at `http://127.0.0.1:${FASTAPI_PORT:-8000}`.
