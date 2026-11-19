import logging

from project.celery import log_broker_target, redis_url_for_log


def test_redis_url_for_log_hides_password():
    raw = "redis://:s3cret@redis.internal:6379/0"
    assert redis_url_for_log(raw) == "redis://:***@redis.internal:6379/0"
    assert "s3cret" not in redis_url_for_log(raw)


def test_redis_url_for_log_hides_user_password_and_keeps_tls():
    raw = "rediss://app:p%40ss@[::1]:6380/1?ssl_cert_reqs=required"
    logged = redis_url_for_log(raw)
    assert logged == "rediss://app:***@[::1]:6380/1?ssl_cert_reqs=required"
    assert "p%40ss" not in logged


def test_redis_url_for_log_leaves_url_without_credentials():
    raw = "redis://localhost:6379/0"
    assert redis_url_for_log(raw) == raw


def test_broker_log_omits_password(caplog):
    secret = "super-secret-redis"
    with caplog.at_level(logging.DEBUG, logger="project.celery"):
        log_broker_target(f"redis://:{secret}@localhost:6379/0")
    assert secret not in caplog.text
    assert "REDIS_URL=redis://:***@localhost:6379/0" in caplog.text
