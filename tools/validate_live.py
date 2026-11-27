"""已安装 wheel 的显式、有界真实验证；只记录公开行情和结构摘要。"""

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import platform
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pyths
from pyths import ThsError, ThsNetworkError, ths
from pyths._headers import decode_response_header
from pyths._quote import QUOTE_MARKETS
from pyths._transport import TcpTransport

FIELDS = (
    "latest",
    "change",
    "change_rate",
    "open",
    "high",
    "low",
    "previous_close",
    "volume",
    "turnover",
)
FRAME_ERRORS = {
    "frame: invalid header": "invalid_envelope_header",
    "frame: invalid length encoding": "invalid_envelope_length_encoding",
    "frame: length exceeds bounds": "envelope_length_exceeds_bounds",
    "frame: incomplete or failed stream": "incomplete_envelope_at_eof",
    "frame: decoder failed": "decoder_already_failed",
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def reserve_call(path, *, limit=12):
    """在跨进程共享的本地账本中预扣调用；失败调用也消耗预算。"""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("explicit business call limit must be 1..20")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    until = time.monotonic() + 5
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= until:
                raise RuntimeError("budget ledger is locked") from None
            time.sleep(0.05)
    try:
        value = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"calls": 0}
        )
        count = value.get("calls")
        if type(count) is not int or not 0 <= count < limit:
            raise RuntimeError("business call budget exhausted or invalid")
        write_json(
            path, {"calls": count + 1, "limit": max(value.get("limit", limit), limit)}
        )
        return count + 1
    finally:
        lock.rmdir()


@contextmanager
def observe_transport(stats):
    """仅此独立验证进程替换内部传输；不改变公开 API 或收发字节。"""
    module = importlib.import_module("pyths.client")
    original = module.TcpTransport

    class ObservedTransport(TcpTransport):
        def connect(self, endpoint, *, deadline, connect_timeout):
            stats["connect_attempts"] += 1
            super().connect(
                endpoint, deadline=deadline, connect_timeout=connect_timeout
            )
            stats["connections"] += 1

        def send(self, packet, *, deadline):
            flags = int.from_bytes(packet[6:10], "little", signed=True)
            frame_id = int.from_bytes(packet[16:20], "little", signed=True)
            # encode_session_request的线上头frame为0；100是App发送入口参数，不是线上头。
            if flags == 0x70000:
                stats["handshakes"] += 1
            elif flags == 0x01060000:
                stats["stops"] += 1
            elif frame_id == 2267:
                stats["queries"] += 1
            stats["sent_headers"].append(
                {
                    "flags": flags,
                    "frame_id": frame_id,
                    "package_id": int.from_bytes(packet[2:6], "little", signed=True),
                }
            )
            super().send(packet, deadline=deadline)

        def receive(self, *, deadline):
            decoder = self._decoder
            before = decoder.empty_frame_count
            try:
                packet = super().receive(deadline=deadline)
            except ThsError as error:
                stats["receive_errors"].append(
                    {
                        "error_type": type(error).__name__,
                        "safe_code": FRAME_ERRORS.get(str(error), "other"),
                    }
                )
                raise
            finally:
                stats["empty_envelopes"] += decoder.empty_frame_count - before
            header = decode_response_header(packet)
            stats["responses"].append(
                {
                    "length": len(packet),
                    "header_length": header.length,
                    "flags": header.flags,
                    "package_id": header.package_id,
                    "frame_id": header.frame_id,
                    "instance_id": header.instance_id,
                }
            )
            return packet

        def close(self):
            stats["close_calls"] += 1
            super().close()

    module.TcpTransport = ObservedTransport
    try:
        yield
    finally:
        module.TcpTransport = original


