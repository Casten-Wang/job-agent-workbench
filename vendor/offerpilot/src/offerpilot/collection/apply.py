"""Single-job apply (招呼语投递) for the non-BOSS platforms.

Each function handles exactly one already-selected job:

1. validate the job against the approval queue status, the greeting and the
   user-confirmed text *before* any page is opened;
2. open the job page in a background tab;
3. find the platform's apply / chat button and click it;
4. if a greeting dialog appears, fill it, verify the text, and confirm;
5. read the result and return a structured conclusion.

The functions never retry and never bypass an obstacle: the first captcha,
login wall or unrecognised button ends the call with ``captcha`` /
``needs_login`` / ``unknown``.  ``capabilities.py`` keeps ``deliver`` locked
for these platforms; nothing calls these functions automatically yet.

The button texts, dialog selectors and success markers below are *assumptions*
derived from the platforms' public pages.  They must be verified against a
real authorized account before ``deliver`` is enabled — see the report.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

# Only these approval-queue states may be sent.  ``approved`` is the queue's
# confirmed state; ``ready`` is accepted as the equivalent pre-send state used
# by the greeting store.
ALLOWED_QUEUE_STATUSES = frozenset({"ready", "approved"})

RESULT_STATUSES = frozenset({"sent", "failed", "needs_login", "captcha", "unknown"})


def _result(status: str, error: str | None, platform: str, job_id: str, detail: str = "") -> dict[str, Any]:
    assert status in RESULT_STATUSES, status
    out: dict[str, Any] = {"status": status, "platform": platform, "job_id": job_id}
    if error:
        out["error"] = error
    if detail:
        out["detail"] = detail
    return out


def _validate_request(
    job: Any,
    greeting: Any,
    queue_status: Any,
    expected_greeting: Any,
    platform: str,
) -> tuple[str, dict[str, Any] | None]:
    """Pre-send checks.  Returns ``(job_id, error_result_or_None)``."""
    row = job if isinstance(job, dict) else {}
    job_id = str(row.get("id") or row.get("job_id") or "").strip()
    if not job_id:
        return "", _result("failed", "missing_job_id", platform, "")
    status = str(queue_status or "").strip()
    if status not in ALLOWED_QUEUE_STATUSES:
        return job_id, _result(
            "failed", "queue_not_approved", platform, job_id,
            detail=f"审批队列状态为 {status or '空'}，仅 ready/approved 可发送",
        )
    text = str(greeting or "").strip()
    if not text:
        return job_id, _result("failed", "empty_greeting", platform, job_id)
    if expected_greeting is not None and text != str(expected_greeting).strip():
        return job_id, _result(
            "failed", "greeting_not_confirmed", platform, job_id,
            detail="招呼语与用户已确认的文本不一致，拒绝发送",
        )
    return job_id, None


# ---------------------------------------------------------------------------
# Page scripts.  Each carries a sentinel comment so tests can route a fake
# browser's ``evaluate`` by script kind without duplicating the JS.
# ---------------------------------------------------------------------------

JS_PAGE_SNAPSHOT = r"""/* offerpilot.apply.page */
(() => {
  const text = document.body ? document.body.innerText : '';
  const captchaMarkers = ['验证码', '滑动验证', '安全验证', '人机验证', '拖动滑块', '向右拖动滑块', '完成验证', '请完成下方验证'];
  const loginMarkers = ['请先登录', '立即登录', '登录后继续', '登录后查看', '登录后操作', '扫码登录', '登录失效', '账号登录', '请登录'];
  const closedMarkers = ['职位已关闭', '职位已下线', '职位已下架', '职位已暂停', '已停止招聘', '停止招聘', '已招满', '访问的页面不存在'];
  if (captchaMarkers.some((m) => text.includes(m))) return JSON.stringify({stage: 'captcha'});
  if (loginMarkers.some((m) => text.includes(m))) return JSON.stringify({stage: 'needs_login'});
  if (closedMarkers.some((m) => text.includes(m))) return JSON.stringify({stage: 'job_closed'});
  return JSON.stringify({stage: 'ready'});
})()"""

JS_SENT_MARKERS = r"""/* offerpilot.apply.sent */
(() => {
  const text = document.body ? document.body.innerText : '';
  const success = ['投递成功', '已投递', '已发送', '发送成功', '简历已投递', '投递完成', '打招呼成功', '沟通成功'];
  const failure = ['投递失败', '发送失败', '请勿重复投递', '已投递过', '不能重复投递', '操作频繁'];
  if (success.some((m) => text.includes(m))) return JSON.stringify({sent: true});
  if (failure.some((m) => text.includes(m))) return JSON.stringify({sent: false, rejected: true});
  return JSON.stringify({sent: false});
})()"""


def click_button_script(patterns: tuple[str, ...]) -> str:
    """Find and click the first visible button whose text starts with a pattern."""
    encoded = json.dumps(list(patterns), ensure_ascii=False)
    return f"""/* offerpilot.apply.click */
