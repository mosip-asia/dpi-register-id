import pytest
from project.register_id.matcher import (
    compute_cosine_similarity,
    compute_euclidean_distance,
    match_embeddings,
)


def test_euclidean_distance_exact():
    v1 = [0.1, 0.2, 0.3, 0.4]
    v2 = [0.1, 0.2, 0.3, 0.4]
    assert compute_euclidean_distance(v1, v2) == 0.0


def test_match_embeddings_same_person():
    v1 = [0.1] * 128
    v2 = [0.12] * 128
    is_match, dist, conf = match_embeddings(v1, v2, threshold=0.50)
    assert is_match is True
    assert dist < 0.50
    assert conf > 50.0


def test_match_embeddings_different_person():
    v1 = [0.1] * 128
    v2 = [0.9] * 128
    is_match, dist, conf = match_embeddings(v1, v2, threshold=0.50)
    assert is_match is False
    assert dist > 0.50
    assert conf == 0.0


def test_cosine_similarity_identical():
    v1 = [1.0, 2.0, 3.0]
    v2 = [1.0, 2.0, 3.0]
    sim = compute_cosine_similarity(v1, v2)
    assert round(sim, 4) == 1.0
