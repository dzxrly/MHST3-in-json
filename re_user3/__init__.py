"""RE User3 JSON 工具包的公开导出入口。

较重的转换模块会依赖 Rich 等命令行显示库。这里使用惰性导出，
让 `web.py --help` 和 `python -m re_user3.web --help` 这类轻量入口
不需要提前加载完整导出器或封包器。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BinaryReader",
    "ClassDef",
    "FieldDef",
    "PackError",
    "ParseError",
    "TypeDB",
    "REUser3Converter",
    "RSZ_MAGIC",
    "User3Exporter",
    "User3Packer",
    "USR_MAGIC",
]

_EXPORT_MODULES = {
    "BinaryReader": ".core",
    "ParseError": ".core",
    "RSZ_MAGIC": ".core",
    "USR_MAGIC": ".core",
    "ClassDef": ".schema",
    "FieldDef": ".schema",
    "TypeDB": ".schema",
    "PackError": ".pack",
    "User3Packer": ".pack",
    "User3Exporter": ".export",
    "REUser3Converter": ".api",
}


def __getattr__(name: str) -> Any:
    """首次访问公开名称时再导入对应模块。"""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # 导入后把结果缓存到 globals，后续访问不再触发 __getattr__。
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
