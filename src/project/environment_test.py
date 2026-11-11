import os


def test_environment_values():
    valid_environments = {"dev", "stg", "prod"}
    current_env = os.getenv("ENVIRONMENT", "dev").lower()
    # Ensure current environment is one of dev, stg, or prod
    assert current_env in valid_environments


def test_build_version_fallback():
    from project.web.router import _BUILD_VERSION, _ENVIRONMENT

    assert _BUILD_VERSION is not None
    assert _ENVIRONMENT in {"dev", "stg", "prod"}