(() => {{
  const patterns = {encoded};
  const nodes = Array.from(document.querySelectorAll(
    'button, a, input[type="button"], input[type="submit"], div[role="button"], span.btn, .btn'
  ));
  const visible = nodes.filter((el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }});
  const textOf = (el) => String(el.textContent || el.value || '').replace(/\\s+/g, '');
  const hit = visible.find((el) => patterns.some((p) => {{
    const t = textOf(el);
    return t === p || t.startsWith(p);
  }}));
  if (!hit) {{
    const applied = visible.some((el) => ['已投递', '已申请', '已沟通', '投递过'].some((m) => textOf(el).includes(m)));
    return JSON.stringify({{found: false, already: applied}});
  }}
  hit.scrollIntoView();
  hit.click();
  return JSON.stringify({{found: true, text: String(hit.textContent || '').trim().slice(0, 40)}});
}})()"""


def fill_greeting_script(greeting: str) -> str:
    """Fill the greeting dialog's editable field and read the value back."""
    encoded = json.dumps(str(greeting), ensure_ascii=False)
    return f"""/* offerpilot.apply.fill */
(() => {{
  const expected = {encoded};
  const normalize = (value) => String(value || '').replace(/\\s+/g, '');
  const isVisible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const editable = Array.from(document.querySelectorAll(
    'textarea, div[contenteditable="true"], [contenteditable="true"], input[type="text"]'
  )).filter(isVisible).find((el) => !el.readOnly && !el.disabled);
  if (!editable) return JSON.stringify({{filled: false, stage: 'no_dialog'}});
  const isFormField = editable instanceof HTMLTextAreaElement || editable instanceof HTMLInputElement;
  const prop = isFormField ? 'value' : 'textContent';
  const findSetter = (el, name) => {{
    let proto = Object.getPrototypeOf(el);
    while (proto) {{
      const desc = Object.getOwnPropertyDescriptor(proto, name);
      if (desc && desc.set) return desc.set;
      proto = Object.getPrototypeOf(proto);
    }}
    return null;
  }};
  editable.scrollIntoView();
  editable.focus();
  const setter = findSetter(editable, prop);
  if (setter) {{
    setter.call(editable, expected);
  }} else if (isFormField) {{
    editable.value = expected;
  }} else {{
    editable.textContent = expected;
  }}
  editable.dispatchEvent(new Event('input', {{bubbles: true}}));
  editable.dispatchEvent(new Event('change', {{bubbles: true}}));
  const actual = isFormField ? editable.value : editable.textContent;
  if (normalize(actual) !== normalize(expected)) return JSON.stringify({{filled: false, stage: 'fill_mismatch'}});
  return JSON.stringify({{filled: true}});
}})()"""


