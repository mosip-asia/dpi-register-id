"""
register_id: DPI Citizen Registration Gateway Submodule.

Provides zero-hardware citizen onboarding, ISO 30107-3 PAD liveness,
ISO 19794-5 / ISO 19785-3 CBEFF biometric packaging, and MOSIP IDRepo / Keycloak IAM integration.
"""

from register_id.api import router
from register_id.cli import cli
from register_id.liveness import evaluate_liveness
from register_id.matcher import (
    compute_cosine_similarity,
    compute_euclidean_distance,
    match_embeddings,
)
from register_id.models import (
    AuthRequest,
    AuthResponse,
    CitizenSummary,
    EnrollRequest,
    LivenessRequest,
    LivenessResponse,
)

__all__ = [
    "router",
    "cli",
    "evaluate_liveness",
    "match_embeddings",
    "compute_euclidean_distance",
    "compute_cosine_similarity",
    "EnrollRequest",
    "AuthRequest",
    "AuthResponse",
    "LivenessRequest",
    "LivenessResponse",
    "CitizenSummary",
]
