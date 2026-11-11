"""
MOSIP Identity Repository (IDRepo) Integration.

Re-exports IDRepoClient for backwards compatibility.
All identity operations are executed via the MOSIP IDRepo REST interface.
"""

from register_id.idrepo_client import IDRepoClient, get_idrepo_client

__all__ = ["IDRepoClient", "get_idrepo_client"]
