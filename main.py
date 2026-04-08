from __future__ import annotations

import argparse
import json

from msg_converter import MsgConverter
from user3_exporter import User3Exporter


def main() -> None:
    """Parse CLI arguments and run exporter.

    @return None.
    """
    parser = argparse.ArgumentParser(description="Export all .user.3 files to JSON.")
    parser.add_argument(
        "--input-dir",
        "-i",
        required=True,
        help="Root directory that contains .user.3 files (recursive).",
    )
    parser.add_argument(
        "--schema-dir",
        "-s",
        required=True,
        help="Directory that contains rszmhst3.json (or direct path to json).",
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
        default=None,
        help=(
            "Path to il2cpp_dump.json. "
            "When provided, enum metadata generation will use this file directly."
        ),
    )
    args = parser.parse_args()

    tree_depth: int | str
    if isinstance(args.tree_depth, str) and args.tree_depth.strip().lower() == "auto":
        tree_depth = "auto"
    else:
        tree_depth = int(args.tree_depth)

    # Convert .msg.23 files to JSON
    print("Converting .msg.23 files to JSON...")
    msg_converter = MsgConverter(
        input_root=args.input_dir,
        output_root=args.output_dir,
        exclude_regexes=args.exclude_regex,
    )
    msg_result = msg_converter.run()
    print(
        "Converted .msg.23 files to JSON. Done:",
        json.dumps(msg_result, ensure_ascii=False),
    )

    # Export .user.3 files to JSON
    print("Exporting .user.3 files to JSON...")
    exporter = User3Exporter(
        user3_root=args.input_dir,
        schema_dir=args.schema_dir,
        output_root=args.output_dir,
        tree_depth=tree_depth,
        exclude_regexes=args.exclude_regex,
        il2cpp_dump_path=args.il2cpp_dump_path,
    )
    result = exporter.run()
    print(
        "Exported .user.3 files to JSON. Done:", json.dumps(result, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
