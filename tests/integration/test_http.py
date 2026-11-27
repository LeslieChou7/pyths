"""合成本地 HTTP 替身；不提供生产协议兼容证据。"""

import gzip
import ssl
import subprocess
import threading
import time
import zlib
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pyths._http import MAX_BODY, request
from pyths.errors import (
    ThsAuthenticationError,
    ThsBusinessError,
    ThsNetworkError,
    ThsProtocolError,
    ThsRateLimitError,
)


@contextmanager
def server(
    *,
    status=200,
    body=b"public body",
    headers=(),
    stall=False,
    drip=False,
    body_drip=False,
    length=True,
    tls_context=None,
):
    observed = []
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append(
                (self.command, self.path, self.headers.get("Authorization"))
            )
            if stall:
                finished.wait(5)
                return
            if drip:
                try:
                    self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    while not finished.wait(0.02):
                        self.connection.sendall(b"x")
                except OSError:
                    pass
                return
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            if length and not any(
                key.lower() == "content-length" for key, _ in headers
            ):
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if body_drip:
                    while not finished.wait(0.02):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    return
                self.wfile.write(body)
            except OSError:
                pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            observed.append(self.rfile.read(length))
            self.do_GET()

        def log_message(self, *args):
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls_context is not None:
        instance.socket = tls_context.wrap_socket(instance.socket, server_side=True)
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    try:
        scheme = "https" if tls_context is not None else "http"
        yield f"{scheme}://127.0.0.1:{instance.server_port}", observed
    finally:
        finished.set()
        instance.shutdown()
        instance.server_close()
        worker.join(2)
        assert not worker.is_alive()


def test_success_is_explicit_and_credentials_are_not_in_repr():
    with server(
        headers=(("Content-Type", "application/json"), ("Set-Cookie", "secret"))
    ) as (url, seen):
        result = request(
            url + "/read?token=secret-query",
            headers={"Authorization": "secret-header"},
            deadline=time.monotonic() + 3,
        )
    assert result.status == 200
    assert result.body == b"public body"
    assert ("content-type", "application/json") in result.headers
    assert not any(key == "set-cookie" for key, _ in result.headers)
    assert seen == [("GET", "/read?token=secret-query", "secret-header")]
    assert "public body" not in repr(result)
    assert "secret" not in repr(result)


@pytest.mark.parametrize(
    "media_type", ["application/json", "application/problem+json; charset=utf-8"]
)
def test_explicit_json_expectation_accepts_json_media_types(media_type):
    with server(body=b"{}", headers=(("Content-Type", media_type),)) as (url, _):
        result = request(url, expected_json=True, deadline=time.monotonic() + 3)
    assert result.body == b"{}"


def test_json_expectation_rejects_html_before_waiting_for_a_body():
    # The body never ends. Reading it would hit the deadline as a network failure.
    with (
        server(headers=(("Content-Type", "text/html"),), body_drip=True) as (url, _),
        pytest.raises(ThsProtocolError),
    ):
        request(url, expected_json=True, deadline=time.monotonic() + 3)


def test_json_expectation_type_is_checked_before_worker(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("worker started")
    )
    with pytest.raises(ValueError):
        request(
            "https://example.invalid", expected_json=1, deadline=time.monotonic() + 3
        )  # type: ignore[arg-type]


def test_explicit_post_preserves_bytes():
    with server() as (url, seen):
        result = request(
            url, method="POST", body=b"\x00public\xff", deadline=time.monotonic() + 3
        )
    assert result.status == 200
    assert seen[0] == b"\x00public\xff"
    assert seen[1][0] == "POST"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ThsAuthenticationError),
        (403, ThsAuthenticationError),
        (429, ThsRateLimitError),
        (500, ThsBusinessError),
        (404, ThsBusinessError),
    ],
)
def test_status_mapping_is_sanitized(status, error):
    with (
        server(status=status, body=b"secret-response") as (url, seen),
        pytest.raises(error) as failure,
    ):
        request(url + "/?secret-query", deadline=time.monotonic() + 3)
    assert len(seen) == 1
    assert "secret" not in str(failure.value)


def test_redirect_does_not_send_credentials_to_another_origin():
    with server() as (target, target_seen):
        with (
            server(status=302, headers=(("Location", target),)) as (url, seen),
            pytest.raises(ThsProtocolError),
        ):
            request(
                url,
                headers={"Authorization": "secret-header"},
                deadline=time.monotonic() + 3,
            )
        assert len(seen) == 1
        assert target_seen == []


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_compressed_body(encoding):
    original = b"synthetic public body" * 300
    compressed = (
        gzip.compress(original) if encoding == "gzip" else zlib.compress(original)
    )
    with server(body=compressed, headers=(("Content-Encoding", encoding),)) as (url, _):
        result = request(url, deadline=time.monotonic() + 3)
    assert result.body == original


