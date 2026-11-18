"""智联招聘岗位投递适配器。

智联网页版没有 Boss 那样的「先沟通再发招呼语」流程：岗位页上只有「立即投递」，
点击后平台把在线简历连同它自己预置的打招呼语一起发给 HR，并弹出
``deliver-greeting-modal``（标题「已向对方发送简历和打招呼语」，按钮「留在此页」「继续沟通」）。
所以这里发出去的招呼语是平台预置的那一句，不是工作台生成的招呼语；调用方据此在记录里写
平台实际发送的文字（``sent_text``）。

该流程在 2026-11-18 用真实账号验证过一次（弹窗文字与按钮名按当时页面写成）。
页面结构以后变化时，宁可报 ``deliver_unconfirmed`` 让用户去「投递记录」核实，
也不盲目重试，避免重复投递。
"""

from __future__ import annotations

import json
import random
from typing import Any, Callable

from offerpilot.browser import close_tab, evaluate, new_tab
from offerpilot.platform_safety import PlatformAccessGuard, PlatformSafetyStop

APPLY_BUTTON_TEXT = "立即投递"
SUCCESS_MODAL_MARKER = "已向对方发送"
RISK_MARKERS = ("滑块", "安全验证", "请完成验证", "访问异常", "操作过于频繁")
CLOSED_MARKERS = ("职位已下线", "职位已关闭", "该职位已停止招聘", "访问的页面不存在", "职位不存在")

_PAGE_STATE_JS = f"""
(() => {{
    const text = document.body ? document.body.innerText : '';
    const title = document.title || '';
    const visible = (el) => {{ const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }};
    const buttons = Array.from(document.querySelectorAll('button')).filter(visible)
        .map((el) => (el.innerText || '').trim());
    const modal = document.querySelector('.deliver-greeting-modal__box');
    return JSON.stringify({{
        title: title.slice(0, 80),
        text: text.slice(0, 4000),
        has_apply: buttons.includes({json.dumps(APPLY_BUTTON_TEXT, ensure_ascii=False)}),
        has_continue: buttons.includes('继续沟通'),
        modal_text: modal ? (modal.innerText || '').trim().slice(0, 400) : '',
    }});
}})()
"""

_CLICK_APPLY_JS = f"""
(() => {{
    const button = Array.from(document.querySelectorAll('button'))
        .find((el) => (el.innerText || '').trim() === {json.dumps(APPLY_BUTTON_TEXT, ensure_ascii=False)});
    if (!button) return JSON.stringify({{clicked: false}});
    button.click();
    return JSON.stringify({{clicked: true}});
}})()
"""

_CLOSE_MODAL_JS = """
(() => {
    const button = Array.from(document.querySelectorAll('.deliver-greeting-modal__btn'))
        .find((el) => (el.innerText || '').trim() === '留在此页');
    if (button) button.click();
    return JSON.stringify({closed: !!button});
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


def send_zhilian_application(
    job: dict,
    throttle_config: dict,
    *,
    stop_requested: Callable[[Any], bool],
    sleep_or_stop: Callable[[float, Any], bool],
) -> tuple[dict, str | None]:
    """Apply to one Zhilian job in a background tab; returns ``(result, failed_target_id)``.

    Same contract as the Boss sender: ``result["success"]`` is true only when the
    platform confirmed the delivery (or the page already shows it was delivered).
    """
    stop_event = throttle_config.get("_workbench_stop_event")
    access_guard = throttle_config.get("_platform_access_guard")
    if isinstance(access_guard, PlatformAccessGuard):
        try:
            access_guard.reserve("job_page")
        except PlatformSafetyStop as exc:
            return {
                "success": False,
                "error": exc.reason,
                "history_detail": "为了账户安全，已达到平台页面访问上限或仍处于风险冷却",
            }, None
    url = str(job.get("url") or "")
    if "zhaopin.com" not in url:
        return _failure("invalid_job_url", "岗位链接不是智联招聘地址"), None
    target_id = new_tab(url, background=True)
    if not target_id:
        return _failure("open_page_failed", "无法打开页面"), None

    def done(result: dict, keep: bool = False) -> tuple[dict, str | None]:
        if keep:
            return result, target_id
        close_tab(target_id)
        return result, None

    if sleep_or_stop(random.uniform(4, 8), stop_event) or stop_requested(stop_event):
        return done(_failure("stopped", "用户已请求停止"))

    state = _parse(evaluate(target_id, _PAGE_STATE_JS))
    text = str(state.get("text") or "")
    title = str(state.get("title") or "")
    if any(marker in text for marker in RISK_MARKERS):
        return done(_failure("captcha", "智联页面出现验证，已停止；请人工处理后再试", skip_backoff=False))
    if any(marker in text or marker in title for marker in CLOSED_MARKERS):
        return done(_failure("job_page_unavailable", "岗位已关闭或下架"))
    if not state.get("has_apply"):
        if state.get("has_continue"):
            # The page already offers 「继续沟通」: this job was delivered before.
            return done({
                "success": True, "verified": True, "already_applied": True,
                "sent_text": "（此前已投递，本次未重复投递）",
            })
        return done(_failure("no_apply_button", "页面没有「立即投递」按钮，未投递"))

    if not _parse(evaluate(target_id, _CLICK_APPLY_JS)).get("clicked"):
        return done(_failure("no_apply_button", "页面没有「立即投递」按钮，未投递"))

    modal_text = ""
    for _ in range(12):
        if sleep_or_stop(1, stop_event):
            return done(_failure("stopped", "用户已请求停止"), keep=True)
        state = _parse(evaluate(target_id, _PAGE_STATE_JS))
        modal_text = str(state.get("modal_text") or "")
        if SUCCESS_MODAL_MARKER in modal_text:
            break
    if SUCCESS_MODAL_MARKER not in modal_text:
        return done(
            _failure(
                "deliver_unconfirmed",
                "已点击「立即投递」，但平台没有给出成功提示；请到智联「投递记录」核实，避免重复投递",
            ),
            keep=True,
        )
    # The modal lists what the platform sent: its title, then its preset greeting.
    lines = [line.strip() for line in modal_text.splitlines() if line.strip()]
    sent_text = next((line for line in lines[1:] if line not in {"留在此页", "继续沟通"}), "")
    evaluate(target_id, _CLOSE_MODAL_JS)
    return done({"success": True, "verified": True, "sent_text": sent_text or "平台预置招呼语"})
