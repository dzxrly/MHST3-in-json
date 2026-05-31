"""封包阶段共享的数据结构与二进制写入器。"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from ..core import PACK_JSON_FORMAT, ClassDef, ParseError, align


class PackError(ParseError):
    """JSON 数据无法编码为 `.user.3` 时抛出的异常。"""


@dataclass(frozen=True)
class InstanceRef:
    """RSZ 实例表中的对象引用。"""

    index: int


@dataclass
class StructValue:
    """待写入的结构体值和声明尺寸。"""

    class_def: ClassDef
    fields: dict[str, Any]
    declared_size: int


@dataclass
class InstanceSpec:
    """封包前规划出的一个 RSZ 实例。"""

    class_hash: int
    class_def: ClassDef
    fields: dict[str, Any] = field(default_factory=dict)


class BinaryWriter:
    """带对齐辅助的小端二进制写入器。"""

    def __init__(self) -> None:
        """初始化空的字节缓冲区。"""
        self.data = bytearray()

    def tell(self) -> int:
        """返回当前写入偏移。"""
        return len(self.data)

    def write(self, raw: bytes) -> None:
        """追加原始字节。"""
        self.data.extend(raw)

    def write_struct(self, fmt: str, *values: Any) -> None:
        """按 `struct` 格式打包并写入数值。"""
        self.write(struct.pack(fmt, *values))

    def align(self, alignment: int) -> None:
        """用零字节填充到指定对齐边界。"""
        target = align(self.tell(), alignment)
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))

    def pad_to(self, target: int) -> None:
        """填充到绝对偏移，禁止回退写入。"""
        if target < self.tell():
            raise PackError(f"cannot pad backwards: {self.tell()} -> {target}")
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))
