"""本地路径选择对话框。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_PICKER_LOCK = threading.Lock()


def pick_path(payload: dict[str, Any]) -> dict[str, str]:
    """根据前端请求打开文件或目录选择对话框。"""
    # tkinter 是 Python 标准库，适合在本地工具里弹出原生选择框。
    # 这里延迟导入，避免无界面环境仅启动服务时就尝试初始化 GUI。
    import tkinter as tk
    from tkinter import filedialog

    kind = str(payload.get("kind", "file")).strip().lower()
    title = str(payload.get("title", "请选择路径")).strip() or "请选择路径"
    filetypes = _normalize_filetypes(payload.get("filetypes"))

    with _PICKER_LOCK:
        # 多个浏览器请求同时打开文件框会非常混乱，因此用锁串行化。
        root = tk.Tk()
        root.withdraw()
        try:
            # 尽量把对话框放到最前面，避免用户以为网页没有响应。
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            if kind == "directory":
                selected = filedialog.askdirectory(
                    parent=root,
                    title=title,
                    mustexist=False,
                )
            elif kind == "file":
                selected = filedialog.askopenfilename(
                    parent=root,
                    title=title,
                    filetypes=filetypes,
                )
            else:
                raise ValueError("路径选择类型必须是 file 或 directory")
        finally:
            root.destroy()

    # 用户取消选择时返回空字符串，前端保持原字段不变。
    return {"path": str(Path(selected)) if selected else ""}


def _normalize_filetypes(raw: Any) -> list[tuple[str, str]]:
    """把前端传来的文件过滤器整理成 tkinter 接受的格式。"""
    if not isinstance(raw, list):
        return [("所有文件", "*.*")]

    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        label = str(item[0]).strip()
        pattern = str(item[1]).strip()
        if label and pattern:
            out.append((label, pattern))
    return out or [("所有文件", "*.*")]
