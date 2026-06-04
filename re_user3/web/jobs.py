"""本地 Web UI 的后台任务管理。"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    """浏览器提交的一次导出任务。"""

    id: str
    kind: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


Runner = Callable[[dict[str, Any], Callable[[str], None]], dict[str, Any]]


class JobStore:
    """线程安全的内存任务仓库。"""

    def __init__(self, max_jobs: int = 50) -> None:
        """初始化任务仓库。"""
        # Web UI 只用于本地临时操作，任务记录无需持久化到磁盘。
        self.max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, payload: dict[str, Any], runner: Runner) -> Job:
        """创建后台任务并立即启动线程。"""
        # 任务 ID 不需要可预测，只需要足够短、方便在前端显示。
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._cleanup_locked()

        # 转换任务可能耗时很长，因此必须放到后台线程中执行。
        thread = threading.Thread(
            target=self._run_worker,
            args=(job, payload, runner),
            daemon=True,
        )
        thread.start()
        return job

    def list_jobs(self) -> list[Job]:
        """按创建时间倒序返回任务快照。"""
        with self._lock:
            # 返回克隆对象，避免 HTTP 层在锁外读取时碰到并发修改。
            return sorted(
                (self._clone(job) for job in self._jobs.values()),
                key=lambda job: job.created_at,
                reverse=True,
            )

    def get(self, job_id: str) -> Job | None:
        """按任务 ID 返回单个任务快照。"""
        with self._lock:
            job = self._jobs.get(job_id)
            return self._clone(job) if job is not None else None

    def serialize(self, job: Job, include_logs: bool = False) -> dict[str, Any]:
        """把任务对象转换成可 JSON 序列化的字典。"""
        # 前端使用驼峰字段名，因此这里统一完成字段名转换。
        data: dict[str, Any] = {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "createdAt": job.created_at,
            "updatedAt": job.updated_at,
            "result": job.result,
            "error": job.error,
        }
        if include_logs:
            data["logs"] = list(job.logs)
        return data

    def _run_worker(self, job: Job, payload: dict[str, Any], runner: Runner) -> None:
        """在后台线程中执行具体任务。"""
        self._set_job(job.id, status="running")
        self._log(job.id, "任务已启动。")
        try:
            # runner 接收一个日志回调，便于转换流程把阶段性信息写回任务。
            result = runner(payload, lambda message: self._log(job.id, message))
        except Exception as exc:
            # 单个任务失败只更新任务状态，不影响 HTTP 服务和其他任务。
            error = f"{exc.__class__.__name__}: {exc}"
            self._set_job(job.id, status="failed", error=error)
            self._log(job.id, f"任务失败：{error}")
            return
        self._set_job(job.id, status="done", result=result)
        self._log(job.id, "任务完成。")

    def _set_job(self, job_id: str, **changes: Any) -> None:
        """在锁内更新任务字段。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def _log(self, job_id: str, message: str) -> None:
        """在锁内追加一条任务日志。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
            job.updated_at = time.time()

    def _cleanup_locked(self) -> None:
        """在锁内移除超出保留上限的旧任务。"""
        if len(self._jobs) <= self.max_jobs:
            return
        ordered = sorted(
            self._jobs.values(),
            key=lambda job: job.created_at,
            reverse=True,
        )
        keep = {job.id for job in ordered[: self.max_jobs]}
        for job_id in list(self._jobs):
            if job_id not in keep:
                self._jobs.pop(job_id, None)

    @staticmethod
    def _clone(job: Job) -> Job:
        """复制任务对象，隔离调用方和内部存储。"""
        return Job(
            id=job.id,
            kind=job.kind,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            logs=list(job.logs),
            result=job.result,
            error=job.error,
        )
