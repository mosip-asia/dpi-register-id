import logging
import os
import sys

# Kubernetes collects container stdout. This process does not open log files.
_env = os.getenv("ENVIRONMENT", "dev").lower()
_default_log_level = "DEBUG" if _env == "dev" else "INFO"
_log_level_str = os.getenv("LOG_LEVEL", _default_log_level).upper()
_log_level = getattr(logging, _log_level_str, logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s|%(filename)s:%(funcName)s:%(lineno)d|%(levelname)s|%(message)s"
)
formatter.datefmt = "%d-%m-%Y %H:%M:%S"

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

logging.basicConfig(
    level=_log_level,
    handlers=[console_handler],
)
