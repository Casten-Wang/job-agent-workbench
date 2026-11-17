"""One-note, non-commercial research check using the pinned MediaCrawler source."""

import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import traceback
from time import time_ns
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "MediaCrawler-source"
OUTPUT = ROOT / "output"
KEYWORD = "校招 后端 面经"
sys.path.insert(0, str(SOURCE))
os.chdir(SOURCE)
os.environ["NO_PROXY"] = ",".join(filter(None, [
    os.environ.get("NO_PROXY", ""), "localhost", "127.0.0.1", "::1"
]))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
OUTPUT.mkdir(exist_ok=True)

import config
from media_platform.xhs.core import XiaoHongShuCrawler
from media_platform.xhs.field import SearchNoteType, SearchSortType
from media_platform.xhs.help import get_search_id
from media_platform.xhs.login import XiaoHongShuLogin
from PIL import Image
from store import xhs as xhs_store
from tools import utils
from var import source_keyword_var
import live_login
import media_platform.xhs.client as xhs_client_module

config.ENABLE_CDP_MODE = True
config.XHS_INTERNATIONAL = False
config.CDP_CONNECT_EXISTING = False
config.CDP_DEBUG_PORT = 18637
config.CUSTOM_BROWSER_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
config.USER_DATA_DIR = "single_note_%s"
config.SAVE_LOGIN_STATE = True
config.HEADLESS = False
config.CDP_HEADLESS = False
config.LOGIN_TYPE = "qrcode"
config.KEYWORDS = KEYWORD
config.CRAWLER_TYPE = "search"
config.MAX_CONCURRENCY_NUM = 1
config.ENABLE_IP_PROXY = False
config.ENABLE_GET_COMMENTS = False
config.ENABLE_GET_SUB_COMMENTS = False
config.ENABLE_GET_MEDIA = True
config.DOWNLOAD_LIVE_PHOTO = False
config.SAVE_DATA_OPTION = "jsonl"
config.SAVE_DATA_PATH = str(OUTPUT)
logging.getLogger("MediaCrawler").setLevel(logging.WARNING)

http_results = []
original_make_async_client = xhs_client_module.make_async_client


async def capture_api_result(response):
    await response.aread()
    item = {
        "url": f"{response.url.scheme}://{response.url.host}{response.url.path}",
        "http_status": response.status_code,
    }
    try:
        data = response.json()
        item.update({key: data.get(key) for key in ("success", "code", "msg")})
        if response.url.path.endswith(("/user/selfinfo", "/user/me")):
            info = data.get("data") or {}
            item["data_fields"] = list(info) if isinstance(info, dict) else []
            result = info.get("result", {}) if isinstance(info, dict) else {}
            item["result_success"] = result.get("success") if isinstance(result, dict) else None
            item["guest"] = info.get("guest") if isinstance(info, dict) else None
    except (ValueError, AttributeError):
        item["json_response"] = False
    http_results.append(item)
    (OUTPUT / "retry-http-results.json").write_text(
        json.dumps(http_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"api_result": item}, ensure_ascii=False), flush=True)


def observed_client(**kwargs):
    kwargs["event_hooks"] = {"response": [capture_api_result]}
    return original_make_async_client(**kwargs)


xhs_client_module.make_async_client = observed_client
# This diagnostic retry sends each API request once, without the upstream retry loop.
xhs_client_module.XiaoHongShuClient.request = xhs_client_module.XiaoHongShuClient.request.__wrapped__


async def current_user_info(self):
    return await self.get("/api/sns/web/v2/user/me", params={})


async def current_login_check(self):
    try:
        host = urlsplit(self.playwright_page.url).hostname
        api_hosts = {
            "www.xiaohongshu.com": "https://edith.xiaohongshu.com",
            "www.rednote.com": "https://webapi.rednote.com",
        }
        if host in api_hosts:
            self._domain = "https://" + host
            self._host = api_hosts[host]
            self.cookie_urls = [self._domain]
            self.headers["origin"] = self._domain
            self.headers["referer"] = self._domain + "/"
            config.XHS_INTERNATIONAL = host == "www.rednote.com"
        await self.update_cookies(self.playwright_page.context, urls=[self._host])
        me = await self.query_self()
        return isinstance(me, dict) and me.get("guest") is False
    except Exception:
        return False


# Match the current website's endpoint and explicitly reject guest sessions.
xhs_client_module.XiaoHongShuClient.query_self = current_user_info
xhs_client_module.XiaoHongShuClient.pong = current_login_check


