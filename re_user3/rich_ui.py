"""基于 Rich 的批处理进度条和日志输出工具。"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

_CONSOLE = Console()


def get_console() -> Console:
    """返回命令行批处理共用的 Rich 控制台。"""
    return _CONSOLE


class BatchProgress:
    """让 Rich 进度条固定在底部，并把日志滚动输出到上方。"""

    def __init__(self, description: str, total: int, unit: str = "file") -> None:
        self.description = description
        self.total = total
        self.unit = unit
        self.console = get_console()
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn(unit),
            TextColumn("elapsed"),
            TimeElapsedColumn(),
            TextColumn("eta"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True,
            transient=False,
        )
        self._task_id: TaskID | None = None

    def __enter__(self) -> "BatchProgress":
        self._progress.__enter__()
        self._task_id = self._progress.add_task(self.description, total=self.total)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self._progress.__exit__(exc_type, exc, tb)
        return False

    def log(self, message: str, style: str | None = None) -> None:
        """在实时进度条上方输出一行日志。"""
        self.console.log(message, style=style)

    def update(self, advance: int = 1, description: str | None = None) -> None:
        """推进当前任务，并可同时更新底部进度条标签。"""
        if self._task_id is None:
            return
        kwargs: dict[str, Any] = {"advance": advance}
        if description is not None:
            kwargs["description"] = description
        self._progress.update(self._task_id, **kwargs)
