import subprocess
import sys

import pytest

from pyths import ThsClientClosedError, ths


def test_lifecycle():
    client = ths()
    with client as entered:
        assert entered is client
        assert not client.closed
    client.close()
    assert client.closed
    with pytest.raises(ThsClientClosedError), client:
        pass


def test_exception_propagates():
    client = ths()
    with pytest.raises(ValueError, match="sentinel"), client:
        raise ValueError("sentinel")
    assert client.closed


def test_no_socket():
    code = """
import sys
def guard(event, args):
    if event.startswith('socket.'):
        raise AssertionError(event)
sys.addaudithook(guard)
from pyths import ths
with ths():
    pass
"""
    import os
    from pathlib import Path

    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    subprocess.run([sys.executable, "-c", code], env=env, check=True)