def confirm_script(patterns: tuple[str, ...]) -> str:
    """Click the dialog's confirm button."""
    encoded = json.dumps(list(patterns), ensure_ascii=False)
    return f"""/* offerpilot.apply.confirm */
(() => {{
  const patterns = {encoded};
  const nodes = Array.from(document.querySelectorAll(
    'button, a, div[role="button"], span.btn, .btn'
  ));
  const textOf = (el) => String(el.textContent || el.value || '').replace(/\\s+/g, '');
  const visible = nodes.filter((el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }});
  const hit = visible.find((el) => patterns.some((p) => {{
    const t = textOf(el);
    return t === p || t.startsWith(p);
  }}));
  if (!hit) return JSON.stringify({{clicked: false}});
  hit.scrollIntoView();
  hit.click();
  return JSON.stringify({{clicked: true}});
}})()"""


# Button / confirm vocabularies.  These are *assumptions* until a real-page
# acceptance test confirms them (see the report).
BUTTON_PATTERNS = {
    "zhilian": ("立即投递", "投递简历", "立即申请"),
    "51job": ("立即投递", "投递简历", "立即申请"),
    "liepin": ("立即沟通", "立即投递", "沟通一下"),
}
CONFIRM_PATTERNS = {
    "zhilian": ("确认投递", "投递简历", "投递", "确定"),
    "51job": ("确认投递", "投递简历", "投递", "确定"),
    "liepin": ("确认沟通", "发送打招呼", "发送", "确定"),
}


def _evaluate_json(browser: Any, target_id: str, script: str) -> dict[str, Any] | None:
    try:
        raw = browser.evaluate(target_id, script)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _obstacle_result(snapshot: dict[str, Any] | None, platform: str, job_id: str) -> dict[str, Any] | None:
    """Return a terminal result for a captcha / login / closed snapshot, else None."""
    if snapshot is None:
        return _result("unknown", "page_snapshot_unreadable", platform, job_id)
    stage = str(snapshot.get("stage") or "")
    if stage == "captcha":
        return _result("captcha", None, platform, job_id, detail="页面出现验证码，已停止，不重试")
    if stage == "needs_login":
        return _result("needs_login", None, platform, job_id, detail="页面要求登录，已停止，不重试")
    if stage == "job_closed":
        return _result("failed", "job_unavailable", platform, job_id, detail="岗位已关闭或下架")
    return None