@pytest.mark.parametrize(
    "compressed, length", [(False, True), (False, False), (True, True)]
)
def test_wire_and_decompressed_limits(compressed, length):
    body = b"x" * (MAX_BODY + 1)
    headers = ()
    if compressed:
        body = gzip.compress(body)
        headers = (("Content-Encoding", "gzip"),)
    with (
        server(body=body, headers=headers, length=length) as (url, _),
        pytest.raises(ThsProtocolError),
    ):
        request(url, deadline=time.monotonic() + 3)


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"invalid gzip", (("Content-Encoding", "gzip"),)),
        (gzip.compress(b"public")[:-2], (("Content-Encoding", "gzip"),)),
        (gzip.compress(b"public") + b"trailing", (("Content-Encoding", "gzip"),)),
        (b"public", (("Content-Encoding", "unknown"),)),
        (b"public", (("Content-Length", "100"),)),
        (b"public", (("Content-Length", "-1"),)),
        (b"public", (("Content-Length", "6"), ("Content-Length", "6"))),
    ],
)
def test_malformed_responses_fail(body, headers):
    with (
        server(body=body, headers=headers) as (url, _),
        pytest.raises(ThsProtocolError),
    ):
        request(url, deadline=time.monotonic() + 3)


@pytest.mark.parametrize("scenario", ["stall", "header_drip", "body_drip"])
def test_deadline_kills_and_reaps_worker(monkeypatch, scenario):
    processes = []
    original = subprocess.Popen

    def tracked(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", tracked)
    with server(
        stall=scenario == "stall",
        drip=scenario == "header_drip",
        body_drip=scenario == "body_drip",
        length=False,
    ) as (url, _):
        started = time.monotonic()
        with pytest.raises(ThsNetworkError):
            request(url, connect_timeout=3, deadline=started + 0.5)
        assert time.monotonic() - started < 1.5
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert processes[0].returncode != 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"url": "https://user:password@example.invalid"},
        {"url": "https://example.invalid/#fragment"},
        {"url": "ftp://example.invalid"},
        {"url": "https://example.invalid/\r\nheader"},
        {"headers": {"Authorization": "secret\r\nInjected: yes"}},
        {"headers": {"Host": "another-origin.invalid"}},
        {"headers": {"content-length": "0"}},
        {"method": "DELETE"},
        {"body": b"x" * (MAX_BODY + 1)},
    ],
)
def test_invalid_configuration_never_starts_worker(monkeypatch, kwargs):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("worker started")
    )
    config = {"url": "https://example.invalid", "deadline": time.monotonic() + 1}
    config.update(kwargs)
    with pytest.raises(ValueError) as failure:
        request(**config)
    assert "secret" not in str(failure.value)


def test_expired_deadline_never_starts_worker(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("worker started")
    )
    with pytest.raises(ThsNetworkError):
        request("https://example.invalid", deadline=time.monotonic() - 1)


# Generated exclusively for this synthetic localhost test; this key has no external use.
_TEST_CERTIFICATE = "-----BEGIN CERTIFICATE-----\nMIIBczCCARigAwIBAgIUEUJRJ8AZJH1cXnsW8jfn3PMXLiIwCgYIKoZIzj0EAwIw\nFDESMBAGA1UEAwwJbG9jYWxob3N0MB4XDTI2MTEwMzAxNDExMVoXDTI2MTEwNDAx\nNDExMVowFDESMBAGA1UEAwwJbG9jYWxob3N0MFkwEwYHKoZIzj0CAQYIKoZIzj0D\nAQcDQgAEWE0hGs7xRqy/52NqYtXImrRRUoet1azx1gCgkkIA9ZNeC5uEUqv5paLO\nDrhuQixH0msJp7U6IrixUHZBBaQz1KNIMEYwHQYDVR0OBBYEFFe7LjNkvauY08t5\nZqUj2rAvPpxbMA8GA1UdEwEB/wQFMAMBAf8wFAYDVR0RBA0wC4IJbG9jYWxob3N0\nMAoGCCqGSM49BAMCA0kAMEYCIQCTsuSKvRuRUXeFQAolVO9U8vX5Foeqz8zXK3Y1\nTYz3wAIhAKtV4tn4oaoNKbNYxrZNbKpc7XzHPwdr6aHWmQy9hskx\n-----END CERTIFICATE-----\n-----BEGIN PRIVATE KEY-----\nMIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgdib60rWsK1LcOLWE\nHgIoxO5ApZgTlWT2shlfXdWg2M+hRANCAARYTSEazvFGrL/nY2pi1ciatFFSh63V\nrPHWAKCSQgD1k14Lm4RSq/mlos4OuG5CLEfSawmntToiuLFQdkEFpDPU\n-----END PRIVATE KEY-----\n"


def test_https_rejects_untrusted_certificate(tmp_path):
    certificate = tmp_path / "synthetic-localhost.pem"
    certificate.write_text(_TEST_CERTIFICATE, encoding="ascii")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate)
    with server(tls_context=context) as (url, seen), pytest.raises(ThsNetworkError):
        request(url, deadline=time.monotonic() + 3)
    assert seen == []
