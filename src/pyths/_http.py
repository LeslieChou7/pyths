"""显式 HTTP 请求；独立进程将解析、TLS 和收发限制在同一截止时间内。"""

import base64
import http.client
import json
import math
import re
import ssl
import struct
import subprocess
import sys
import time
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .errors import (
    ThsAuthenticationError,
    ThsBusinessError,
    ThsNetworkError,
    ThsProtocolError,
    ThsRateLimitError,
)

MAX_BODY = 4 * 1024 * 1024
_MAX_META = 8192
_RESPONSE_HEADERS = frozenset({"content-type", "date", "retry-after"})
_WORKER = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from pyths._http import _worker_main; _worker_main()"
)


@dataclass(frozen=True)
class HttpResponse:
    """有界正文和白名单响应头；正文不会进入默认表示或异常。"""

    status: int
    body: bytes = field(repr=False)
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)


def request(
    url: str,
    *,
    deadline: float,
    connect_timeout: float = 5,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    expected_json: bool = False,
) -> HttpResponse:
    """发送一次显式 GET/POST，不跟随重定向或重试；只读性由业务层确认。"""
    supplied = dict(headers or {})
    _validate(url, method, supplied, body, deadline, connect_timeout, expected_json)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ThsNetworkError("http: deadline exceeded")
    payload = json.dumps(
        {
            "url": url,
            "method": method,
            "headers": supplied,
            "body": None if body is None else base64.b64encode(body).decode("ascii"),
            "deadline": deadline,
            "connect_timeout": connect_timeout,
            "expected_json": expected_json,
        },
        ensure_ascii=True,
    ).encode("ascii")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ThsNetworkError("http: deadline exceeded")
    try:
        # stdin keeps URLs and credentials out of command arguments. subprocess.run
        # kills and waits for the worker on TimeoutExpired, including DNS/TLS stalls.
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                _WORKER,
                str(Path(__file__).resolve().parents[1]),
            ],
            input=payload,
            capture_output=True,
            check=False,
            timeout=remaining,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        raise ThsNetworkError("http: request failed or timed out") from None
    if time.monotonic() >= deadline:
        raise ThsNetworkError("http: deadline exceeded")
    errors = {
        10: ThsNetworkError,
        11: ThsProtocolError,
        12: ThsAuthenticationError,
        13: ThsRateLimitError,
        14: ThsBusinessError,
    }
    if result.returncode:
        error = errors.get(result.returncode, ThsNetworkError)
        raise error("http: request rejected or failed")
    try:
        data = result.stdout
        if not 4 <= len(data) <= MAX_BODY + _MAX_META + 4:
            raise ValueError
        length = struct.unpack(">I", data[:4])[0]
        if not 0 < length <= _MAX_META or len(data) < 4 + length:
            raise ValueError
        metadata = json.loads(data[4 : 4 + length])
        if (
            not isinstance(metadata, list)
            or len(metadata) != 2
            or type(metadata[0]) is not int
            or not 200 <= metadata[0] < 300
            or not isinstance(metadata[1], list)
        ):
            raise ValueError
        safe_headers = []
        for row in metadata[1]:
            if (
                not isinstance(row, list)
                or len(row) != 2
                or row[0] not in _RESPONSE_HEADERS
                or not isinstance(row[1], str)
                or len(row[1]) > 2048
            ):
                raise ValueError
            safe_headers.append((row[0], row[1]))
        content = data[4 + length :]
        if len(content) > MAX_BODY:
            raise ValueError
        return HttpResponse(metadata[0], content, tuple(safe_headers))
    except (ValueError, TypeError, KeyError, struct.error):
        raise ThsProtocolError("http: invalid worker response") from None


def _validate(
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    deadline: float,
    connect_timeout: float,
    expected_json: bool = False,
) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
        if (
            type(expected_json) is not bool
            or not isinstance(url, str)
            or len(url) > 8192
            or any(ord(char) < 33 or ord(char) == 127 for char in url)
            or parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
            or method not in ("GET", "POST")
            or len(headers) > 64
            or (
                body is not None
                and (not isinstance(body, bytes) or len(body) > MAX_BODY)
            )
            or not math.isfinite(deadline)
            or not math.isfinite(connect_timeout)
            or connect_timeout <= 0
        ):
            raise ValueError
        normalized = set()
        for key, value in headers.items():
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}", key)
                or key.lower() in normalized
                or key.lower()
                in {"host", "content-length", "transfer-encoding", "connection"}
                or not isinstance(value, str)
                or len(value) > 8192
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError
            value.encode("latin-1")
            normalized.add(key.lower())
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise ValueError("invalid HTTP request configuration") from None


