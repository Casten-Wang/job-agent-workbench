"""公网展示部署模式（魔搭创空间 / 任意容器）。

默认关闭：工作台只监听 127.0.0.1（见 CLAUDE.md §1）。只有设置环境变量
``OFFERPILOT_DEPLOY=1``（由 ``tools/run_career_demo.py --deploy`` 设置）才启用本模式。

本模式把工作台放到别人的服务器上给访客体验，所以同时收紧三件事：

1. 不连接任何招聘平台：容器里没有浏览器、没有账号，岗位采集、HR 回复、投递、
   测试、导出这些入口一律拒绝（返回 403 与清楚的中文说明）。
2. 模型密钥只来自部署环境的密钥变量，访客不能查看、保存或测试 AI 接口设置。
3. 访客共用一个演示数据空间，并对会调用模型的请求按来源限频，避免耗尽额度。

本文件只含判断逻辑与常量，不起服务、不读写用户数据。
"""

from __future__ import annotations

import os
import threading
import time
import urllib.parse
from typing import Any

ENV_FLAG = "OFFERPILOT_DEPLOY"
# 部署环境的密钥变量（魔搭「设置 > 环境变量」里按 secrets 配置）。
ENV_MODEL_KEY = "OFFERPILOT_MODEL_API_KEY"
ENV_MODEL_BASE_URL = "OFFERPILOT_MODEL_BASE_URL"
ENV_MODEL_NAME = "OFFERPILOT_MODEL_NAME"
ENV_MODEL_SERVICE = "OFFERPILOT_MODEL_SERVICE"

BLOCKED_MESSAGE = "公网展示版不连接招聘平台、不写入模型密钥，这个功能请在本机完整版使用"

# 这些 POST 路径在展示版里直接拒绝。
BLOCKED_POST_PATHS = frozenset({
    "/api/run-tests",
    "/api/export",
    "/api/offerpilot/preflight",
    "/api/offerpilot/tasks",
    "/api/offerpilot/conversations/sync",
    "/api/pipeline/event",
})
BLOCKED_POST_PREFIXES = ("/api/offerpilot/tasks/",)

# /api/action 里拒绝的动作：所有 offerpilot-*（平台自动化）与 AI 接口设置写入/测试。
BLOCKED_ACTIONS = frozenset({
    "save-ai-settings",
    "test-ai-connection",
    "pipeline-event",
})

# 会调用模型的路径前缀；按来源限频。
MODEL_PATH_PREFIXES = (
    "/api/workbench-agent/",
    "/api/career-user/",
    "/api/resume-agent/",
    "/api/interview-agent/",
    "/api/interview/stream",
)
MODEL_ACTIONS = frozenset({
    "interview-start", "interview-reply", "interview-end", "interview-drill",
    "generate-job-greetings", "import-profile-cv", "interview-material-upload",
})
PER_CLIENT_LIMIT = 40        # 每个来源每个窗口最多这么多次调用模型的请求
GLOBAL_LIMIT = 600           # 全站每个窗口上限
WINDOW_SECONDS = 600


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip() == "1"


def listen_port(default: int = 7860) -> int:
    """魔搭 Docker 创空间要求监听 7860；其他平台通常通过 PORT 指定。"""
    raw = os.environ.get("PORT", "").strip()
    return int(raw) if raw.isdigit() and 0 < int(raw) < 65536 else default


def same_origin(host_header: str, origin: str | None) -> bool:
    """展示版不限定域名，但跨站请求（Origin 与 Host 不一致）一律拒绝。"""
    host = (host_header or "").strip().lower()
    if not host:
        return False
    if not origin:
        return True
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return parsed.netloc.lower() == host


def frame_ancestors() -> str:
    """魔搭把创空间嵌在自己的页面里，需要放行它的域名；其余来源仍禁止嵌入。"""
    return "frame-ancestors https://modelscope.cn https://*.modelscope.cn https://modelscope.ai https://*.modelscope.ai"


def blocked_reason(path: str, payload: dict[str, Any] | None = None) -> str | None:
    """返回拒绝原因；允许时返回 None。"""
    if path in BLOCKED_POST_PATHS or path.startswith(BLOCKED_POST_PREFIXES):
        return BLOCKED_MESSAGE
    if path == "/api/action":
        action = str((payload or {}).get("action") or "")
        if action.startswith("offerpilot-") or action in BLOCKED_ACTIONS:
            return BLOCKED_MESSAGE
    return None


def uses_model(path: str, payload: dict[str, Any] | None = None) -> bool:
    if path.startswith(MODEL_PATH_PREFIXES):
        return True
    return path == "/api/action" and str((payload or {}).get("action") or "") in MODEL_ACTIONS


class RateLimiter:
    """固定窗口计数；进程内、够用即可。"""

    def __init__(self, per_client: int = PER_CLIENT_LIMIT, total: int = GLOBAL_LIMIT,
                 window: int = WINDOW_SECONDS, clock=time.monotonic) -> None:
        self.per_client, self.total, self.window, self.clock = per_client, total, window, clock
        self._lock = threading.Lock()
        self._start = clock()
        self._counts: dict[str, int] = {}
        self._all = 0

    def allow(self, client: str) -> bool:
        with self._lock:
            now = self.clock()
            if now - self._start >= self.window:
                self._start, self._counts, self._all = now, {}, 0
            if self._all >= self.total or self._counts.get(client, 0) >= self.per_client:
                return False
            self._counts[client] = self._counts.get(client, 0) + 1
            self._all += 1
            return True


limiter = RateLimiter()


def client_id(headers: Any, peer: str) -> str:
    """反向代理后取 X-Forwarded-For 的第一段；取不到就用连接对端地址。"""
    forwarded = str(headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return (forwarded or peer or "unknown")[:64]


def seed_model_from_env(env: dict[str, str] | None = None) -> bool:
    """用部署环境变量写入模型配置（密钥进被忽略的凭据文件，不进仓库）。

    没有设置密钥变量时什么都不做，返回 False（演示版仍可浏览，模型功能显示未配置）。
    """
    env = os.environ if env is None else env
    key = (env.get(ENV_MODEL_KEY) or "").strip()
    if not key:
        return False
    import offerpilot_runtime

    offerpilot_runtime.save_ai_settings({
        "service": (env.get(ENV_MODEL_SERVICE) or "custom").strip().lower(),
        "model": (env.get(ENV_MODEL_NAME) or "").strip(),
        "base_url": (env.get(ENV_MODEL_BASE_URL) or "").strip(),
        "api_key": key,
    })
    return True


def seed_showcase_data() -> bool:
    """展示版第一次启动时，用仓库里明显虚构的 demo/ 数据填充空工作台；已有数据不动。"""
    import sys
    from pathlib import Path

    tests = Path(__file__).resolve().parents[1] / "tools" / "tests"
    if str(tests) not in sys.path:
        sys.path.insert(0, str(tests))
    import backend
    import local_fixtures

    store = backend.get_store("user")
    if store.jobs():
        return False
    local_fixtures.seed_local_data(store)
    return True
