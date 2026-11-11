import logging
import logging.handlers as handlers
import sys
import os
from pathlib import Path

if "LOG_DIR" not in os.environ:
    raise EnvironmentError("Missing 'LOG_DIR' in environment variable")
if "LOG_NAME" not in os.environ:
    raise EnvironmentError("Missing 'LOG_NAME' in environment variable")
if "LOG_ROTATE_NAME" not in os.environ:
    raise EnvironmentError("Missing 'LOG_ROTATE_NAME' in environment variable")

_LOG_DIR = Path(os.environ["LOG_DIR"])
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_PATH = _LOG_DIR.joinpath(os.environ["LOG_NAME"])
_LOG_ROTATE_PATH = _LOG_DIR.joinpath(os.environ["LOG_ROTATE_NAME"])

# Log level: default DEBUG for dev, INFO for stg/prod
_env = os.getenv("ENVIRONMENT", "dev").lower()
_default_log_level = "DEBUG" if _env == "dev" else "INFO"
_log_level_str = os.getenv("LOG_LEVEL", _default_log_level).upper()
_log_level = getattr(logging, _log_level_str, logging.INFO)

# log format
formatter = logging.Formatter(
    "%(asctime)s|%(filename)s:%(funcName)s:%(lineno)d|%(levelname)s|%(message)s"
)
formatter.datefmt = "%d-%m-%Y %H:%M:%S"

# console handler
consoleHandler = logging.StreamHandler(sys.stdout)
consoleHandler.setFormatter(formatter)

# file handlers
fileHandler = handlers.RotatingFileHandler(
    filename=_LOG_ROTATE_PATH, mode="a", maxBytes=10240000, backupCount=10
)
fileHandler.setFormatter(formatter)
fileHandler2 = logging.FileHandler(filename=_LOG_PATH, mode="a")
fileHandler2.setFormatter(formatter)

logging.basicConfig(
    level=_log_level,
    handlers=[
        fileHandler,
        fileHandler2,
        consoleHandler,
    ],
)
