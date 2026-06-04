"""项目专属 Web 启动器。

`re_user3.web` 只负责 `.user.3` 解包导出。当前根脚本在不修改
`re_user3` 库的前提下，额外提供 `.msg.23` 转 JSON 的本地网页入口。
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

from re_user3.web.handler import make_handler
from re_user3.web.jobs import JobStore
from re_user3.web.runners import ConversionRunners
from re_user3.web.settings import WebSettings

MSG_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MSG 23 JSON Web</title>
  <style>
    :root{--bg:#f7f7f4;--panel:#fff;--text:#1c1d1f;--muted:#697078;--line:#d8ddd6;--accent:#176f6b;--red:#b0332e;--green:#227343;--blue:#315f9b}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Segoe UI","Microsoft YaHei",Arial,sans-serif;font-size:14px;letter-spacing:0}
    a{color:var(--accent);text-decoration:none}button,input,textarea{font:inherit}.top{border-bottom:1px solid var(--line);background:#fffefb}.inner{max-width:1120px;margin:0 auto;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px}
    h1{margin:0;font-size:20px}.sub{margin:4px 0 0;color:var(--muted);line-height:1.4}.pill{border:1px solid var(--line);border-radius:999px;padding:6px 11px;background:#f3f7f1;color:#10514e;white-space:nowrap}
    main{max-width:1120px;margin:0 auto;padding:18px 20px 24px;display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,.8fr);gap:18px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-width:0}
    .head{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px}.head h2{margin:0;font-size:15px}.body{padding:16px;display:grid;gap:14px}.field{display:grid;gap:6px}label{font-size:13px;font-weight:650;color:#32363a}
    input,textarea{width:100%;border:1px solid #cfd7cf;border-radius:7px;background:#fff;color:var(--text);padding:9px 10px;outline:none}input[readonly]{background:#f7f8f5;color:#303437}textarea{min-height:96px;resize:vertical;line-height:1.45}input:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(23,111,107,.14)}
    .path-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px}.actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.primary{border:1px solid #10514e;background:var(--accent);color:#fff;border-radius:7px;padding:10px 15px;min-width:112px;cursor:pointer;font-weight:700}.secondary{border:1px solid var(--line);background:#fbfcfa;color:#263433;border-radius:7px;padding:9px 11px;white-space:nowrap;cursor:pointer}.primary:disabled,.secondary:disabled{opacity:.62;cursor:not-allowed}.notice{color:var(--red);line-height:1.45;word-break:break-word}
    .metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.metric{border:1px solid var(--line);border-radius:7px;padding:10px;background:#fbfcfa}.metric span{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.metric strong{font-size:18px}
    .badge{border-radius:999px;padding:4px 8px;font-size:12px;border:1px solid var(--line);white-space:nowrap}.queued,.running{color:var(--blue);background:#eef4fb;border-color:#cbd9ee}.done{color:var(--green);background:#eef8f1;border-color:#c8e2cf}.failed{color:var(--red);background:#fff0ef;border-color:#e8cbc8}
    pre{margin:0;padding:12px;border:1px solid var(--line);border-radius:7px;background:#1f2424;color:#f4f6ee;min-height:260px;max-height:520px;overflow:auto;line-height:1.5;white-space:pre-wrap;word-break:break-word}.muted{color:var(--muted)}
    @media(max-width:860px){main{grid-template-columns:1fr}.inner,.actions{align-items:stretch;flex-direction:column}.path-row{grid-template-columns:1fr}.primary,.secondary{width:100%}}
  </style>
</head>
<body>
  <header class="top"><div class="inner">
    <div><h1>MSG 23 JSON Web</h1><p class="sub">只转换 .msg.23；可和 .user.3 共用同一个输出目录。</p></div>
    <div class="pill"><a href="/">返回 User3 Web</a></div>
  </div></header>
  <main>
    <section class="panel">
      <div class="head"><h2>导出 .msg.23</h2><span class="muted">不清空输出目录</span></div>
      <form class="body" id="msg-form">
        <div class="field"><label for="input-root">输入目录或 .msg.23 文件</label><div class="path-row"><input id="input-root" name="inputRoot" readonly placeholder="请选择目录或 .msg.23 文件"><button class="secondary" type="button" id="pick-input-dir">选择目录</button><button class="secondary" type="button" id="pick-input-file">选择文件</button></div></div>
        <div class="field"><label for="output-root">JSON 输出目录</label><div class="path-row"><input id="output-root" name="outputRoot" readonly placeholder="请选择 JSON 输出目录"><button class="secondary" type="button" id="pick-output-dir">选择目录</button></div></div>
        <div class="field"><label for="exclude-regexes">排除正则</label><textarea id="exclude-regexes" name="excludeRegexes" spellcheck="false"></textarea></div>
        <div class="actions"><button class="primary" id="start-button" type="submit">开始转换</button><div class="notice" id="notice"></div></div>
      </form>
    </section>
    <aside class="panel">
      <div class="head"><h2>任务日志</h2><span class="badge" id="status">未开始</span></div>
      <div class="body">
        <div class="metrics">
          <div class="metric"><span>总数</span><strong id="total">0</strong></div>
          <div class="metric"><span>成功</span><strong id="success">0</strong></div>
          <div class="metric"><span>失败</span><strong id="failed">0</strong></div>
        </div>
        <pre id="log">等待提交任务。</pre>
      </div>
    </aside>
  </main>
  <script>
    const form = document.getElementById("msg-form");
    const button = document.getElementById("start-button");
    const notice = document.getElementById("notice");
    const statusBadge = document.getElementById("status");
    const logBox = document.getElementById("log");
    const totalEl = document.getElementById("total");
    const successEl = document.getElementById("success");
    const failedEl = document.getElementById("failed");
    let activeJobId = null;

    function statusLabel(status) {
      return { queued: "排队", running: "运行中", done: "完成", failed: "失败" }[status] || status || "未开始";
    }

    function setStatus(status) {
      statusBadge.className = `badge ${status || ""}`;
      statusBadge.textContent = statusLabel(status);
    }

    function renderJob(job) {
      const result = job.result && job.result.msg ? job.result.msg : {};
      totalEl.textContent = result.total || 0;
      successEl.textContent = result.success || 0;
      failedEl.textContent = result.failed || 0;
      setStatus(job.status);
      const lines = job.logs ? [...job.logs] : [];
      if (job.error) lines.push(`[错误] ${job.error}`);
      if (job.result) lines.push(JSON.stringify(job.result, null, 2));
      logBox.textContent = lines.join("\n") || "任务已提交，等待日志。";
    }

    async function requestJson(url, options) {
      const response = await fetch(url, options);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || response.statusText);
      return body;
    }

    async function pickPath(target, kind, title, filetypes) {
      notice.textContent = "";
      const data = await requestJson("/api/pick-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, title, filetypes: filetypes || [] }),
      });
      if (data.path) target.value = data.path;
    }

    async function refreshJob() {
      if (!activeJobId) return;
      const data = await requestJson(`/api/jobs/${activeJobId}`);
      renderJob(data.job);
      button.disabled = data.job.status === "queued" || data.job.status === "running";
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      notice.textContent = "";
      button.disabled = true;
      const payload = {
        inputRoot: form.inputRoot.value,
        outputRoot: form.outputRoot.value,
        excludeRegexes: form.excludeRegexes.value,
      };
      try {
        const data = await requestJson("/api/msg/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        activeJobId = data.jobId;
        await refreshJob();
      } catch (error) {
        notice.textContent = error instanceof Error ? error.message : String(error);
        button.disabled = false;
      }
    });

    document.getElementById("pick-input-dir").addEventListener("click", () => {
      pickPath(form.inputRoot, "directory", "选择包含 .msg.23 的目录").catch((error) => {
        notice.textContent = error instanceof Error ? error.message : String(error);
      });
    });
    document.getElementById("pick-input-file").addEventListener("click", () => {
      pickPath(form.inputRoot, "file", "选择 .msg.23 文件", [["msg 文件", "*.msg.23"], ["所有文件", "*.*"]]).catch((error) => {
        notice.textContent = error instanceof Error ? error.message : String(error);
      });
    });
    document.getElementById("pick-output-dir").addEventListener("click", () => {
      pickPath(form.outputRoot, "directory", "选择 JSON 输出目录").catch((error) => {
        notice.textContent = error instanceof Error ? error.message : String(error);
      });
    });

    window.setInterval(() => { refreshJob().catch(() => {}); }, 1200);
  </script>
</body>
</html>
"""