def record(stage, **details):
    result = {"stage": stage, **details}
    (OUTPUT / "status.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


def save_login_qr(value):
    encoded = value.split(",", 1)[-1]
    path = OUTPUT / f"login-qr-{time_ns()}.png"
    raw = base64.b64decode(encoded)
    path.write_bytes(raw)
    (OUTPUT / "login-qr.png").write_bytes(raw)
    record("waiting_for_user_login", qr_path=str(path))


utils.show_qrcode = save_login_qr


async def live_qrcode_login(self, client):
    async def publish_qr():
        encoded = await utils.find_login_qrcode(
            self.context_page, selector="xpath=//img[@class='qrcode-img']"
        )
        if not encoded:
            raise RuntimeError("No login QR code found on the current page")
        save_login_qr(encoded)

    await publish_qr()
    deadline = asyncio.get_running_loop().time() + 1800
    next_login_check = 0
    while asyncio.get_running_loop().time() < deadline:
        if live_login.refresh_requested.is_set():
            live_login.refresh_requested.clear()
            record("refreshing_login_qr")
            await self.context_page.reload(wait_until="domcontentloaded")
            await publish_qr()
        now = asyncio.get_running_loop().time()
        if now >= next_login_check:
            if await client.pong():
                record("browser_login_confirmed")
                return
            next_login_check = now + 15
        await asyncio.sleep(1)
    raise TimeoutError("Login was not confirmed within 30 minutes")


async def capture_browser_login(response):
    if response.url.split("?", 1)[0] != "https://webapi.rednote.com/api/sns/web/v2/user/me":
        return
    try:
        payload = await response.json()
        state = {
            "http_status": response.status,
            "success": payload.get("success"), "code": payload.get("code"),
            "guest": (payload.get("data") or {}).get("guest"),
        }
        (OUTPUT / "browser-auth-state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"website_auth": state}), flush=True)
    except Exception:
        pass


class SingleNoteCrawler(XiaoHongShuCrawler):
    async def launch_browser_with_cdp(self, *args, **kwargs):
        context = await super().launch_browser_with_cdp(*args, **kwargs)
        context.on("response", capture_browser_login)
        return context

    async def search(self):
        source_keyword_var.set(KEYWORD)
        record("checking_api_login")
        if not await self.xhs_client.pong():
            raise RuntimeError("API login check rejected the session; search was not sent")
        record("authenticated_searching", keyword=KEYWORD)
        response = await self.xhs_client.get_note_by_keyword(
            keyword=KEYWORD,
            search_id=get_search_id(),
            page=1,
            sort=SearchSortType.GENERAL,
            note_type=SearchNoteType.IMAGE,
        )
        candidates = [
            item for item in response.get("items", [])
            if item.get("model_type") == "note" and item.get("xsec_token")
        ]
        if not candidates:
            raise RuntimeError("Search returned no readable note candidates")
        item = candidates[0]
        record("fetching_one_note", candidate_count=len(candidates))
        note = await self.get_note_detail_async_task(
            note_id=item["id"],
            xsec_source=item.get("xsec_source") or "pc_search",
            xsec_token=item["xsec_token"],
            semaphore=asyncio.Semaphore(1),
        )
        if not note:
            raise RuntimeError("The selected note could not be retrieved")
        await xhs_store.update_xhs_note(note)
        record("downloading_images", note_id=note["note_id"])
        await self.download_media(note)
        directory = OUTPUT / "xhs" / "media" / note["note_id"]
        images = []
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}:
                continue
            with Image.open(path) as image:
                size = image.size
                image_format = image.format
                image.verify()
            images.append({
                "path": str(path), "width": size[0], "height": size[1],
                "format": image_format,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        if not images:
            raise RuntimeError("Note data was obtained but no valid image was downloaded")
        expected_images = len(note.get("image_list") or [])
        if len(images) != expected_images:
            raise RuntimeError("The downloaded image count does not match the note")
        summary = {
            "source_commit": "306ab4ca26c0e44fb87ede0e40e98748752815a6",
            "note_id": note["note_id"], "title": note.get("title", ""),
            "body_characters": len(note.get("desc", "")),
            "source_url": "https://www.xiaohongshu.com/explore/" + note["note_id"],
            "images": images, "expected_image_count": expected_images,
            "image_text_extraction": "not yet tested",
        }
        (OUTPUT / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        record("note_and_images_verified", title=summary["title"],
               body_characters=summary["body_characters"], image_count=len(images))


async def main():
    crawler = SingleNoteCrawler()

    async def login_for_crawler(login):
        await live_qrcode_login(login, crawler.xhs_client)

    XiaoHongShuLogin.login_by_qrcode = login_for_crawler
    record("starting", keyword=KEYWORD, scope="one note, no comments")
    login_server = live_login.start()
    print(json.dumps({"login_page": live_login.URL}), flush=True)
    try:
        await crawler.start()
    finally:
        if getattr(crawler, "browser_context", None):
            await crawler.close()
        login_server.shutdown()
        login_server.server_close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (Exception, SystemExit) as error:
        (OUTPUT / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        record("not_completed", error_type=type(error).__name__,
               detail_log=str(OUTPUT / "failure.log"))
        raise SystemExit(1)
