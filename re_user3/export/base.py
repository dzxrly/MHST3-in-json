"""`.user.3` 到 JSON 的导出器入口。"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from tqdm.rich import tqdm
except Exception:  # 轻量环境下允许没有 tqdm/rich
    def tqdm(iterable=None, total=None, desc=None, unit=None):
        """在缺少 tqdm 时提供一个无显示的兼容进度条。"""

        class _Tqdm:
            """最小进度条协议实现。"""

            def __init__(self, iterable=None, total=None, desc=None, unit=None):
                """保存可迭代对象，其他参数仅用于兼容 tqdm 签名。"""
                self.iterable = iterable

            def __enter__(self):
                """支持 `with tqdm(...)` 写法。"""
                return self

            def __exit__(self, exc_type, exc, tb):
                """退出上下文时不吞掉异常。"""
                return False

            def __iter__(self):
                """返回原始迭代器。"""
                return iter(self.iterable or [])

            def update(self, n=1):
                """兼容 tqdm 的进度更新接口。"""
                return None

            def set_description(self, desc):
                """兼容 tqdm 的描述更新接口。"""
                return None

        return _Tqdm(iterable, total, desc, unit)

from ..core import RSZ_MAGIC, USR_MAGIC, TypeDB, resolve_schema_path
from .enums import ExporterEnumSourceMixin
from .fields import ExporterFieldParserMixin
from .metadata import ExporterMetadataMixin
from .postprocess import ExporterPostprocessMixin
from .tree import ExporterTreeMixin
from .user3 import ExporterUser3ParserMixin


class User3Exporter(
    ExporterEnumSourceMixin,
    ExporterMetadataMixin,
    ExporterPostprocessMixin,
    ExporterTreeMixin,
    ExporterFieldParserMixin,
    ExporterUser3ParserMixin,
):
    """把 RE Engine `.user.3` 二进制文件导出为紧凑 JSON。"""

    def __init__(
        self,
        user3_root: str | Path,
        schema_dir: str | Path,
        output_root: str | Path,
        tree_depth: int | str = "auto",
        exclude_regexes: list[str] | None = None,
        il2cpp_dump_path: str | Path = "",
        user_magic: int = USR_MAGIC,
        rsz_magic: int = RSZ_MAGIC,
    ):
        """初始化导出器配置和运行期索引。

        参数：
            user3_root: 输入根目录或单个 `.user.3` 文件。
            schema_dir: 显式传入的 RE_RSZ 模板 JSON 文件路径。
            output_root: JSON 输出根目录。
            tree_depth: 对象引用树展开深度，支持整数或 `"auto"`。
            exclude_regexes: 用于排除相对路径的正则表达式列表。
            il2cpp_dump_path: 必填的 `il2cpp_dump.json` 文件路径。
            user_magic: 期望读取到的 USR 文件 magic。
            rsz_magic: 期望读取到的 RSZ 块 magic。
        """
        # 路径在入口处统一转为 Path，后续模块只处理 Path 对象。
        self.user3_root = Path(user3_root)
        self.schema_dir = Path(schema_dir)
        self.output_root = Path(output_root)
        self.il2cpp_dump_path = Path(il2cpp_dump_path)
        if not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        self.tree_depth = self._normalize_tree_depth(tree_depth)
        self.user_magic = int(user_magic)
        self.rsz_magic = int(rsz_magic)
        self.exclude_regexes = exclude_regexes or []
        self._exclude_patterns = [re.compile(p) for p in self.exclude_regexes]
        self.schema_path = self._resolve_schema_path(self.schema_dir)
        self.typedb = TypeDB.load(self.schema_path)
        # 下面这些索引在导出前由 il2cpp_dump.json 构建，用于把固定枚举值
        # 转成 `[数值] 成员名`，并在泛型容器中推断字段对应的枚举类型。
        self.enum_lookup: dict[str, dict[int, tuple[str, int]]] = {}
        self.class_field_fixed_types: dict[str, dict[str, str]] = {}
        self.serializable_to_fixed: dict[str, str] = {}
        self.generic_container_rules: dict[str, tuple[str, str]] = {}
        self.param_type_default_enum: dict[str, str] = {}
        self.enum_member_to_types: dict[str, list[str]] = {}

    def run(self) -> dict[str, int]:
        """执行批量导出流程。

        返回：
            包含 `total`、`success`、`failed` 的统计字典。
        """
        files = self._discover_user3_files()
        self.output_root.mkdir(parents=True, exist_ok=True)
        # 每次导出都根据显式传入的 il2cpp_dump.json 重新生成枚举表，
        # 不复用旧目录中的 Enums_Internal.json，避免跨游戏或跨版本污染。
        enums_internal = self._ensure_internal_metadata_files()
        self.enum_lookup = self._build_enum_lookup_from_enums_internal(
            enums_internal
        )
        self._load_enum_context_from_il2cpp_dump()
        self._ensure_enum_lookup()

        success = 0
        failed = 0
        # 单文件失败只计入失败数量，不中断整批导出；这样大批量资源更容易排查。
        with tqdm(total=len(files), desc="Exporting user3", unit="file") as pbar:
            for user3_file in files:
                pbar.set_description(user3_file.name.replace(".user.3", ""))
                if self._export_one_file(user3_file):
                    success += 1
                else:
                    failed += 1
                pbar.update(1)

        return {"total": len(files), "success": success, "failed": failed}

    def _export_one_file(self, user3_file: Path) -> bool:
        """导出单个 `.user.3` 文件。

        参数：
            user3_file: 源 `.user.3` 文件路径。

        返回：
            成功返回 `True`，异常返回 `False` 交给批量统计。
        """
        try:
            # 解析出的原始树先经过枚举后处理，再移除内部索引和值包装，
            # 最后对展示用浮点数做轻微圆整，生成更适合人工编辑的 JSON。
            tree = self._parse_user3(user3_file)
            tree = self._postprocess_enum_nodes(tree)
            tree = self._finalize_export_tree(tree)
            tree = self._round_export_floats(tree)
            output_path = self._output_path_for(user3_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(tree, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _resolve_schema_path(self, schema_dir: Path) -> Path:
        """校验并返回模板文件路径。

        参数：
            schema_dir: 历史参数名，实际必须是具体模板 JSON 文件。

        返回：
            校验后的模板文件路径。
        """
        return resolve_schema_path(schema_dir)

    def _normalize_tree_depth(self, tree_depth: int | str) -> int | str:
        """规范化对象树展开深度。

        参数：
            tree_depth: 用户传入的深度设置。

        返回：
            非负整数或 `"auto"`。
        """
        if isinstance(tree_depth, str):
            value = tree_depth.strip().lower()
            if value != "auto":
                raise ValueError("tree_depth must be a non-negative integer or 'auto'")
            return "auto"
        if isinstance(tree_depth, int):
            if tree_depth < 0:
                raise ValueError("tree_depth must be >= 0")
            return tree_depth
        raise TypeError("tree_depth must be int or str")

    def _discover_user3_files(self) -> list[Path]:
        """发现输入 `.user.3` 文件并应用排除规则。

        返回：
            过滤后的 `.user.3` 文件列表。
        """
        if self.user3_root.is_file():
            files = [self.user3_root]
        else:
            if not self.user3_root.is_dir():
                raise FileNotFoundError(f"user3 root not found: {self.user3_root}")
            files = sorted(self.user3_root.rglob("*.user.3"))
            if not files:
                raise FileNotFoundError(f"no *.user.3 found under: {self.user3_root}")
        if not self._exclude_patterns:
            return files

        kept: list[Path] = []
        for file_path in files:
            # 目录模式下按相对路径匹配排除正则，便于排除整类子目录。
            if self.user3_root.is_file():
                rel_path = file_path.name
            else:
                rel_path = file_path.relative_to(self.user3_root).as_posix()
            if any(pattern.search(rel_path) for pattern in self._exclude_patterns):
                continue
            kept.append(file_path)
        if not kept:
            raise FileNotFoundError("all *.user.3 files were excluded by regex filters")
        return kept

    def _output_path_for(self, user3_file: Path) -> Path:
        """计算单个源文件对应的 JSON 输出路径。

        参数：
            user3_file: 源 `.user.3` 文件。

        返回：
            输出 JSON 文件路径。
        """
        if self.user3_root.is_file():
            relative_parent = Path()
        else:
            relative_parent = user3_file.relative_to(self.user3_root).parent
        output_name = f"{user3_file.name}.json"
        return self.output_root / relative_parent / output_name
