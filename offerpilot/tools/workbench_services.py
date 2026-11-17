"""Model configuration without restarting the local workspace or its tasks."""

import asyncio
import json
import os
from pathlib import Path
import threading

from local_secrets import load, save


class ModelSettings:
    def __init__(self, root, *, offline=False):
        self.path = Path(root) / "web/data/user/career-agent/model-credentials.dpapi.json"
        self.lock = threading.RLock()
        self.models = []
        self.revision = 0
        self.pending_key = None
        self.active_key = None if offline else next((os.environ[k] for k in
            ("INTERVIEW_API_KEY", "STEP_API_KEY", "STEPFUN_API_KEY") if os.getenv(k)), None)
        if not self.active_key and not offline:
            self.active_key = load(self.path).get("step_api_key")
        if self.active_key:
            os.environ["INTERVIEW_API_KEY"] = self.active_key
        import interview_agent
        self.provider = json.loads(Path(interview_agent.__file__).with_name("provider.json").read_text(encoding="utf-8"))
        self.generation = {"provider": os.getenv("INTERVIEW_PROVIDER") or self.provider["provider"],
                           "model": os.getenv("INTERVIEW_MODEL") or self.provider["model"], "kind": "live_model"}

    def model(self):
        model = ConfigurableModel(self)
        self.models.append(model)
        return model

    def model_config(self):
        if not self.active_key:
            return None
        return {"service": "custom", "api_key": self.active_key,
                "base_url": os.getenv("INTERVIEW_BASE_URL") or self.provider["base_url"],
                "model": self.generation["model"]}

    def status(self):
        with self.lock:
            return {"configured": bool(self.active_key), "pending": self.pending_key is not None,
                    "can_configure": True, "model": self.generation["model"],
                    "message": "配置已验证，当前任务结束后自动应用。" if self.pending_key else
                               "模型凭据已配置。" if self.active_key else "配置模型后可导入简历、生成申请材料和进行面试。"}

    def idle(self):
        return all(m.active_calls == 0 and not m.is_busy() for m in self.models)

    def configured_environment(self, key):
        return {**os.environ, "INTERVIEW_API_KEY": key}

    async def validate(self, key):
        from interview_agent.model_adapter import ModelAdapter
        adapter = await ModelAdapter(self.configured_environment(key), timeout=25).start()
        try:
            await adapter._decide_untraced("workbench_decide", {
                "messages": [{"role": "user", "text": "连接测试。只选择 reply，message 填写连接成功。"}],
                "tools": [], "observations": []})
        finally:
            await adapter.close()

    def configure(self, key):
        from backend import ApiError
        try:
            asyncio.run(self.validate(key))
        except Exception as error:
            code = getattr(error, "code", "model_connection_failed")
            message = {"provider_http_401": "密钥无效，请核对后重试。", "provider_http_403": "模型账号没有访问权限。",
                       "provider_http_429": "模型服务限流，请稍后重试。", "model_timeout": "连接验证超时，原配置保留。"}.get(code, "模型连接验证未通过，原配置保留。")
            raise ApiError(message, 400) from None
        with self.lock:
            stored = load(self.path)
            stored["step_api_key"] = key
            try:
                save(self.path, stored)
            except OSError:
                raise ApiError("无法保存本机加密配置，原运行配置保留。", 503) from None
            self.pending_key = key
            self.revision += 1
        return self.status()

    def applied(self):
        with self.lock:
            if self.pending_key and all(m.applied_revision == self.revision for m in self.models):
                self.active_key, self.pending_key = self.pending_key, None
                os.environ["INTERVIEW_API_KEY"] = self.active_key


class ConfigurableModel:
    managed = True

    def __init__(self, settings):
        self.settings = settings
        self.generation = settings.generation
        self.delegate = None
        self.active_calls = 0
        self.is_busy = lambda: False
        self.applied_revision = settings.revision
        self.monitor = None

    async def start(self):
        if self.settings.active_key:
            from interview_agent.model_adapter import ModelAdapter
            self.delegate = await ModelAdapter(self.settings.configured_environment(self.settings.active_key)).start()
        self.monitor = asyncio.create_task(self.watch())
        return self

    async def watch(self):
        while True:
            await asyncio.sleep(0.25)
            with self.settings.lock:
                key, revision = self.settings.pending_key, self.settings.revision
            if key and revision != self.applied_revision and self.settings.idle():
                from interview_agent.model_adapter import ModelAdapter
                replacement = await ModelAdapter(self.settings.configured_environment(key)).start()
                previous, self.delegate = self.delegate, replacement
                self.applied_revision = revision
                if previous:
                    await previous.close()
                self.settings.applied()

    async def decide(self, stage, value, **kwargs):
        from interview_agent.model_adapter import ModelError
        if self.delegate is None:
            raise ModelError("missing_model_credential")
        self.active_calls += 1
        try:
            return await self.delegate.decide(stage, value, **kwargs)
        finally:
            self.active_calls -= 1

    async def decide_stream(self, stage, value, on_text):
        return await self.decide(stage, value, on_text=on_text)

    async def close(self):
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
        if self.delegate:
            await self.delegate.close()