def _apply_single(
    platform: str,
    job: Any,
    greeting: Any,
    *,
    queue_status: Any,
    expected_greeting: Any,
    browser: Any,
    config: dict[str, Any] | None,
    log: Callable[[str], None] | None,
) -> dict[str, Any]:
    job_id, error = _validate_request(job, greeting, queue_status, expected_greeting, platform)
    if error is not None:
        if log is not None:
            log(f"{platform} 投递被拒：{error.get('error')}（{error.get('detail', '')}）")
        return error
    row = job if isinstance(job, dict) else {}
    url = str(row.get("url") or "").strip()
    if not url:
        return _result("failed", "missing_job_url", platform, job_id)
    if browser is None:
        return _result("failed", "browser_unavailable", platform, job_id)

    raw_wait = (config or {}).get("apply_step_wait_seconds")
    if raw_wait is None:
        step_wait = 2.0
    else:
        try:
            step_wait = max(0.0, float(raw_wait))
        except (TypeError, ValueError):
            step_wait = 2.0

    target_id = browser.new_tab(url, background=True)
    if not target_id:
        return _result("failed", "open_page_failed", platform, job_id)
    try:
        wait_for_load = getattr(browser, "wait_for_load", None)
        if callable(wait_for_load):
            try:
                wait_for_load(target_id, timeout=20.0)
            except Exception:
                pass

        snapshot = _evaluate_json(browser, target_id, JS_PAGE_SNAPSHOT)
        terminal = _obstacle_result(snapshot, platform, job_id)
        if terminal is not None:
            return terminal

        clicked = _evaluate_json(browser, target_id, click_button_script(BUTTON_PATTERNS[platform]))
        if clicked is None:
            return _result("unknown", "apply_button_scan_unreadable", platform, job_id)
        if not clicked.get("found"):
            if clicked.get("already"):
                return _result("failed", "already_applied", platform, job_id,
                               detail="岗位显示已投递/已沟通，未重复操作")
            return _result("unknown", "apply_button_not_found", platform, job_id,
                           detail=f"未找到按钮：{'/'.join(BUTTON_PATTERNS[platform])}")

        time.sleep(step_wait)
        snapshot = _evaluate_json(browser, target_id, JS_PAGE_SNAPSHOT)
        terminal = _obstacle_result(snapshot, platform, job_id)
        if terminal is not None:
            return terminal

        dialog = _evaluate_json(browser, target_id, fill_greeting_script(greeting))
        if dialog is None:
            return _result("unknown", "greeting_dialog_scan_unreadable", platform, job_id)
        terminal = _obstacle_result(dialog, platform, job_id)
        if terminal is not None:
            return terminal
        if dialog.get("filled"):
            time.sleep(step_wait)
            snapshot = _evaluate_json(browser, target_id, JS_PAGE_SNAPSHOT)
            terminal = _obstacle_result(snapshot, platform, job_id)
            if terminal is not None:
                return terminal
            confirm = _evaluate_json(browser, target_id, confirm_script(CONFIRM_PATTERNS[platform]))
            if confirm is None or not confirm.get("clicked"):
                return _result("unknown", "confirm_button_not_found", platform, job_id,
                               detail=f"未找到确认按钮：{'/'.join(CONFIRM_PATTERNS[platform])}")
            time.sleep(step_wait)
        elif dialog.get("stage") == "fill_mismatch":
            return _result("unknown", "greeting_fill_mismatch", platform, job_id,
                           detail="招呼语填入后校验不一致，未确认发送")
        else:
            # No greeting dialog: some sites send the preset greeting directly.
            time.sleep(step_wait)

        final = _evaluate_json(browser, target_id, JS_PAGE_SNAPSHOT)
        terminal = _obstacle_result(final, platform, job_id)
        if terminal is not None:
            return terminal
        sent = _evaluate_json(browser, target_id, JS_SENT_MARKERS)
        if sent is None:
            return _result("unknown", "send_result_unreadable", platform, job_id)
        if sent.get("sent"):
            return _result("sent", None, platform, job_id)
        if sent.get("rejected"):
            return _result("failed", "send_rejected", platform, job_id,
                           detail="页面提示投递失败或重复投递")
        return _result("unknown", "send_result_unconfirmed", platform, job_id,
                       detail="未读到明确的发送成功或失败提示")
    finally:
        try:
            browser.close_tab(target_id)
        except Exception:
            pass


def apply_zhilian(
    job: Any,
    greeting: Any,
    *,
    queue_status: Any = "approved",
    expected_greeting: Any = None,
    browser: Any = None,
    config: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Send one greeting to one 智联 job.  Returns a structured conclusion."""
    return _apply_single(
        "zhilian", job, greeting,
        queue_status=queue_status, expected_greeting=expected_greeting,
        browser=browser, config=config, log=log,
    )


def apply_51job(
    job: Any,
    greeting: Any,
    *,
    queue_status: Any = "approved",
    expected_greeting: Any = None,
    browser: Any = None,
    config: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Send one greeting to one 前程无忧 job.  Returns a structured conclusion."""
    return _apply_single(
        "51job", job, greeting,
        queue_status=queue_status, expected_greeting=expected_greeting,
        browser=browser, config=config, log=log,
    )


def apply_liepin(
    job: Any,
    greeting: Any,
    *,
    queue_status: Any = "approved",
    expected_greeting: Any = None,
    browser: Any = None,
    config: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Send one greeting to one 猎聘 job.  Returns a structured conclusion."""
    return _apply_single(
        "liepin", job, greeting,
        queue_status=queue_status, expected_greeting=expected_greeting,
        browser=browser, config=config, log=log,
    )
