# Celery & Asynchronous Task Processing

For background processing, queuing, or pub-sub workloads, the starter includes a pre-configured **Celery** stack backed by **Redis**.

---

## Directory Structure

```
src/project/
├── celery.py                 # Celery app instance & configuration
├── processor/                # Direct in-process data processor
│   ├── __init__.py
│   ├── works.py
│   └── works_test.py
└── processor_celery/         # Celery distributed task runner
    ├── __init__.py
    ├── cli.py                # Worker CLI entrypoint
    ├── works.py              # Celery task definitions
    └── works_test.py         # Unit tests
```

---

## Configuration

Celery connects to Redis using the `REDIS_URL` environment variable:
- **Local Host (`uv run`)**: `redis://:redispassword@localhost:6379/0`
- **Docker Container**: In `docker-compose.yml`, the `environment:` section automatically routes Redis to the internal `redis` container (`redis://:redispassword@redis:6379/0`).

---

## Starting Workers

### 1. Start the Redis Broker
```bash
docker compose up -d redis
```

### 2. Start Celery Worker
```bash
# Using the Typer CLI
uv run python-project-starter celery worker

# Or directly via celery
uv run celery -A project.celery.queue worker --loglevel=info
```

---

## Process Supervision (`supervisord.conf`)

To run the web service and background celery worker together in a single development session, `supervisord.conf` is provided:

```bash
uv run supervisord -c supervisord.conf
```
