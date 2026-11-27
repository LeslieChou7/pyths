import subprocess
import time

import pytest

from pyths._resolve import resolve
from pyths.errors import ThsNetworkError


def test_numeric_address_never_starts_worker(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("numeric address started process")

    monkeypatch.setattr(subprocess, "run", fail)
    assert (
        resolve("127.0.0.1", 9528, deadline=time.monotonic() + 1)[0][1] == "127.0.0.1"
    )


def test_resolver_timeout_is_sanitized(monkeypatch):
    def timeout(*args, **kwargs):
        assert 0 < kwargs["timeout"] <= 1
        raise subprocess.TimeoutExpired("sensitive diagnostic", kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ThsNetworkError) as error:
        resolve("example.invalid", 9528, deadline=time.monotonic() + 1)
    assert "sensitive" not in str(error.value)


def test_expired_deadline_never_starts_worker(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("worker started")
    )
    with pytest.raises(ThsNetworkError):
        resolve("example.invalid", 9528, deadline=time.monotonic() - 1)
