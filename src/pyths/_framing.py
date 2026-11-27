"""基于目标Socket接收代码的有界离线分帧；发送头规则尚未验证。"""

from .errors import ThsProtocolError


def encode_frame(payload: bytes, *, max_frame_size: int = 1024 * 1024) -> bytes:
    """编码本次native输出已验证的FD封装；不改变内部负载。"""
    if type(max_frame_size) is not int or max_frame_size <= 0:
        raise ValueError("max_frame_size must be positive")
    if not 0 < len(payload) <= min(max_frame_size, 0xFFFFFFFF):
        raise ThsProtocolError("frame: length exceeds bounds")
    return b"\xfd" * 4 + f"{len(payload):08x}".encode("ascii") + b"\x00" + payload


class FrameDecoder:
    """严格解析13字节接收头；合法空封装不生成应用帧，不扫描畸形数据。"""

    def __init__(self, *, max_frame_size: int = 1024 * 1024) -> None:
        if type(max_frame_size) is not int or max_frame_size <= 0:
            raise ValueError("max_frame_size must be positive")
        self._limit = max_frame_size
        self._buffer = bytearray()
        self._length: int | None = None
        self._failed = False
        self._empty_frames = 0

    @property
    def empty_frame_count(self) -> int:
        """本解码器消费的合法空封装数量；不包含业务帧。"""
        return self._empty_frames

    def feed(self, data: bytes) -> tuple[bytes, ...]:
        """输入任意分段；输出本次完整帧，错误后不可复用。"""
        if self._failed:
            raise ThsProtocolError("frame: decoder failed")
        frames = []
        position = 0
        try:
            while position < len(data):
                target = 13 if self._length is None else self._length
                size = min(target - len(self._buffer), len(data) - position)
                self._buffer.extend(data[position : position + size])
                position += size
                if len(self._buffer) < target:
                    continue
                if self._length is None:
                    header = bytes(self._buffer)
                    if header[:4] != b"\xfd" * 4 or header[12] != 0:
                        raise ThsProtocolError("frame: invalid header")
                    digits = header[4:12]
                    if any(char not in b"0123456789abcdefABCDEF" for char in digits):
                        raise ThsProtocolError("frame: invalid length encoding")
                    length = int(digits, 16)
                    if length > self._limit:
                        raise ThsProtocolError("frame: length exceeds bounds")
                    if length == 0:
                        self._empty_frames += 1
                        self._buffer.clear()
                        continue
                    self._length = length
                    self._buffer.clear()
                else:
                    frames.append(bytes(self._buffer))
                    self._buffer.clear()
                    self._length = None
        except ThsProtocolError:
            self._failed = True
            self._buffer.clear()
            raise
        return tuple(frames)

    def finish(self) -> None:
        """流结束时拒绝残留头或残留负载。"""
        if self._failed or self._buffer or self._length is not None:
            self._failed = True
            self._buffer.clear()
            raise ThsProtocolError("frame: incomplete or failed stream")
