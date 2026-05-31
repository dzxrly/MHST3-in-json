"""RE_RSZ 模板类型数据库。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def murmur3_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    """计算 RE_RSZ 类型名常用的 MurmurHash3 32 位哈希。

    Args:
        data: 输入字节。
        seed: 哈希种子，RE_RSZ 模板通常使用 `0xFFFFFFFF`。

    Returns:
        32 位无符号哈希值。
    """
    c1 = 0xCC9E2D51
    c2 = 0x1B873593
    h1 = seed & 0xFFFFFFFF
    length = len(data)
    rounded_end = length & ~0x3

    # MurmurHash3 以 4 字节块为主体处理，尾部不足 4 字节再单独混合。
    for i in range(0, rounded_end, 4):
        k1 = int.from_bytes(data[i : i + 4], "little")
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    # 处理尾部 1-3 字节。这里严格保持小端序位移顺序。
    k1 = 0
    tail = data[rounded_end:]
    if len(tail) == 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1

    # 最终混合阶段把长度和高低位充分混合，得到最终 32 位结果。
    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 & 0xFFFFFFFF


@dataclass
class FieldDef:
    """RE_RSZ 模板中的字段定义。"""

    name: str
    field_type: str
    original_type: str
    size: int
    align: int
    is_array: bool


@dataclass
class ClassDef:
    """RE_RSZ 模板中的类型定义。"""

    name: str
    crc: int
    fields: list[FieldDef]


class TypeDB:
    """封装 RE_RSZ 模板中的类型索引。"""

    def __init__(self, classes: dict[int, ClassDef]):
        """初始化类型数据库。

        Args:
            classes: 以类型哈希为键的类型定义。
        """
        self.classes = classes
        # name_to_hash 用于封包时从 JSON 类名反查类型哈希。
        self.name_to_hash = {c.name: h for h, c in classes.items()}

    @classmethod
    def load(cls, json_path: Path) -> "TypeDB":
        """从 RE_RSZ 模板 JSON 读取类型数据库。

        Args:
            json_path: 模板 JSON 文件路径。

        Returns:
            已加载的 `TypeDB`。
        """
        with json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        classes: dict[int, ClassDef] = {}
        for key, value in raw.items():
            try:
                # RE_RSZ 模板通常以十六进制字符串保存类型哈希。
                class_hash = int(key, 16)
            except ValueError:
                continue
            fields: list[FieldDef] = []
            for field in value.get("fields", []):
                # 字段缺省值尽量保守，保证模板中少数字段缺属性时仍能加载。
                fields.append(
                    FieldDef(
                        name=field.get("name", ""),
                        field_type=field.get("type", "Data"),
                        original_type=field.get("original_type", ""),
                        size=int(field.get("size", 0)),
                        align=int(field.get("align", 1)),
                        is_array=bool(field.get("array", False)),
                    )
                )
            crc_raw = value.get("crc", "0")
            crc = int(crc_raw, 16) if isinstance(crc_raw, str) else int(crc_raw)
            classes[class_hash] = ClassDef(
                name=value.get("name", ""), crc=crc, fields=fields
            )
        return cls(classes)

    def get_class(self, class_hash: int) -> ClassDef | None:
        """按类型哈希查询类型定义。

        Args:
            class_hash: RE_RSZ 类型哈希。

        Returns:
            类型定义；不存在时返回 `None`。
        """
        return self.classes.get(class_hash)

    def resolve_struct_hash(self, original_type: str) -> int | None:
        """把结构体类型名解析为类型哈希。

        Args:
            original_type: 模板字段中的原始结构体类型名。

        Returns:
            找到的类型哈希；无法解析时返回 `None`。
        """
        if not original_type:
            return None
        known = self.name_to_hash.get(original_type)
        if known is not None:
            return known
        # 有些结构体不会直接出现在 name_to_hash 中，需要按 RE_RSZ 规则
        # 对类型名做 MurmurHash3 后再查模板。
        maybe = murmur3_32(original_type.encode("utf-8"), seed=0xFFFFFFFF)
        if maybe in self.classes:
            return maybe
        return None
