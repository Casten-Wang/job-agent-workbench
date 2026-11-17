"""Continue the one-note check on the domain actually opened after sign-in."""

import asyncio
import json
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

import verify_mediacrawler as trial
from var import crawler_type_var


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp("http://127.0.0.1:18637")
        context = browser.contexts[0]
        pages = [page for page in context.pages if urlsplit(page.url).hostname in {
            "www.xiaohongshu.com", "www.rednote.com"
        }]
        page = pages[-1]
        trial.config.XHS_INTERNATIONAL = urlsplit(page.url).hostname == "www.rednote.com"
        crawler = trial.SingleNoteCrawler()
        crawler.browser_context = context
        crawler.context_page = page
        crawler.xhs_client = await crawler.create_xhs_client(None)
        crawler_type_var.set("search")
        trial.record("checking_api_login", page_host=urlsplit(page.url).hostname)
        try:
            await crawler.search()
        except Exception as error:
            trial.record("not_completed", error_type=type(error).__name__)
            raise
        finally:
            (trial.OUTPUT / "current-domain-http-results.json").write_text(
                json.dumps(trial.http_results, ensure_ascii=False, indent=2), encoding="utf-8"
            )


if __name__ == "__main__":
    asyncio.run(main())
