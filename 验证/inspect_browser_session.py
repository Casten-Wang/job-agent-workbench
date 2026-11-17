"""Compare the website's normal requests using the existing validation profile."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PROFILE = ROOT / "MediaCrawler-source" / "browser_data" / "cdp_single_note_xhs"
os.environ["NO_PROXY"] = ",".join(filter(None, [
    os.environ.get("NO_PROXY", ""), "localhost", "127.0.0.1", "::1"
]))


async def main():
    observations = []
    self_info_seen = asyncio.Event()

    async def observe(response):
        url = urlsplit(response.url)
        if url.hostname != "webapi.rednote.com" or not url.path.startswith("/api/sns/"):
            return
        item = {"host": url.hostname, "path": url.path, "http_status": response.status}
        try:
            data = await response.json()
            item.update({key: data.get(key) for key in ("success", "code", "msg")})
            if url.path.endswith(("/user/selfinfo", "/user/me")):
                info = data.get("data") or {}
                item["data_fields"] = list(info) if isinstance(info, dict) else []
                result = info.get("result") if isinstance(info, dict) else None
                if isinstance(result, dict):
                    item["result_success"] = result.get("success")
                if isinstance(info, dict):
                    item["guest"] = info.get("guest")
        except Exception:
            item["json_response_readable"] = False
        observations.append(item)
        if url.path.endswith(("/user/selfinfo", "/user/me")):
            self_info_seen.set()

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="msedge", headless=False,
        )
        try:
            page = await context.new_page()
            page.on("response", observe)
            await page.goto("https://www.rednote.com/", wait_until="domcontentloaded")
            try:
                await asyncio.wait_for(self_info_seen.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(2)
            import verify_mediacrawler as trial
            crawler = trial.SingleNoteCrawler()
            crawler.browser_context = context
            crawler.context_page = page
            client = await crawler.create_xhs_client(None)
            try:
                me = await client.get("/api/sns/web/v2/user/me", params={})
                client_result = {
                    "request_succeeded": True,
                    "guest": me.get("guest"),
                    "data_fields": list(me),
                }
            except Exception as error:
                client_result = {"request_succeeded": False, "error_type": type(error).__name__}
            state = {
                "qr_visible": await page.locator("img.qrcode-img").is_visible(),
                "client_current_me_endpoint": client_result,
                "responses": observations,
            }
            (OUTPUT / "website-session-comparison.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            await page.screenshot(path=str(OUTPUT / "website-session-comparison.png"))
            print(json.dumps(state, ensure_ascii=False), flush=True)
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
