"""
Mock MOSIP IDRepo package.
"""

from mock.idrepo.app import idrepo_app, run_idrepo_server
from mock.idrepo.storage import IDRepoStorage

__all__ = ["idrepo_app", "run_idrepo_server", "IDRepoStorage"]
