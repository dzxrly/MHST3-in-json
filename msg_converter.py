"""`.msg.23` 转 JSON 的轻量包装层。

项目自身的通用库 `re_user3` 只处理 `.user.3`。这里保留对
`REMSG_Converter` 子模块的调用，让 `main.py export` 可以在同一次
批处理里顺手转换消息文本文件，同时不把该依赖耦合进核心库。
"""

from __future__ import annotations

import importlib
import re
import sys
import types
from pathlib import Path

from re_user3.rich_ui import BatchProgress


class MsgConverter:
    """递归转换 `.msg.23` 文件，并保持输入目录的相对路径结构。"""

    def __init__(
        self,
        input_root: str | Path,
        output_root: str | Path,
        converter_root: str | Path = "REMSG_Converter",
        exclude_regexes: list[str] | None = None,
    ):
        """初始化消息转换器。

        参数：
            input_root: 输入根目录，或单个 `.msg.23` 文件。
            output_root: JSON 输出根目录。
            converter_root: 包含 `src/REMSGUtil.py` 的转换器目录。
            exclude_regexes: 用于排除相对路径的正则表达式列表。
        """
        self.input_root = Path(input_root)
        self.output_root = Path(output_root)
        self.converter_root = Path(converter_root)
        self.converter_src = self.converter_root / "src"
        self.exclude_regexes = exclude_regexes or []
        self._exclude_patterns = [re.compile(p) for p in self.exclude_regexes]
        self._remsg_util = self._load_remsg_util()

    def _load_remsg_util(self):
        """从子模块源码目录动态加载 `REMSGUtil`。

        返回：
            已导入的 `REMSGUtil` 模块对象。
        """
        src_path = str(self.converter_src.resolve())
        # REMSG_Converter 不是标准安装包，因此需要临时把 src 目录放入
        # `sys.path`，让它内部的相对导入按原项目结构工作。
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        try:
            return importlib.import_module("REMSGUtil")
        except SyntaxError as exc:
            # 子模块源码不在本仓库维护范围内。遇到已知 f-string 语法问题时，
            # 只在内存中热修补，避免直接改动第三方代码。
            if "REMSGUtil.py" not in str(exc.filename):
                raise
            return self._load_remsg_util_with_hotfix()

    def _load_remsg_util_with_hotfix(self):
        """通过内存补丁加载 `REMSGUtil`。

        返回：
            应用内存补丁后的 `REMSGUtil` 模块对象。
        """
        # REMSGUtil 依赖 REMSG，REMSG 又依赖 HexTool。Python 3.9 下这些
        # 模块都可能因为 3.10 语法无法导入，因此按依赖顺序统一热修补。
        self._load_module_with_hotfix("HexTool")
        self._load_module_with_hotfix("REMSG")
        return self._load_module_with_hotfix("REMSGUtil")

    def _load_module_with_hotfix(self, module_name: str):
        """读取并执行应用兼容性补丁后的子模块源码。"""
        source_path = self.converter_src / f"{module_name}.py"
        source = source_path.read_text(encoding="utf-8")
        source = self._patch_remsg_source(module_name, source)

        # 某些版本的 REMSGUtil 在新版 Python 下会因为嵌套 f-string 报错。
        # 这里只替换影响导入的断言文本，不改变实际转换数据结构。
        if module_name == "REMSGUtil":
            source = re.sub(
                r'assert\s+len\(contents\)\s*==\s*langCount,\s*f"Invalid number of language / contents\.?\\n\{"\\n"\.join\(contents\)\}"',
                'assert len(contents) == langCount, "Invalid number of language / contents"',
                source,
            )

            # 修复 f-string 表达式里嵌套双引号导致的语法错误。
            source = source.replace('else "="+entry.name', "else '=' + entry.name")

        # 手动创建模块对象并执行编译后的源码，相当于一次受控的动态导入。
        module = types.ModuleType(module_name)
        module.__file__ = str(source_path)
        module.__package__ = ""
        sys.modules[module_name] = module
        try:
            exec(compile(source, str(source_path), "exec"), module.__dict__)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

    @staticmethod
    def _patch_remsg_source(module_name: str, source: str) -> str:
        """把 REMSG_Converter 的已知 3.10 语法改成兼容 Python 3.9 的源码。"""
        if "from __future__ import annotations" not in source:
            source = f"from __future__ import annotations\n{source}"

        if module_name == "REMSGUtil":
            source = source.replace(
                """    match vtype:
        case -1:  # null wstring
            value = ""
        case 0:  # int64
            value = int(inValue)
        case 1:  # double
            value = float(inValue)
        case 2:  # wstring
            value = str(inValue)
""",
                """    if vtype == -1:
        value = ""
    elif vtype == 0:
        value = int(inValue)
    elif vtype == 1:
        value = float(inValue)
    elif vtype == 2:
        value = str(inValue)
""",
            )
            source = source.replace(
                """    match ty:
        case -1:
            return "Unknown"
        case 0:
            return "Int"
        case 1:
            return "Float"
        case 2:
            return "String"
        case _:
            return "Unknown"
""",
                """    if ty == -1:
        return "Unknown"
    if ty == 0:
        return "Int"
    if ty == 1:
        return "Float"
    if ty == 2:
        return "String"
    return "Unknown"
""",
            )
        elif module_name == "REMSG":
            source = source.replace(
                """            match header["valueType"]:
                case -1:  # null wstring
                    (value,) = struct.unpack("<Q", filestream.read(8))
                case 0:  # int64
                    (value,) = struct.unpack("<q", filestream.read(8))
                case 1:  # double
                    (value,) = struct.unpack("<d", filestream.read(8))
                case 2:  # wstring
                    (value,) = struct.unpack("<Q", filestream.read(8))
                case _:
                    raise NotImplementedError(f"{value} not implemented")
""",
                """            if header["valueType"] == -1:
                (value,) = struct.unpack("<Q", filestream.read(8))
            elif header["valueType"] == 0:
                (value,) = struct.unpack("<q", filestream.read(8))
            elif header["valueType"] == 1:
                (value,) = struct.unpack("<d", filestream.read(8))
            elif header["valueType"] == 2:
                (value,) = struct.unpack("<Q", filestream.read(8))
            else:
                raise NotImplementedError(f"{value} not implemented")
""",
            )
            source = source.replace(
                """            match header["valueType"]:
                case -1:  # null wstring
                    value = struct.pack("<q", -1)
                case 0:  # int64
                    value = struct.pack("<q", self.attributes[i])
                case 1:  # double
                    value = struct.pack("<d", self.attributes[i])
                case 2:  # wstring
                    value = struct.pack("<q", -1)
""",
                """            if header["valueType"] == -1:
                value = struct.pack("<q", -1)
            elif header["valueType"] == 0:
                value = struct.pack("<q", self.attributes[i])
            elif header["valueType"] == 1:
                value = struct.pack("<d", self.attributes[i])
            elif header["valueType"] == 2:
                value = struct.pack("<q", -1)
""",
            )
        return source

    @staticmethod
    def _is_msg23(file_path: Path) -> bool:
        """判断文件名是否符合 `.msg.23` 后缀。"""
        return file_path.name.lower().endswith(".msg.23")

    def _discover_msg_files(self) -> list[Path]:
        """发现待转换的 `.msg.23` 文件，并应用排除规则。

        返回：
            过滤后的消息文件路径列表。
        """
        if self.input_root.is_file():
            # 单文件模式下只接受 `.msg.23`，其他文件会被静默视为无任务。
            files = [self.input_root] if self._is_msg23(self.input_root) else []
        else:
            if not self.input_root.is_dir():
                raise FileNotFoundError(f"input root not found: {self.input_root}")
            # 目录模式递归扫描，保持和 `.user.3` 导出器相同的批处理体验。
            files = sorted(
                f for f in self.input_root.rglob("*") if f.is_file() and self._is_msg23(f)
            )

        if not files or not self._exclude_patterns:
            return files

        kept: list[Path] = []
        for file_path in files:
            # 正则统一匹配相对路径；单文件模式下只能匹配文件名。
            if self.input_root.is_file():
                rel_path = file_path.name
            else:
                rel_path = file_path.relative_to(self.input_root).as_posix()
            if any(pattern.search(rel_path) for pattern in self._exclude_patterns):
                continue
            kept.append(file_path)
        return kept

    def _output_path_for(self, msg_file: Path) -> Path:
        """计算单个 `.msg.23` 的输出 JSON 路径。

        参数：
            msg_file: 源消息文件路径。

        返回：
            保持相对目录结构后的输出路径。
        """
        if self.input_root.is_file():
            relative_parent = Path()
        else:
            relative_parent = msg_file.relative_to(self.input_root).parent
        output_name = f"{msg_file.name}.json"
        return self.output_root / relative_parent / output_name

    def _convert_one_file(
        self, msg_file: Path
    ) -> tuple[bool, Path | None, str | None]:
        """转换单个 `.msg.23` 文件。

        参数：
            msg_file: 源消息文件路径。

        返回：
            `(是否成功, 输出路径, 错误信息)`，失败时由批处理统一记录日志。
        """
        try:
            # importMSG/exportJson 均来自 REMSG_Converter 子模块。
            msg = self._remsg_util.importMSG(str(msg_file))
            output_path = self._output_path_for(msg_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._remsg_util.exportJson(msg, str(output_path))
            return True, output_path, None
        except Exception as exc:
            return False, None, f"{exc.__class__.__name__}: {exc}"

    def run(self) -> dict[str, int]:
        """执行完整批量转换流程。

        返回：
            包含 `total`、`success`、`failed` 的统计字典。
        """
        files = self._discover_msg_files()
        self.output_root.mkdir(parents=True, exist_ok=True)

        success = 0
        failed = 0
        # Rich 进度条固定在底部；单文件日志从上方持续滚动输出。
        with BatchProgress(
            "Converting msg", total=len(files), unit="file"
        ) as progress:
            progress.log(f"发现 {len(files)} 个 .msg.23 文件。")
            for msg_file in files:
                label = msg_file.name.replace(".msg.23", "")
                progress.update(advance=0, description=label)
                progress.log(f"开始转换消息: {msg_file}")
                ok, output_path, error = self._convert_one_file(msg_file)
                if ok:
                    success += 1
                    progress.log(f"消息转换完成: {output_path}", style="green")
                else:
                    failed += 1
                    progress.log(f"消息转换失败: {msg_file} ({error})", style="red")
                progress.update(1)

        return {"total": len(files), "success": success, "failed": failed}
