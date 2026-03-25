from __future__ import annotations

import argparse
import json
import os

from user3_exporter import User3Exporter

ENUM_UNUSED_KEY = "value__"


def export_enums_internal(dump_json: dict) -> dict:
    enums_internal = {}
    for key, value in dump_json.items():
        if isinstance(value, dict):
            # check if is "parent"
            obj = dump_json[key]
            if "parent" in obj and obj["parent"] == "System.Enum":
                val = {}
                for _k, _v in obj["fields"].items():
                    if _k != ENUM_UNUSED_KEY:
                        val[_k] = _v["default"]
                enums_internal[key] = val
    return enums_internal


def main() -> None:
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
    args = parser.parse_args()

    tree_depth: int | str
    if isinstance(args.tree_depth, str) and args.tree_depth.strip().lower() == "auto":
        tree_depth = "auto"
    else:
        tree_depth = int(args.tree_depth)

    # Export Enums_Internal.json from input_dir/il2cpp_dump.json
    print("Exporting Enums_Internal.json from il2cpp_dump.json...")
    assert os.path.exists(os.path.join(args.input_dir, "il2cpp_dump.json")), "il2cpp_dump.json not found"
    with open(os.path.join(args.input_dir, "il2cpp_dump.json"), "r", encoding="utf-8") as f:
        il2cpp_dump = json.load(f)
    enums_internal = export_enums_internal(il2cpp_dump)
    with open(os.path.join(args.output_dir, "Enums_Internal.json"), "w", encoding="utf-8") as f:
        json.dump(enums_internal, f, ensure_ascii=False, indent=2)
    print("Exported Enums_Internal.json from il2cpp_dump.json. Done.")

    # Export .user.3 files to JSON
    print("Exporting .user.3 files to JSON...")
    exporter = User3Exporter(
        user3_root=args.input_dir,
        schema_dir=args.schema_dir,
        output_root=args.output_dir,
        tree_depth=tree_depth,
    )
    result = exporter.run()
    print("Exported .user.3 files to JSON. Done:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
