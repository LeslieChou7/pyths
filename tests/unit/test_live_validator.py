"""验证联网门禁、跨运行预算、脱敏和生命周期编排；本文件不联网。"""

import importlib.util
import json
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pyths import ThsNetworkError, ThsProtocolError
from pyths.models import QuoteField, QuoteSnapshot


@pytest.fixture
def validator():
    path = Path(__file__).resolve().parents[2] / "tools/validate_live.py"
    spec = importlib.util.spec_from_file_location("live_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_precedes_file_and_network_access(validator, monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_live.py",
            "--scenario",
            "quotes",
            "--host",
            "example.invalid",
            "--port",
            "9528",
            "--app-config",
            str(tmp_path / "absent"),
            "--app-info",
            "synthetic",
            "--sdk-revision",
            "test",
            "--wheel-sha256",
            "test",
            "--report",
            str(tmp_path / "report.json"),
            "--budget",
            str(tmp_path / "budget.json"),
        ],
    )
    monkeypatch.setattr(validator, "execute", lambda *a: pytest.fail("gate bypassed"))
    with pytest.raises(SystemExit) as error:
        validator.main()
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_shared_budget_is_atomic_and_failed_calls_still_count(validator, tmp_path):
    path = tmp_path / "budget.json"

    def reserve(_):
        try:
            return validator.reserve_call(path)
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(13)))
    assert sorted(x for x in results if x is not None) == list(range(1, 13))
    assert results.count(None) == 1
    assert json.loads(path.read_text())["calls"] == 12


def test_observer_counts_handshake_by_wire_flags_not_app_dispatch_frame(
    validator, monkeypatch
):
    stats = {
        "handshakes": 0,
        "queries": 0,
        "stops": 0,
        "close_calls": 0,
        "sent_headers": [],
    }
    sent = []
    monkeypatch.setattr(
        validator.TcpTransport, "send", lambda self, packet, **kw: sent.append(packet)
    )
    module = validator.importlib.import_module("pyths.client")
    original = module.TcpTransport
    private_body = b"private-session-sentinel"
    handshake = (
        struct.pack("<HiiHiii", 24, 0, 0x70000, 0, len(private_body), 0, 0)
        + private_body
    )
    query = struct.pack("<HiiHiii", 24, 1, 0x1010000, 0, 0, 2267, 0)
    stop = struct.pack("<HiiHiii", 24, 2, 0x1060000, 0, 0, 2267, 0)
    with validator.observe_transport(stats):
        transport = module.TcpTransport()
        transport.send(handshake, deadline=1)
        transport.send(query, deadline=1)
        transport.send(stop, deadline=1)
        transport.close()
    assert module.TcpTransport is original
    assert stats["handshakes"] == stats["queries"] == 1
    assert stats["stops"] == 1
    assert sent == [handshake, query, stop]
    assert "private-session-sentinel" not in json.dumps(stats)


def test_explicit_budget_increase_preserves_prior_calls(validator, tmp_path):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"calls": 12, "limit": 12}))
    with pytest.raises(RuntimeError):
        validator.reserve_call(path)
    assert validator.reserve_call(path, limit=20) == 13
    assert json.loads(path.read_text()) == {"calls": 13, "limit": 20}
    with pytest.raises(RuntimeError):
        validator.reserve_call(path)


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("frame: invalid header", "invalid_envelope_header"),
        ("private-session-sentinel", "other"),
    ],
)
def test_receive_diagnostics_are_allowlisted(validator, monkeypatch, message, code):
    stats = {"empty_envelopes": 0, "receive_errors": [], "close_calls": 0}

    def fail(self, *, deadline):
        raise ThsProtocolError(message)

    monkeypatch.setattr(validator.TcpTransport, "receive", fail)
    module = validator.importlib.import_module("pyths.client")
    with validator.observe_transport(stats):
        transport = module.TcpTransport()
        with pytest.raises(ThsProtocolError):
            transport.receive(deadline=1)
        transport.close()
    assert stats["receive_errors"] == [
        {"error_type": "ThsProtocolError", "safe_code": code}
    ]
    assert "private-session-sentinel" not in json.dumps(stats)


@pytest.mark.parametrize("failure", [None, ThsNetworkError, ThsProtocolError])
def test_lifecycle_schedule_closes_and_never_persists_session(
    validator, monkeypatch, tmp_path, failure
):
    clock, calls, clients = [0], [], []
    value = QuoteField("1.00", 0, "1.00")
    quote = QuoteSnapshot("000001", "33", *([value] * 9), received_at=datetime.now(UTC))

    class Client:
        def __init__(self, **kwargs):
            self._session = None
            self.closed = False
            clients.append(self)

        def get_quote(self, code, *, market):
            calls.append(clock[0])
            if len(calls) == 4 and failure:
                self._session = None
                raise failure("private-session-sentinel")
            self._session = self._session or SimpleNamespace(
                session_id="private-session-sentinel"
            )
            return quote

        def close(self):
            self.closed, self._session = True, None

    monkeypatch.setattr(validator, "ths", Client)
    monkeypatch.setattr(
        validator.importlib.metadata, "version", lambda name: "synthetic"
    )
    config = tmp_path / "config.txt"
    config.write_text("synthetic")
    args = SimpleNamespace(
        app_config=config,
        scenario="lifecycle",
        host="unused",
        port=1,
        app_info="synthetic",
        market="33",
        sdk_revision="test",
        wheel_sha256="test",
        image_ref=None,
        budget=tmp_path / "budget.json",
        report=tmp_path / "report.json",
    )
    status = validator.execute(
        args,
        sleep=lambda n: clock.__setitem__(0, clock[0] + n),
        monotonic=lambda: clock[0],
    )
    text = args.report.read_text(encoding="utf-8")
    report = json.loads(text)
    assert "private-session-sentinel" not in text
    assert all(c.closed and c._session is None for c in clients)
    if failure is ThsProtocolError:
        assert status == 1 and not report["complete"]
        assert calls == [0, 10, 20, 300]
    else:
        assert status == 0 and report["complete"]
        assert calls == (
            [0, 10, 20, 300, 300, 900, 1800, 1800]
            if failure
            else [0, 10, 20, 300, 900, 1800, 1800]
        )
        assert report["events"][1]["session_reused"]
