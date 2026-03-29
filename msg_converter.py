from __future__ import annotations

import importlib
import re
import sys
import types
from pathlib import Path

from tqdm.rich import tqdm


class MsgConverter:
    """Convert `.msg.23` files to JSON while preserving relative paths."""

    def __init__(
        self,
        input_root: str | Path,
        output_root: str | Path,
        converter_root: str | Path = "REMSG_Converter",
        exclude_regexes: list[str] | None = None,
    ):
        """Initialize converter configuration.

        @param input_root Input root directory or single `.msg.23` file.
        @param output_root Output root directory.
        @param converter_root Directory that contains converter `src` package.
        @param exclude_regexes Optional regex list used to exclude files.
        @return None.
        """
        self.input_root = Path(input_root)
        self.output_root = Path(output_root)
        self.converter_root = Path(converter_root)
        self.converter_src = self.converter_root / "src"
        self.exclude_regexes = exclude_regexes or []
        self._exclude_patterns = [re.compile(p) for p in self.exclude_regexes]
        self._remsg_util = self._load_remsg_util()

    def _load_remsg_util(self):
        """Load REMSGUtil from local converter source directory.

        @return Imported REMSGUtil module.
        """
        src_path = str(self.converter_src.resolve())
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        try:
            return importlib.import_module("REMSGUtil")
        except SyntaxError as exc:
            # Keep submodule clean: hotfix known upstream f-string syntax issues in memory.
            if "REMSGUtil.py" not in str(exc.filename):
                raise
            return self._load_remsg_util_with_hotfix()

    def _load_remsg_util_with_hotfix(self):
        """Load REMSGUtil via in-memory source patching.

        @return Imported REMSGUtil module.
        """
        source_path = self.converter_src / "REMSGUtil.py"
        source = source_path.read_text(encoding="utf-8")

        source = re.sub(
            r'assert\s+len\(contents\)\s*==\s*langCount,\s*f"Invalid number of language / contents\.?\\n\{"\\n"\.join\(contents\)\}"',
            'assert len(contents) == langCount, "Invalid number of language / contents"',
            source,
        )

        # Fix nested double-quote expression inside f-string.
        source = source.replace('else "="+entry.name', "else '=' + entry.name")

        module = types.ModuleType("REMSGUtil")
        module.__file__ = str(source_path)
        module.__package__ = ""
        sys.modules["REMSGUtil"] = module
        exec(compile(source, str(source_path), "exec"), module.__dict__)
        return module

    @staticmethod
    def _is_msg23(file_path: Path) -> bool:
        """Check whether file matches `.msg.23` naming."""
        return file_path.name.lower().endswith(".msg.23")

    def _discover_msg_files(self) -> list[Path]:
        """Discover input `.msg.23` files and apply excludes.

        @return Discovered `.msg.23` files after exclude filtering.
        """
        if self.input_root.is_file():
            files = [self.input_root] if self._is_msg23(self.input_root) else []
        else:
            if not self.input_root.is_dir():
                raise FileNotFoundError(f"input root not found: {self.input_root}")
            files = sorted(
                f for f in self.input_root.rglob("*") if f.is_file() and self._is_msg23(f)
            )

        if not files or not self._exclude_patterns:
            return files

        kept: list[Path] = []
        for file_path in files:
            if self.input_root.is_file():
                rel_path = file_path.name
            else:
                rel_path = file_path.relative_to(self.input_root).as_posix()
            if any(pattern.search(rel_path) for pattern in self._exclude_patterns):
                continue
            kept.append(file_path)
        return kept

    def _output_path_for(self, msg_file: Path) -> Path:
        """Build output json path for one source file.

        @param msg_file Source file path.
        @return Output json path.
        """
        if self.input_root.is_file():
            relative_parent = Path()
        else:
            relative_parent = msg_file.relative_to(self.input_root).parent
        output_name = f"{msg_file.name}.json"
        return self.output_root / relative_parent / output_name

    def _convert_one_file(self, msg_file: Path) -> bool:
        """Convert one `.msg.23` file to json.

        @param msg_file Source msg path.
        @return True on success.
        """
        try:
            msg = self._remsg_util.importMSG(str(msg_file))
            output_path = self._output_path_for(msg_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._remsg_util.exportJson(msg, str(output_path))
            return True
        except Exception:
            return False

    def run(self) -> dict[str, int]:
        """Run conversion pipeline for all discovered files.

        @return Conversion statistics with total/success/failed counts.
        """
        files = self._discover_msg_files()
        self.output_root.mkdir(parents=True, exist_ok=True)

        success = 0
        failed = 0
        with tqdm(total=len(files), desc="Converting msg", unit="file") as pbar:
            for msg_file in files:
                pbar.set_description(msg_file.name.replace(".msg.23", ""))
                if self._convert_one_file(msg_file):
                    success += 1
                else:
                    failed += 1
                pbar.update(1)

        return {"total": len(files), "success": success, "failed": failed}
