"""Model configuration without restarting the local workspace or its tasks."""

import asyncio
import json
import os
from pathlib import Path
import threading


class ModelSettings:
    def __init__(self, root, *, offline=False):
        self.lock = threading.RLock()
        self.models = []
        self.revision = 0
        self.pending_key = None
        # 唯一密钥来源：「设置」里的 AI 接口设置；不读环境变量，也不读其他本地凭据文件。
        self.active_key = None
        self.config_signature = None
        self.endpoint = {}
        import interview_agent
        self.provider = json.loads(Path(interview_agent.__file__).with_name("provider.json").read_text(encoding="utf-8"))
        self.generation = {"provider": self.provider["provider"],
                           "model": self.provider["model"], "kind": "live_model"}
        if not self.active_key and not offline:
            self.sync_workbench_config()
            self.active_key, self.pending_key = self.pending_key, None

    def sync_workbench_config(self):
        """Follow the 设置 AI panel: key, model and base URL live in the gitignored OfferPilot config."""
        try:
            import offerpilot_runtime as runtime
            server = runtime.load_backend()
            config = server.load_config(server.CONFIG_PATH)
            ai = config.get("ai") if isinstance(config.get("ai"), dict) else {}
            key, base_url, model = server.get_ai_api_key(config), str(ai.get("base_url") or ""), str(ai.get("model") or "")
        except Exception:
            return
        signature = (key, base_url, model)
        if not key or not base_url or not model or signature == self.config_signature:
            return
        with self.lock:
            self.config_signature = signature
            self.endpoint = {"INTERVIEW_BASE_URL": base_url, "INTERVIEW_MODEL": model,
                             "INTERVIEW_PROVIDER": str(ai.get("service") or "custom")}
            self.generation.update({"provider": self.endpoint["INTERVIEW_PROVIDER"], "model": model})
            self.pending_key = key
            self.revision += 1

    def model(self):
        model = ConfigurableModel(self)
        self.models.append(model)
        return model

    def model_config(self):
        if not self.active_key:
            return None
        return {"service": "custom", "api_key": self.active_key,
                "base_url": self.endpoint.get("INTERVIEW_BASE_URL") or self.provider["base_url"],
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
        # 不继承进程环境里的 INTERVIEW_*/STEP_* 变量，端点与密钥只来自设置入口。
        return {**{k: v for k, v in os.environ.items() if not k.startswith(("INTERVIEW_", "STEP_", "STEPFUN_"))},
                **self.endpoint, "INTERVIEW_API_KEY": key}

    async def validate(self, key):
        from interview_agent.model_adapter import ModelAdapter
        adapter = await ModelAdapter(self.configured_environment(key), timeout=25).start()
        try:
            await adapter._decide_untraced("workbench_decide", {
                "messages": [{"role": "user", "text": "连接测试。只选择 reply，message 填写连接成功。"}],
                "tools": [], "observations": []})
        finally:
            await adapter.close()

    def applied(self):
        with self.lock:
            if self.pending_key and all(m.applied_revision == self.revision for m in self.models):
                self.active_key, self.pending_key = self.pending_key, None


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
        ticks = 0
        while True:
            await asyncio.sleep(0.25)
            ticks += 1
            if ticks % 20 == 0:
                self.settings.sync_workbench_config()
            await self.apply_pending()

    async def apply_pending(self):
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
