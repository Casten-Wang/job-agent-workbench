"""猎聘岗位投递适配器。

猎聘网页版的岗位详情页（``/job/<id>.shtml``）在后台标签页里会被重定向回首页，所以不能像
智联那样直接打开岗位页。可用的入口是搜索页的分栏视图：在搜索结果里点中岗位卡片，右侧详情栏
出现「聊一聊」；点它平台会立刻把**平台预置的打招呼语**发给 HR（例如「您好，我的背景与该职位
要求较为匹配，期待您的进一步了解。」），并弹出聊天窗口，按钮变成「继续聊」。
所以这里发出去的是平台预置的那句，不是工作台生成的招呼语；调用方据此在记录里写
平台实际发送的文字（``sent_text``）。

该流程在 2026-11-18 用真实账号验证过一次（点击后弹出聊天窗口，窗口里出现预置招呼语与「未读」，
详情栏按钮变为「继续聊」）。页面结构以后变化时，宁可报 ``deliver_unconfirmed`` 让用户去猎聘
「我的沟通」核实，也不盲目重试，避免重复发送。
"""

from __future__ import annotations

import json
import random
from typing import Any, Callable
from urllib.parse import quote

from offerpilot.browser import close_tab, evaluate, navigate, new_tab
from offerpilot.platform_safety import PlatformAccessGuard, PlatformSafetyStop

CHAT_BUTTON_TEXT = "聊一聊"
CONTINUE_BUTTON_TEXT = "继续聊"
SEARCH_URL = "https://www.liepin.com/zhaopin/?key={keyword}"
MAX_SEARCH_PAGES = 3
RISK_MARKERS = ("滑动验证", "安全验证", "请完成安全验证", "人机验证", "访问过于频繁")
GREETING_ANCHOR = "了解更多安全防范知识"
GREETING_TAIL = {"未读", "已读", "发简历", "交换手机号", "交换微信号", "发送"}

_PAGE_STATE_JS = f"""
(() => {{
    const text = document.body ? document.body.innerText : '';
    const visible = (el) => {{ const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }};
    const pane = document.querySelector('#search-job-detail');
    const buttons = pane
        ? Array.from(pane.querySelectorAll('button')).filter(visible).map((el) => (el.innerText || '').trim())
        : [];
    const chat = document.querySelector('.im-ui-basic-chat-modal');
    return JSON.stringify({{
        text: text.slice(0, 3000),
        cards: document.querySelectorAll('.job-card-pc-container').length,
        has_pane: !!pane,
        has_chat: buttons.includes({json.dumps(CHAT_BUTTON_TEXT, ensure_ascii=False)}),
        has_continue: buttons.includes({json.dumps(CONTINUE_BUTTON_TEXT, ensure_ascii=False)}),
        chat_text: chat && visible(chat) ? (chat.innerText || '').trim().slice(0, 1200) : '',
    }});
}})()
"""

_SELECT_CARD_JS = r"""
(() => {
    const jobId = "__JOB_ID__";
    const cards = Array.from(document.querySelectorAll('.job-card-pc-container')).filter((c) => !!c.offsetParent);
    for (const card of cards) {
        let ext = {};
        const raw = card.getAttribute('data-tlg-ext') || '';
        try { ext = JSON.parse(raw) || {}; } catch (e1) {
            try { ext = JSON.parse(decodeURIComponent(raw)) || {}; } catch (e2) { ext = {}; }
        }
        if (String(ext.jobId || '') !== jobId) continue;
        card.click();
        return JSON.stringify({selected: true});
    }
    return JSON.stringify({selected: false});
})()
"""

_CLICK_CHAT_JS = f"""
(() => {{
    const pane = document.querySelector('#search-job-detail');
    if (!pane) return JSON.stringify({{clicked: false}});
    const button = Array.from(pane.querySelectorAll('button')).find((el) => {{
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && (el.innerText || '').trim() === {json.dumps(CHAT_BUTTON_TEXT, ensure_ascii=False)};
    }});
    if (!button) return JSON.stringify({{clicked: false}});
    button.click();
    return JSON.stringify({{clicked: true}});
}})()
"""

_CLOSE_CHAT_JS = """
(() => {
    const close = document.querySelector('.im-ui-basic-chat-modal .ant-im-modal-close');
    if (close) close.click();
    return JSON.stringify({closed: !!close});
})()
"""


