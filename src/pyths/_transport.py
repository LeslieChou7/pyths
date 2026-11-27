"""同步TCP收发；调用方管理会话、重试与绝对截止时间。"""

import math
import socket
import time
from collections import deque

from ._framing import FrameDecoder, encode_frame
from ._resolve import resolve
from .errors import ThsNetworkError


class TcpTransport:
    """单连接、单调用者传输；构造不联网。"""

    def __init__(self, *, max_frame_size: int = 1024 * 1024) -> None:
        self._limit = max_frame_size
        self._decoder = FrameDecoder(max_frame_size=max_frame_size)
        self._socket: socket.socket | None = None
        self._pending: deque[bytes] = deque()

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ThsNetworkError("transport: operation timed out")
        return remaining

    def connect(
        self, endpoint: tuple[str, int], *, deadline: float, connect_timeout: float
    ) -> None:
        """解析和连接共用有界预算；所有候选使用同一连接截止时间。"""
        self.close()
        if not math.isfinite(connect_timeout) or connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive and finite")
        if not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        try:
            connection_deadline = min(deadline, time.monotonic() + connect_timeout)
            host, port = endpoint
            for family, address in resolve(host, port, deadline=connection_deadline):
                candidate = socket.socket(family, socket.SOCK_STREAM)
                try:
                    candidate.settimeout(self._remaining(connection_deadline))
                    candidate.connect((address, port))
                    self._remaining(connection_deadline)
                except (OSError, ThsNetworkError):
                    candidate.close()
                    continue
                self._socket = candidate
                return
            raise ThsNetworkError("transport: no reachable address")
        except (OSError, ThsNetworkError):
            self.close()
            raise ThsNetworkError("transport: connection failed or timed out") from None

    def send(self, payload: bytes, *, deadline: float) -> None:
        """发送完整外层帧，不自行重试。"""
        packet = encode_frame(payload, max_frame_size=self._limit)
        try:
            connection = self._connection()
            connection.settimeout(self._remaining(deadline))
            connection.sendall(packet)
        except (OSError, ThsNetworkError):
            self.close()
            raise ThsNetworkError("transport: send failed or timed out") from None

    def receive(self, *, deadline: float) -> bytes:
        """增量读取一帧；粘连的完整帧留待下一次读取。"""
        try:
            connection = self._connection()
            self._remaining(deadline)
            while not self._pending:
                connection.settimeout(self._remaining(deadline))
                data = connection.recv(65536)
                if not data:
                    self._decoder.finish()
                    raise ThsNetworkError("transport: peer closed connection")
                self._pending.extend(self._decoder.feed(data))
            self._remaining(deadline)
            return self._pending.popleft()
        except OSError:
            self.close()
            raise ThsNetworkError("transport: receive failed or timed out") from None
        except Exception:
            self.close()
            raise

    def _connection(self) -> socket.socket:
        if self._socket is None:
            raise ThsNetworkError("transport: not connected")
        return self._socket

    def close(self) -> None:
        """幂等释放连接并丢弃旧流状态。"""
        connection, self._socket = self._socket, None
        if connection is not None:
            connection.close()
        self._pending.clear()
        self._decoder = FrameDecoder(max_frame_size=self._limit)
