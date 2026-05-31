"""`.user.3` 解析与封包共享的基础设施。

这里放置不依赖具体导出器/封包器的通用能力：magic 默认值、二进制读取、
字段与类型定义、RE_RSZ 模板加载、字符串/GUID 规范化等。
"""

from __future__ import annotations

import re
import struct
import uuid
from pathlib import Path
from typing import Any

from .schema import ClassDef, FieldDef, TypeDB, murmur3_32


USR_MAGIC = 5395285
RSZ_MAGIC = 5919570
PACK_JSON_FORMAT = "re_user3_pack_v1"
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
ENUM_UNUSED_KEY = "value__"


class ParseError(RuntimeError):
    """解析或封包过程中发现二进制结构不符合预期时抛出的异常。"""

    pass


def align(value: int, alignment: int) -> int:
    """把整数偏移对齐到指定边界。

    参数：
        value: 当前偏移。
        alignment: 对齐粒度；小于等于 1 时不做处理。

    返回：
        对齐后的偏移。
    """
    if alignment <= 1:
        return value
    return (value + (alignment - 1)) & ~(alignment - 1)


def format_guid_text_from_hex32(hex32: str) -> str:
    """把 32 位十六进制文本格式化为标准 GUID 文本。

    参数：
        hex32: 不带分隔符的 32 位十六进制字符串。

    返回：
        形如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 的 GUID。
    """
    h = hex32.lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def normalize_guid_candidate_text(text: str) -> str:
    """在字符串看起来像 GUID 时进行规范化。

    参数：
        text: 原始字符串，可能包含 `{}` 或 `-`。

    返回：
        可识别时返回标准 GUID，否则返回原字符串。
    """
    stripped = text.strip().strip("{}")
    compact = stripped.replace("-", "")
    if HEX32_RE.fullmatch(compact):
        return format_guid_text_from_hex32(compact)
    return text


def resolve_schema_path(schema_path_or_dir: str | Path) -> Path:
    """校验并返回用户显式提供的 RE_RSZ 模板文件路径。

    新逻辑要求依赖文件全部显式传入，因此这里故意拒绝目录路径，
    避免在多个游戏模板共存时自动匹配到错误文件。
    """
    path = Path(schema_path_or_dir)
    if path.is_file():
        return path
    if path.is_dir():
        raise FileNotFoundError(
            f"schema must be an explicit RE RSZ json file, not a directory: {path}"
        )
    raise FileNotFoundError(f"schema file not found: {path}")


class BinaryReader:
    """带边界检查的小端二进制读取器。"""

    def __init__(self, data: bytes):
        """初始化读取器。

        参数：
            data: 源字节缓冲区。
        """
        self.data = data
        self.pos = 0

    @property
    def size(self) -> int:
        """返回缓冲区总长度。"""

        return len(self.data)

    def tell(self) -> int:
        """返回当前读取游标。"""

        return self.pos

    def seek(self, pos: int) -> None:
        """把游标移动到绝对偏移。

        参数：
            pos: 目标绝对偏移。
        """
        if pos < 0 or pos > self.size:
            raise ParseError(f"seek out of range: {pos}")
        self.pos = pos

    def read(self, n: int) -> bytes:
        """读取指定长度的字节并推进游标。

        参数：
            n: 要读取的字节数。

        返回：
            读取出的字节。
        """
        end = self.pos + n
        if end > self.size:
            raise ParseError(f"read out of range: {self.pos}+{n}")
        out = self.data[self.pos : end]
        self.pos = end
        return out

    def read_struct(self, fmt: str) -> Any:
        """按 `struct` 格式读取并解包一个值。

        参数：
            fmt: `struct.unpack` 使用的格式字符串。

        返回：
            解包后的单个值。
        """
        size = struct.calcsize(fmt)
        raw = self.read(size)
        return struct.unpack(fmt, raw)[0]

    def read_u8(self) -> int:
        """读取无符号 8 位整数。"""
        return self.read_struct("<B")

    def read_s8(self) -> int:
        """读取有符号 8 位整数。"""
        return self.read_struct("<b")

    def read_u16(self) -> int:
        """读取无符号 16 位整数。"""
        return self.read_struct("<H")

    def read_s16(self) -> int:
        """读取有符号 16 位整数。"""
        return self.read_struct("<h")

    def read_u32(self) -> int:
        """读取无符号 32 位整数。"""
        return self.read_struct("<I")

    def read_s32(self) -> int:
        """读取有符号 32 位整数。"""
        return self.read_struct("<i")

    def read_u64(self) -> int:
        """读取无符号 64 位整数。"""
        return self.read_struct("<Q")

    def read_s64(self) -> int:
        """读取有符号 64 位整数。"""
        return self.read_struct("<q")

    def read_f32(self) -> float:
        """读取 32 位浮点数。"""
        return self.read_struct("<f")

    def read_f64(self) -> float:
        """读取 64 位浮点数。"""
        return self.read_struct("<d")

    def read_wstring_null(self, offset: int) -> str:
        """从绝对偏移读取以空字符结尾的 UTF-16 字符串。

        参数：
            offset: 字符串起始的绝对偏移。

        返回：
            解码后的字符串；越界时返回空字符串。
        """
        if offset < 0 or offset >= self.size:
            return ""
        out: list[int] = []
        i = offset
        # RE Engine 路径表常以 UTF-16LE 存储，并由 0 结束。
        while i + 1 < self.size:
            ch = struct.unpack_from("<H", self.data, i)[0]
            i += 2
            if ch == 0:
                break
            out.append(ch)
        return normalize_guid_candidate_text("".join(chr(c) for c in out))





def read_len_utf16(reader: BinaryReader) -> str:
    """读取带长度前缀的 UTF-16LE 字符串。

    参数：
        reader: 二进制读取器。

    返回：
        解码并去掉结尾空字符后的字符串。
    """
    # 字符串前的长度字段按 4 字节对齐。
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining_chars = (reader.size - reader.tell()) // 2
    # 长度异常时返回空字符串，而不是继续越界读取破坏后续解析。
    if length > remaining_chars or length > 2_000_000:
        return ""
    raw = reader.read(length * 2)
    decoded = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_len_c8(reader: BinaryReader) -> str:
    """读取带长度前缀的 UTF-8/C8 字符串。

    参数：
        reader: 二进制读取器。

    返回：
        解码并去掉结尾空字符后的字符串。
    """
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining = reader.size - reader.tell()
    if length > remaining or length > 2_000_000:
        return ""
    raw = reader.read(length)
    decoded = raw.decode("utf-8", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_guid_like(reader: BinaryReader) -> str:
    """读取 16 字节 GUID 数据并规范化文本。

    参数：
        reader: 二进制读取器。

    返回：
        标准 GUID 文本；无法按 UUID 解析时退回十六进制格式化。
    """
    raw = reader.read(16)
    try:
        return str(uuid.UUID(bytes_le=raw))
    except Exception:
        return format_guid_text_from_hex32(raw.hex())