def _exchange(config: dict[str, object]) -> HttpResponse:
    """仅由隔离工作进程调用；所有原始异常留在进程内。"""
    url = str(config["url"])
    method = str(config["method"])
    raw_headers = config["headers"]
    if not isinstance(raw_headers, dict):
        raise TypeError
    headers = {str(key): str(value) for key, value in raw_headers.items()}
    encoded_body = config["body"]
    body = (
        None
        if encoded_body is None
        else base64.b64decode(str(encoded_body), validate=True)
    )
    deadline = float(str(config["deadline"]))
    connect_timeout = float(str(config["connect_timeout"]))
    expected_json = config.get("expected_json", False)
    if type(expected_json) is not bool:
        raise ValueError("invalid HTTP response expectation")
    _validate(url, method, headers, body, deadline, connect_timeout, expected_json)
    if time.monotonic() >= deadline:
        raise TimeoutError
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise ValueError
    timeout = min(connect_timeout, max(0.001, deadline - time.monotonic()))
    connection: http.client.HTTPConnection
    if parsed.scheme == "https":
        connection = http.client.HTTPSConnection(
            host, parsed.port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        connection = http.client.HTTPConnection(host, parsed.port, timeout=timeout)
    try:
        connection.connect()
        if time.monotonic() >= deadline:
            raise TimeoutError
        if connection.sock is not None:
            connection.sock.settimeout(max(0.001, deadline - time.monotonic()))
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()
        if response.status in (401, 403):
            raise ThsAuthenticationError
        if response.status == 429:
            raise ThsRateLimitError
        if 300 <= response.status < 400:
            raise ThsProtocolError
        if not 200 <= response.status < 300:
            raise ThsBusinessError
        if expected_json:
            content_types = response.headers.get_all("Content-Type", [])
            if len(content_types) != 1:
                raise ThsProtocolError
            media_type = content_types[0].split(";", 1)[0].strip().lower()
            if media_type != "application/json" and not re.fullmatch(
                r"application/[a-z0-9!#$&^_.+-]+\+json", media_type
            ):
                raise ThsProtocolError
        lengths = response.headers.get_all("Content-Length", [])
        transfers = response.headers.get_all("Transfer-Encoding", [])
        if transfers and (
            len(transfers) != 1 or transfers[0].strip().lower() != "chunked"
        ):
            raise ThsProtocolError
        if lengths and (
            len(lengths) != 1
            or not re.fullmatch(r"[0-9]+", lengths[0])
            or int(lengths[0]) > MAX_BODY
            or response.headers.get("Transfer-Encoding") is not None
        ):
            raise ThsProtocolError
        encoding = response.getheader("Content-Encoding", "identity").strip().lower()
        if encoding not in ("identity", "gzip", "deflate"):
            raise ThsProtocolError
        decoder = (
            None
            if encoding == "identity"
            else zlib.decompressobj(
                16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS
            )
        )
        raw_size = 0
        chunks = []
        size = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError
            if connection.sock is not None:
                connection.sock.settimeout(max(0.001, deadline - time.monotonic()))
            chunk = response.read(65536)
            if not chunk:
                break
            raw_size += len(chunk)
            if raw_size > MAX_BODY:
                raise ThsProtocolError
            decoded = (
                chunk
                if decoder is None
                else decoder.decompress(chunk, MAX_BODY + 1 - size)
            )
            size += len(decoded)
            if size > MAX_BODY or (decoder is not None and decoder.unconsumed_tail):
                raise ThsProtocolError
            chunks.append(decoded)
        if lengths and raw_size != int(lengths[0]):
            raise ThsProtocolError
        if decoder is not None and (not decoder.eof or decoder.unused_data):
            raise ThsProtocolError
        safe_headers = tuple(
            (key.lower(), value)
            for key, value in response.getheaders()
            if key.lower() in _RESPONSE_HEADERS
        )
        metadata = json.dumps([response.status, safe_headers]).encode("utf-8")
        if len(metadata) > _MAX_META or any(
            len(value) > 2048 for _, value in safe_headers
        ):
            raise ThsProtocolError
        return HttpResponse(response.status, b"".join(chunks), safe_headers)
    finally:
        connection.close()


def _worker_main() -> None:
    try:
        config = json.loads(sys.stdin.buffer.read(2 * MAX_BODY + 65536))
        result = _exchange(config)
        metadata = json.dumps([result.status, result.headers]).encode("utf-8")
        sys.stdout.buffer.write(
            struct.pack(">I", len(metadata)) + metadata + result.body
        )
        sys.stdout.buffer.flush()
    except ThsAuthenticationError:
        raise SystemExit(12) from None
    except ThsRateLimitError:
        raise SystemExit(13) from None
    except ThsBusinessError:
        raise SystemExit(14) from None
    except OSError:
        # SSLCertVerificationError also inherits ValueError; preserve the network
        # classification before the malformed-payload branch below.
        raise SystemExit(10) from None
    except (
        ThsProtocolError,
        ValueError,
        TypeError,
        KeyError,
        zlib.error,
        http.client.HTTPException,
    ):
        raise SystemExit(11) from None
    except Exception:  # noqa: BLE001 -- no raw diagnostic may escape this process
        raise SystemExit(10) from None
