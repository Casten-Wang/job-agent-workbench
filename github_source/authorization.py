"""GitHub device authorization. Tokens never cross the local HTTP boundary."""

import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

import httpx

from .github_api import GitHubError
from .tls import tls_context


def _protect(data, decrypt=False):
    if os.name != "nt":
        return data

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise GitHubError("无法读取本机 GitHub 登录，请重新授权")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


class GitHubAuthorization:
    def __init__(self, directory, *, client=None, clock=time.monotonic):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(timeout=30, follow_redirects=False, verify=tls_context())
        self.clock = clock
        self.pending = None
        self.lock = threading.Lock()
        self.config_file = self.directory / "github-app.json"
        self.token_file = self.directory / "github-login.bin"

    def client_id(self):
        configured = os.environ.get("OFFERPILOT_GITHUB_CLIENT_ID", "")
        if not configured and self.config_file.is_file():
            configured = json.loads(self.config_file.read_text(encoding="utf-8")).get("client_id", "")
        return configured

    def configure(self, client_id):
        if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{10,100}", client_id):
            raise GitHubError("请输入 GitHub OAuth App 的 Client ID，不是 Client Secret 或访问令牌")
        if client_id.startswith(("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_")) or re.fullmatch(r"[a-fA-F0-9]{40}", client_id):
            raise GitHubError("这里需要公开的 Client ID，请勿填写 Secret 或访问令牌")
        with self.lock:
            if self.client_id() != client_id:
                self.pending = None
                self.token_file.unlink(missing_ok=True)
            self.config_file.write_text(json.dumps({"client_id": client_id}), encoding="utf-8")
        return self.status()

    def _credentials(self):
        if not self.token_file.is_file():
            return None
        try:
            value = json.loads(_protect(self.token_file.read_bytes(), decrypt=True))
        except (ValueError, OSError):
            raise GitHubError("GitHub 本机登录记录不可用，请重新授权") from None
        if value.get("expires_at") and time.time() >= value["expires_at"]:
            return None
        return value

    def token(self):
        value = self._credentials()
        if not value:
            raise GitHubError("请先连接 GitHub")
        return value["access_token"]

    def status(self):
        value = self._credentials()
        return {"configured": bool(self.client_id()), "connected": bool(value),
                "login": value["login"] if value else None, "expires_at": value.get("expires_at") if value else None,
                "authorization_kind": "oauth_device_flow"}

    def _json(self, method, url, **kwargs):
        try:
            response = self.client.request(method, url, headers={"Accept": "application/json"}, **kwargs)
            if response.status_code >= 400:
                raise GitHubError(f"GitHub 请求失败（HTTP {response.status_code}），请检查网络、授权或组织访问限制")
            return response.json()
        except (httpx.TransportError, ValueError):
            raise GitHubError("GitHub 连接失败，请检查网络后重试") from None

    def start(self):
        with self.lock:
            client_id = self.client_id()
            if not client_id:
                raise GitHubError("首次连接需要配置自己的 GitHub OAuth App Client ID，并启用 Device Flow")
            data = self._json("POST", "https://github.com/login/device/code",
                              data={"client_id": client_id, "scope": "repo read:user"})
            if data.get("error"):
                raise GitHubError("GitHub 登录应用未就绪，请检查 Client ID 并启用 Device Flow")
            try:
                interval = max(5, int(data["interval"]))
                expires = min(900, int(data["expires_in"]))
                if data["verification_uri"] != "https://github.com/login/device" or expires <= 0:
                    raise ValueError("Unexpected authorization URL")
                ticket = secrets.token_urlsafe(24)
                self.pending = {"ticket": ticket, "device_code": data["device_code"], "client_id": client_id,
                                "interval": interval, "next_poll": self.clock() + interval,
                                "expires_at": self.clock() + expires}
                return {"ticket": ticket, "user_code": data["user_code"], "verification_uri": data["verification_uri"],
                        "interval": interval, "expires_in": expires}
            except (KeyError, ValueError, TypeError):
                raise GitHubError("GitHub 授权响应不完整，请重新连接") from None

    def poll(self, ticket):
        with self.lock:
            value = self.pending
            if not value or not secrets.compare_digest(str(ticket), value["ticket"]):
                raise GitHubError("授权请求已失效，请重新连接 GitHub")
            now = self.clock()
            if now >= value["expires_at"]:
                self.pending = None
                return {"status": "expired"}
            if now < value["next_poll"]:
                return {"status": "pending", "interval": value["interval"]}
            value["next_poll"] = now + value["interval"]
            data = self._json("POST", "https://github.com/login/oauth/access_token", data={
                "client_id": value["client_id"], "device_code": value["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            error = data.get("error")
            if error in {"authorization_pending", "slow_down"}:
                if error == "slow_down":
                    value["interval"] += 5
                    value["next_poll"] = now + value["interval"]
                return {"status": "pending", "interval": value["interval"]}
            if error or not data.get("access_token"):
                self.pending = None
                return {"status": "denied" if error == "access_denied" else "expired"}
            token = data["access_token"]
            try:
                response = self.client.get("https://api.github.com/user", headers={"Authorization": "Bearer " + token,
                                           "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})
                response.raise_for_status()
                account = response.json()
                login = account["login"]
                if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
                    raise ValueError("Invalid login")
            except (httpx.HTTPError, ValueError, KeyError):
                raise GitHubError("已收到授权，但 GitHub 账号确认失败，请重新连接") from None
            record = {"access_token": token, "login": login,
                      "expires_at": time.time() + int(data["expires_in"]) if data.get("expires_in") else None}
            encoded = _protect(json.dumps(record).encode("utf-8"))
            descriptor = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
            self.pending = None
            return {"status": "connected", **self.status()}

    def disconnect(self):
        with self.lock:
            self.pending = None
            self.token_file.unlink(missing_ok=True)
        return {"connected": False, "note": "已断开本机连接；GitHub 授权可在账号设置中撤销"}

    def close(self):
        self.client.close()
