"""
1:1 Biometric Verification Engine for register_id.

Calculates Euclidean (L2) distance and Cosine similarity between
stored gallery face embeddings and live probe descriptors.
"""

import math


def compute_euclidean_distance(embedding1: list[float], embedding2: list[float]) -> float:
    """
    Computes Euclidean (L2) Distance between two embedding vectors.
    """
    if len(embedding1) != len(embedding2):
        raise ValueError(
            f"Embedding dimension mismatch: {len(embedding1)} vs {len(embedding2)}"
        )
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(embedding1, embedding2)))


def compute_cosine_similarity(embedding1: list[float], embedding2: list[float]) -> float:
    """
    Computes Cosine Similarity between two embedding vectors (-1.0 to 1.0).
    """
    if len(embedding1) != len(embedding2):
        raise ValueError(
            f"Embedding dimension mismatch: {len(embedding1)} vs {len(embedding2)}"
        )
    dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
    norm_a = math.sqrt(sum(a * a for a in embedding1))
    norm_b = math.sqrt(sum(b * b for b in embedding2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def match_embeddings(
    stored: list[float],
    probe: list[float],
    threshold: float = 0.50,
) -> tuple[bool, float, float]:
    """
    Compares stored gallery embedding against live probe.

    Returns:
        (is_match: bool, distance: float, match_confidence_pct: float)
    """
    distance = compute_euclidean_distance(stored, probe)
    is_match = distance < threshold
    # Normalize score: distance 0.0 -> 100%, distance >= 1.0 -> 0%
    confidence = max(0.0, min(100.0, (1.0 - (distance / 1.0)) * 100.0))
    return is_match, round(distance, 4), round(confidence, 1)
