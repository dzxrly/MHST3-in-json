"""命令行入口，负责分发 `.user.3` 导出流程。

本文件只做参数解析和流程编排，具体的二进制解析和 JSON 生成逻辑
由已安装的 `pyreuser3` 软件包提供，便于本仓库只保留 MHST3 项目
专属的导出命令组合与 `.msg.23` 转换入口。
"""

from __future__ import annotations

import argparse
import json
import sys

from pyreuser3 import User3Exporter
from pyreuser3.core import RSZ_MAGIC, USR_MAGIC
from pyreuser3.rich_ui import get_console


def configure_utf8_stdio() -> None:
    """让 Rich 进度输出在 Windows 的非 UTF-8 终端中也可用。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def parse_int_arg(value: str) -> int:
    """解析命令行中的十进制或 `0x` 前缀整数。

    参数：
        value: 用户输入的整数字符串。

    返回：
        转换后的整数，可用于 magic 等二进制字段。
    """
    return int(value, 0)


def run_export(argv: list[str] | None = None) -> None:
    """解析导出参数，并依次执行 `.msg.23` 与 `.user.3` 导出。

    参数：
        argv: 不包含子命令名的参数列表；为 `None` 时由 argparse 读取默认输入。
    """
    parser = argparse.ArgumentParser(description="Export all .user.3 files to JSON.")
    parser.add_argument(
        "--input-dir",
        "-i",
        required=True,
        help="Root directory that contains .user.3 files (recursive).",
    )
    parser.add_argument(
        "--schema-path",
        "--schema-dir",
        "-s",
        dest="schema_path",
        required=True,
        help="Explicit RE RSZ schema json file path.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="Root output directory for exported json files.",
    )
    parser.add_argument(
        "--tree-depth",
        "-d",
        default="auto",
        help="Tree depth as non-negative integer or 'auto' (default: auto).",
    )
    parser.add_argument(
        "--exclude-regex",
        "-x",
        action="append",
        default=[],
        help=(
            "Regex to exclude matching relative file paths. "
            "Can be used multiple times."
        ),
    )
    parser.add_argument(
        "--il2cpp-dump-path",
        "-p",
        required=True,
        help=(
            "Path to il2cpp_dump.json. "
            "This parameter is required and used to generate Enums_Internal.json."
        ),
    )
    parser.add_argument(
        "--user-magic",
        type=parse_int_arg,
        default=USR_MAGIC,
        help=f"USR file magic as decimal or hex (default: 0x{USR_MAGIC:08x}).",
    )
    parser.add_argument(
        "--rsz-magic",
        type=parse_int_arg,
        default=RSZ_MAGIC,
        help=f"RSZ block magic as decimal or hex (default: 0x{RSZ_MAGIC:08x}).",
    )
    args = parser.parse_args(argv)

    # `tree_depth` 支持 `auto` 和非负整数。这里先归一化，避免底层类
    # 同时处理字符串大小写、空格和整数转换这些命令行细节。
    tree_depth: int | str
    if isinstance(args.tree_depth, str) and args.tree_depth.strip().lower() == "auto":
        tree_depth = "auto"
    else:
        tree_depth = int(args.tree_depth)

    # `.msg.23` 依赖 REMSG_Converter 子模块。延迟导入避免只导入
    # 本模块、尚未执行批量导出时就加载该子模块。
    from msg_converter import MsgConverter

    # 先转换文本消息文件。转换失败的单文件会被统计到失败数量中，
    # 不会阻止后续 `.user.3` 数据库导出。
    console = get_console()
    console.log("Converting .msg.23 files to JSON...")
    msg_converter = MsgConverter(
        input_root=args.input_dir,
        output_root=args.output_dir,
        exclude_regexes=args.exclude_regex,
    )
    msg_result = msg_converter.run()
    console.log(
        "Converted .msg.23 files to JSON. Done:",
        json.dumps(msg_result, ensure_ascii=False),
    )

    # 再导出 `.user.3`。schema 与 il2cpp_dump 都必须由用户显式传入，
    # 这里不做任何自动查找，避免在多游戏项目中误用旧依赖文件。
    console.log("Exporting .user.3 files to JSON...")
    exporter = User3Exporter(
        user3_root=args.input_dir,
        schema_dir=args.schema_path,
        output_root=args.output_dir,
        tree_depth=tree_depth,
        exclude_regexes=args.exclude_regex,
        il2cpp_dump_path=args.il2cpp_dump_path,
        user_magic=args.user_magic,
        rsz_magic=args.rsz_magic,
    )
    result = exporter.run()
    console.log(
        "Exported .user.3 files to JSON. Done:", json.dumps(result, ensure_ascii=False)
    )


def main() -> None:
    """运行导出命令。

    为了兼容现有脚本，`export` 子命令可以省略。
    """
    configure_utf8_stdio()
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-"):
        if argv[0] == "export":
            run_export(argv[1:])
            return
        raise SystemExit(f"Unsupported command {argv[0]!r}; only 'export' is available.")
    run_export(argv)


if __name__ == "__main__":
    main()