def _parse(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _failure(error: str, detail: str, *, skip_backoff: bool = True) -> dict:
    return {"success": False, "error": error, "history_detail": detail, "skip_backoff": skip_backoff}


def _search_url(job: dict, page: int) -> str:
    keyword = str(job.get("source_keyword") or job.get("title") or "").strip()
    url = SEARCH_URL.format(keyword=quote(keyword))
    code = str(job.get("source_city_code") or "").strip()
    if code:
        url += f"&dqs={quote(code)}"
    if page > 0:
        url += f"&curPage={page}"
    return url


def _greeting_from_chat(chat_text: str) -> str:
    """The chat window shows the safety notice, then the greeting the platform sent."""
    lines = [line.strip() for line in chat_text.splitlines() if line.strip()]
    if GREETING_ANCHOR in lines:
        lines = lines[lines.index(GREETING_ANCHOR) + 1:]
    return next((line for line in lines if line not in GREETING_TAIL), "")


def send_liepin_application(
    job: dict,
    throttle_config: dict,
    *,
    stop_requested: Callable[[Any], bool],
    sleep_or_stop: Callable[[float, Any], bool],
) -> tuple[dict, str | None]:
    """Greet one Liepin job via the search split view; returns ``(result, failed_target_id)``.

    Same contract as the Boss sender: ``result["success"]`` is true only when the
    platform showed the greeting in the chat window (or the page already offers 「继续聊」).
    """
    stop_event = throttle_config.get("_workbench_stop_event")
    access_guard = throttle_config.get("_platform_access_guard")
    job_id = str(job.get("source_job_id") or "").strip()
    if not job_id.isdigit():
        return _failure("invalid_job_url", "缺少猎聘岗位编号，无法在搜索页定位该岗位"), None
    if not str(job.get("source_keyword") or job.get("title") or "").strip():
        return _failure("invalid_job_url", "缺少搜索关键词，无法在猎聘搜索页定位该岗位"), None
    if isinstance(access_guard, PlatformAccessGuard):
        try:
            access_guard.reserve("job_page")
        except PlatformSafetyStop as exc:
            return {
                "success": False,
                "error": exc.reason,
                "history_detail": "为了账户安全，已达到平台页面访问上限或仍处于风险冷却",
            }, None
    target_id = new_tab(_search_url(job, 0), background=True)
    if not target_id:
        return _failure("open_page_failed", "无法打开页面"), None

    def done(result: dict, keep: bool = False) -> tuple[dict, str | None]:
        if keep:
            return result, target_id
        close_tab(target_id)
        return result, None

    select_js = _SELECT_CARD_JS.replace("__JOB_ID__", job_id)
    state: dict = {}
    found = False
    for page in range(MAX_SEARCH_PAGES):
        if page > 0 and not navigate(target_id, _search_url(job, page)):
            return done(_failure("open_page_failed", "猎聘搜索页翻页失败"))
        if sleep_or_stop(random.uniform(4, 8), stop_event) or stop_requested(stop_event):
            return done(_failure("stopped", "用户已请求停止"))
        for _ in range(6):
            state = _parse(evaluate(target_id, _PAGE_STATE_JS))
            if state.get("cards"):
                break
            if any(marker in str(state.get("text") or "") for marker in RISK_MARKERS):
                break
            if sleep_or_stop(1, stop_event):
                return done(_failure("stopped", "用户已请求停止"))
        if any(marker in str(state.get("text") or "") for marker in RISK_MARKERS):
            return done(_failure("captcha", "猎聘页面出现验证，已停止；请人工处理后再试", skip_backoff=False))
        if not state.get("cards"):
            return done(_failure("job_page_unavailable", "猎聘搜索页没有岗位卡片，未发送"))
        if _parse(evaluate(target_id, select_js)).get("selected"):
            found = True
            break
    if not found:
        return done(_failure(
            "job_not_in_search",
            f"在猎聘搜索前 {MAX_SEARCH_PAGES} 页没有找到该岗位（可能已下架或排名变化），未发送",
        ))

    for _ in range(8):
        if sleep_or_stop(1, stop_event):
            return done(_failure("stopped", "用户已请求停止"))
        state = _parse(evaluate(target_id, _PAGE_STATE_JS))
        if state.get("has_chat") or state.get("has_continue"):
            break
    if not state.get("has_chat"):
        if state.get("has_continue"):
            # The pane already offers 「继续聊」: this job was greeted before.
            return done({
                "success": True, "verified": True, "already_applied": True,
                "sent_text": "（此前已沟通，本次未重复发送）",
            })
        return done(_failure("no_chat_button", "详情栏没有「聊一聊」按钮，未发送"))

    if not _parse(evaluate(target_id, _CLICK_CHAT_JS)).get("clicked"):
        return done(_failure("no_chat_button", "详情栏没有「聊一聊」按钮，未发送"))

    sent_text = ""
    for _ in range(10):
        if sleep_or_stop(1, stop_event):
            return done(_failure("stopped", "用户已请求停止"), keep=True)
        state = _parse(evaluate(target_id, _PAGE_STATE_JS))
        sent_text = _greeting_from_chat(str(state.get("chat_text") or ""))
        if sent_text and state.get("has_continue"):
            break
    if not sent_text:
        return done(
            _failure(
                "deliver_unconfirmed",
                "已点击「聊一聊」，但聊天窗口没有出现招呼语；请到猎聘「我的沟通」核实，避免重复发送",
            ),
            keep=True,
        )
    evaluate(target_id, _CLOSE_CHAT_JS)
    return done({"success": True, "verified": True, "sent_text": sent_text})
