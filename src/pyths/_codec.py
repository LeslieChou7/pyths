"""1269 已观察分支的离线正文编码；不包含应用头或会话材料。"""

import struct
from dataclasses import dataclass

from .errors import ThsProtocolError


@dataclass(frozen=True)
class TableHeader:
    """tb1.0原始头字段；计数尚未应用扩展表转置。"""

    row_count: int
    unsigned_value: int
    reserved: int
    data_offset: int
    row_width: int
    columns: tuple[tuple[int, int, int], ...]


def decode_tb1_header(data: bytes) -> TableHeader:
    """读取已确认的小端表头；不宣称已解码后续数据。"""
    if len(data) < 24 or data[:6] != b"tb1.0\x00":
        raise ThsProtocolError("table: invalid header at offset 0")
    rows, unsigned, reserved, offset, width, count = struct.unpack_from(
        "<iIiHHH", data, 6
    )
    end = 24 + count * 4
    if rows < 0 or end > len(data) or not end <= offset <= len(data):
        raise ThsProtocolError("table: invalid bounds at offset 6")
    columns = tuple(struct.unpack_from("<HBB", data, 24 + i * 4) for i in range(count))
    return TableHeader(rows, unsigned, reserved, offset, width, columns)


@dataclass(frozen=True)
class StringTable:
    """已观察的转置字符串表，保留格式字节，不反推精确数值。"""

    caption: str
    cells: tuple[tuple[int, str, int], ...]
    header: TableHeader
    extensions: tuple[tuple[int, int, bytes], ...]
    cell_offsets: tuple[int, ...]


def format_table_string(value: str, flag: int) -> str:
    """按已确认的格式高四位追加后缀；不恢复舍入前数值。"""
    suffixes = {0: "", 16: "万手", 32: "%", 48: "亿", 64: "万", 80: "万亿"}
    return value + suffixes.get(flag & 240, "")


def decode_tb1_strings(data: bytes) -> StringTable:
    """解码tb1.0单列转置字符串分支；其他布局明确拒绝。"""
    head = decode_tb1_header(data)
    if len(head.columns) != 1 or head.columns[0][0] != 0:
        raise ThsProtocolError("table: unsupported layout")
    position = 28

    def take(size: int, end: int) -> bytes:
        nonlocal position
        if size < 0 or position + size > end:
            raise ThsProtocolError("table: truncated field")
        result = data[position : position + size]
        position += size
        return result

    def ushort(end: int) -> int:
        return int.from_bytes(take(2, end), "little")

    def text(end: int) -> str:
        size = ushort(end)
        try:
            return take(size * 2, end).decode("utf-16-le")
        except UnicodeDecodeError:
            raise ThsProtocolError("table: invalid text") from None

    caption = text(head.data_offset)
    text(head.data_offset)  # 单列标题
    count = ushort(head.data_offset)
    field_ids: tuple[int, ...] | None = None
    extensions = []
    extension_keys: set[int] = set()
    for _ in range(count):
        tag = ushort(head.data_offset)
        kind, key = tag & 28672, tag & 36863
        if key in extension_keys:
            raise ThsProtocolError("table: duplicate extension")
        extension_keys.add(key)
        start = position
        if kind == 0:
            text(head.data_offset)
        elif kind == 8192:
            take(8 if key == 34068 else 4, head.data_offset)
        elif kind == 24576 and key == 32776 and field_ids is None:
            length = ushort(head.data_offset)
            raw = take(length * 4, head.data_offset)
            field_ids = tuple(value[0] for value in struct.iter_unpack("<i", raw))
        else:
            raise ThsProtocolError("table: unsupported extension")
        extensions.append((key, tag, data[start:position]))
    if field_ids is None or len(field_ids) != head.row_count:
        raise ThsProtocolError("table: invalid transpose mapping")
    if len(set(field_ids)) != len(field_ids):
        raise ThsProtocolError("table: duplicate field identifier")
    width = head.columns[0][1]
    if width % 2 or head.row_width != width + 1:
        raise ThsProtocolError("table: invalid string width")
    position = head.data_offset
    cells = []
    cell_offsets = []
    for key in field_ids:
        cell_offsets.append(position)
        try:
            value = (
                take(width, len(data))
                .decode("utf-16-le")
                .strip("".join(chr(code) for code in range(33)))
            )
        except UnicodeDecodeError:
            raise ThsProtocolError("table: invalid cell text") from None
        flag = take(1, len(data))[0]
        cells.append((key, value, flag))
    if position != len(data):
        raise ThsProtocolError("table: unexpected trailing bytes")
    return StringTable(
        caption, tuple(cells), head, tuple(extensions), tuple(cell_offsets)
    )


def encode_1269_body(
    *, stock_code: str, market: str, frame_id: int, instance_id: int
) -> bytes:
    """编码单证券正文；调用者显式提供市场及关联编号。"""
    for value in (stock_code, market):
        if (
            not isinstance(value, str)
            or not value
            or any(char in value for char in "\r\n\x00=[]")
        ):
            raise ThsProtocolError("request: invalid parameter")
    for identifier in (frame_id, instance_id):
        if type(identifier) is not int or not 0 <= identifier <= 2147483647:
            raise ThsProtocolError("request: invalid identifier")
    text = (
        f"[frame]\r\nid={frame_id}\r\npageList={instance_id}\r\n"
        f"reqPage={instance_id}\r\nreqPageCount=1\r\n[{instance_id}]\r\n"
        f"id=1269\r\nstockcode={stock_code}\r\nmarketcode={market}\r\n"
    )
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        raise ThsProtocolError("request: invalid encoding") from None