LogFn = Callable[[str], None]


class MsgConversionRunner:
    """把 MSG 页面提交的参数转换为 `MsgConverter` 调用。"""

    def __init__(self, root_dir: str | Path) -> None:
        """保存项目脚本定位 REMSG_Converter 所需的根目录。"""
        self.root_dir = Path(root_dir).expanduser().resolve()

    def run_export(self, payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
        """执行 `.msg.23` 到 JSON 的转换任务。"""
        # Web 端只负责解析路径和提交任务，实际转换仍复用根目录现有包装器。
        input_root = self._path_value(payload, "inputRoot", "输入目录或文件")
        output_root = self._path_value(payload, "outputRoot", "JSON 输出目录")
        exclude_regexes = self._exclude_regexes(payload)

        # 输出目录不做清空处理；MsgConverter 会按需创建并覆盖同名输出文件。
        self._ensure_existing_path(input_root, "输入目录或文件")

        log(f"输入：{input_root}")
        log(f"输出：{output_root}")
        if exclude_regexes:
            log(f"排除规则：{len(exclude_regexes)} 条")

        # 延迟导入可以避免仅启动网页或查看 --help 时加载第三方转换依赖。
        from msg_converter import MsgConverter

        converter = MsgConverter(
            input_root=input_root,
            output_root=output_root,
            converter_root=self.root_dir / "REMSG_Converter",
            exclude_regexes=exclude_regexes,
        )
        result = converter.run()
        log(f".msg.23 转换完成：{json.dumps(result, ensure_ascii=False)}")
        return {"msg": result, "outputDir": str(output_root)}

    def _path_value(self, payload: dict[str, Any], key: str, label: str) -> Path:
        """读取必填路径，并要求用户通过选择按钮提供绝对路径。"""
        path = Path(self._text_value(payload, key, label)).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{label}必须通过选择按钮提供绝对路径")
        return path

    @staticmethod
    def _text_value(payload: dict[str, Any], key: str, label: str) -> str:
        """读取必填文本参数，允许用户粘贴带双引号的路径。"""
        value = payload.get(key)
        if value is None:
            raise ValueError(f"缺少参数：{label}")
        text = str(value).strip().strip('"')
        if not text:
            raise ValueError(f"缺少参数：{label}")
        return text

    @staticmethod
    def _ensure_existing_path(path: Path, label: str) -> None:
        """校验输入路径存在，可以是目录也可以是单个文件。"""
        if not path.exists():
            raise FileNotFoundError(f"{label}不存在：{path}")

    @staticmethod
    def _exclude_regexes(payload: dict[str, Any]) -> list[str]:
        """解析排除正则，文本域中每一行视为一条正则。"""
        raw = payload.get("excludeRegexes", "")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [line.strip() for line in str(raw).splitlines() if line.strip()]


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """允许复用刚释放端口的多线程 HTTP 服务。"""

    allow_reuse_address = True


def make_project_handler(
    settings: WebSettings,
    jobs: JobStore,
    user3_runner: ConversionRunners,
    msg_runner: MsgConversionRunner,
) -> type[BaseHTTPRequestHandler]:
    """创建同时支持 User3 页面和 MSG 页面请求的处理类。"""
    base_handler = make_handler(settings, jobs, user3_runner)

    class ProjectWebHandler(base_handler):
        """根目录脚本专属的 Web 处理器。"""

        def do_GET(self) -> None:
            """在库内路由之外，额外提供 `/msg` 页面。"""
            path = urlparse(self.path).path
            if path == "/msg":
                self._send_html(MSG_PAGE)
                return
            if path == "/api/jobs":
                # 库内 Vue 页面只显示 .user.3 导出任务。这里过滤掉 msg
                # 任务，避免主页面混入项目扩展任务。
                visible_jobs = [job for job in jobs.list_jobs() if job.kind == "export"]
                self._send_json(
                    200,
                    {
                        "jobs": [
                            jobs.serialize(job, include_logs=False)
                            for job in visible_jobs
                        ],
                        "rootDir": str(settings.root_dir),
                    },
                )
                return
            super().do_GET()

        def do_POST(self) -> None:
            """在库内 API 之外，额外提供 MSG 转换任务提交接口。"""
            path = urlparse(self.path).path
            if path == "/api/msg/export":
                try:
                    payload = self._read_json()
                    job = jobs.start("msg", payload, msg_runner.run_export)
                    self._send_json(202, {"jobId": job.id})
                except Exception as exc:
                    self._send_json(
                        400,
                        {"error": f"{exc.__class__.__name__}: {exc}"},
                    )
                return
            super().do_POST()

    return ProjectWebHandler


def run_project_server(settings: WebSettings) -> None:
    """启动包含 `.user.3` 和 `.msg.23` 两套页面的项目 Web 服务。"""
    # 根目录只用于定位项目内的 REMSG_Converter；用户输入路径必须自行选择。
    settings = settings.with_resolved_root()
    jobs = JobStore(max_jobs=settings.max_jobs)
    user3_runner = ConversionRunners(settings.root_dir)
    msg_runner = MsgConversionRunner(settings.root_dir)
    handler = make_project_handler(settings, jobs, user3_runner, msg_runner)

    server = ReusableThreadingHTTPServer((settings.host, settings.port), handler)
    url = f"http://{settings.host}:{settings.port}/"
    print(f"RE User3 JSON Web 正在运行：{url}")
    print(f"MSG 转换页面：{url}msg")
    print("网页路径不会自动使用项目根目录，请在页面中手动选择。")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        server.server_close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析项目 Web 服务命令行参数。"""
    parser = argparse.ArgumentParser(description="启动项目本地 Web UI。")
    parser.add_argument("--host", default="127.0.0.1", help="监听主机。")
    parser.add_argument("--port", type=int, default=8765, help="监听端口。")
    parser.add_argument(
        "--root-dir",
        default=str(Path.cwd()),
        help="兼容配置；网页路径仍需通过选择按钮提供绝对路径。",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=50,
        help="内存中保留的最大任务数量。",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """命令行入口。"""
    args = parse_args(argv)
    run_project_server(
        WebSettings(
            host=args.host,
            port=args.port,
            root_dir=Path(args.root_dir),
            max_jobs=args.max_jobs,
        )
    )


if __name__ == "__main__":
    main()
