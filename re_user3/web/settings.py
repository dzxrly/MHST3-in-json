"""本地 Web UI 的运行配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebSettings:
    """HTTP 服务和转换任务共享的配置。"""

    host: str = "127.0.0.1"
    port: int = 8765
    root_dir: Path = Path.cwd()
    max_jobs: int = 50

    def with_resolved_root(self) -> "WebSettings":
        """返回根目录已解析为绝对路径的新配置对象。"""
        # dataclass 设置为 frozen，使用新对象可以避免运行中误改配置。
        return WebSettings(
            host=self.host,
            port=self.port,
            root_dir=self.root_dir.expanduser().resolve(),
            max_jobs=self.max_jobs,
        )
