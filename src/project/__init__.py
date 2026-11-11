from dotenv import load_dotenv
from pathlib import Path
import os
import sys

# Detect target environment: dev (default), stg, or prod
_target_env = os.getenv("ENVIRONMENT", "dev").lower()

# Priority order for loading environment file:
# 1. Explicit ENV_FILE if specified in os.environ
# 2. .env.<environment> (e.g. .env.dev, .env.stg, .env.prod)
# 3. .env (standard: copied from .env.example)
_env_candidates: list[Path | None] = [
    Path(os.environ["ENV_FILE"]) if "ENV_FILE" in os.environ else None,
    Path(f".env.{_target_env}"),
    Path(".env"),
]

_loaded_file = None
for _candidate in _env_candidates:
    if _candidate and _candidate.exists():
        load_dotenv(dotenv_path=_candidate)
        _loaded_file = _candidate
        break

if not _loaded_file:
    print(
        f"[Warning] No env file found (.env or .env.{_target_env}). Please copy .env.example to .env",
        file=sys.stderr,
    )

# Ensure essential defaults
os.environ.setdefault("ENVIRONMENT", _target_env)
os.environ.setdefault("BUILD_VERSION", "0.1.0-dev")
os.environ.setdefault("PROJECT_NAME", "register-id")
os.environ.setdefault("LOG_DIR", "logs/")
os.environ.setdefault("LOG_NAME", "main.log")
os.environ.setdefault("LOG_ROTATE_NAME", "main_rotate.log")
os.environ.setdefault("LOG_LEVEL", "DEBUG" if _target_env == "dev" else "INFO")
os.environ.setdefault("FASTAPI_HOST", "0.0.0.0")
os.environ.setdefault("FASTAPI_PORT", "8000")
os.environ.setdefault("FASTAPI_WORKERS", "1")
os.environ.setdefault("REDIS_URL", "redis://:redispassword@localhost:6379/0")

# We do this to load the logger (which will config the logger for this module)
import project.logger  # type: ignore

# This is how you do logging
import logging

logging.debug("App start")

# Start loading modules
from project.cli import cli  # type: ignore