def execute(args, *, sleep=time.sleep, monotonic=time.monotonic):
    config_bytes = args.app_config.read_bytes()
    report = {
        "run_id": args.report.stem,
        "scenario": args.scenario,
        "started_at": datetime.now(UTC).isoformat(),
        "environment": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "package_version": importlib.metadata.version("pyths"),
        "sdk_revision": args.sdk_revision,
        "wheel_sha256": args.wheel_sha256,
        "image_ref": args.image_ref,
        "business_call_limit": getattr(args, "max_calls", 12),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "installed_package": str(Path(pyths.__file__).resolve()),
        "stats": {
            "connect_attempts": 0,
            "connections": 0,
            "handshakes": 0,
            "queries": 0,
            "stops": 0,
            "empty_envelopes": 0,
            "receive_errors": [],
            "close_calls": 0,
            "sent_headers": [],
            "responses": [],
        },
        "events": [],
        "complete": False,
    }
    start = monotonic()
    client = None

    def save():
        write_json(args.report, report)

    def query(code, label):
        number = reserve_call(args.budget, limit=getattr(args, "max_calls", 12))
        began = monotonic()
        prior = client._session
        event = {
            "label": label,
            "budget_call": number,
            "stock_code": code,
            "market": args.market,
            "started_at": datetime.now(UTC).isoformat(),
            "elapsed_from_start": round(began - start, 3),
        }
        error = None
        try:
            quote = client.get_quote(code, market=args.market)
            if (quote.stock_code, quote.market) != (code, args.market):
                raise RuntimeError("unexpected security identity")
            event["fields"] = {
                name: asdict(value)
                if (value := getattr(quote, name)) is not None
                else None
                for name in FIELDS
            }
            event["received_at"] = quote.received_at.isoformat()
            event["session_reused"] = prior is not None and prior is client._session
            event["success"] = True
        except (ThsError, ValueError, RuntimeError) as exc:
            error = exc
            event["success"] = False
            event["error_type"] = type(exc).__name__
            event["session_cleared"] = client._session is None
        event["duration_seconds"] = round(monotonic() - began, 3)
        event["connections"] = report["stats"]["connections"]
        event["handshakes"] = report["stats"]["handshakes"]
        report["events"].append(event)
        save()
        print(
            json.dumps(
                {"label": label, "success": event["success"], "budget_call": number},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return error

    def new_client():
        return ths(
            endpoint=(args.host, args.port),
            app_config=config_bytes.decode("utf-8"),
            app_info=args.app_info,
            connect_timeout=5,
            request_timeout=15,
            retries=0,
        )

    save()
    with observe_transport(report["stats"]):
        try:
            client = new_client()
            if args.scenario == "quotes":
                for code in args.codes:
                    error = query(code, "comparison")
                    if error:
                        raise error
            else:
                recovered = False
                for offset in (0, 10, 20, 300, 900, 1800):
                    while (remaining := start + offset - monotonic()) > 0:
                        sleep(min(5, remaining))
                    error = query("000001", f"at_{offset}s")
                    if isinstance(error, ThsNetworkError) and not recovered:
                        recovered = True
                        error = query("000001", f"recovery_after_{offset}s")
                    if error:
                        raise error
                client.close()
                report["first_client_closed"] = (
                    client.closed and client._session is None
                )
                client = new_client()
                error = query("000001", "fresh_client")
                if error:
                    raise error
            report["complete"] = True
        except (ThsError, ValueError, RuntimeError) as exc:
            report["error_type"] = type(exc).__name__
        finally:
            if client is not None:
                client.close()
                report["closed"] = client.closed and client._session is None
            report["finished_at"] = datetime.now(UTC).isoformat()
            report["duration_seconds"] = round(monotonic() - start, 3)
            save()
    return 0 if report["complete"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--scenario", choices=("quotes", "lifecycle"), required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--app-config", required=True, type=Path)
    parser.add_argument("--app-info", required=True)
    parser.add_argument("--codes", nargs="+", default=["000001"])
    parser.add_argument("--market", choices=QUOTE_MARKETS, default="33")
    parser.add_argument("--sdk-revision", required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--image-ref", default=None)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--max-calls", type=int, choices=range(1, 21), default=12)
    args = parser.parse_args()
    if not args.live:
        parser.error("explicit --live required")
    if not sys.flags.isolated or "site-packages" not in Path(pyths.__file__).parts:
        parser.error("run installed wheel with python -I outside the source tree")
    if args.scenario == "lifecycle" and args.market != "33":
        parser.error("lifecycle uses the fixed security 000001/33")
    if any(
        len(code) != 6 or not code.isascii() or not code.isdigit()
        for code in args.codes
    ):
        parser.error("stock codes must be six ASCII digits")
    if args.report.exists():
        parser.error("report already exists; choose a new run id")
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
