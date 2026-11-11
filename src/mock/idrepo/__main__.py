"""
Entrypoint for `python -m mock.idrepo`.
"""

import os
from mock.idrepo.app import run_idrepo_server

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    run_idrepo_server(host=host, port=port)
