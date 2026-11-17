"""Browser acceptance against the isolated synthetic UI fixture on port 8769."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/desktop-agent-ui"
OUT.mkdir(parents=True, exist_ok=True)
AUDIT = (Path.home() / ".agents/skills/desktop-agent-ui/scripts/clip-audit.js").read_text(encoding="utf-8")
checks = {}


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_init_script("localStorage.setItem('job-workbench-mode','user')")
    page = context.new_page()
    errors, streams, posts = [], [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("response", lambda r: streams.append(r.status) if "/stream?" in r.url else None)
    page.on("request", lambda r: posts.append(r.url) if "/messages?" in r.url and r.method == "POST" else None)
    page.goto("http://127.0.0.1:8769/")
    expect(page.locator("#wa-new")).to_be_enabled()
    expect(page.locator("#wa-notice")).to_be_empty()
    page.evaluate("""() => { window.inkSeen=0; new MutationObserver(records=>records.forEach(r=>r.addedNodes.forEach(n=>{if(n.nodeType===1){if(n.matches('.wa-ink'))window.inkSeen++;window.inkSeen+=n.querySelectorAll('.wa-ink').length;}}))).observe(document.querySelector('#wa-messages'),{childList:true,subtree:true}); }""")

    def send(text):
        page.locator("#wa-input").fill(text)
        page.locator("#wa-send").click()

    def settled(state="completed"):
        expect(page.locator("#wa-new")).to_be_enabled()
        expect(page.locator("#wa-status")).to_have_attribute("data-state", state)
        expect(page.locator("#wa-notice")).to_be_empty()

    send("保持执行")
    expect(page.locator("#wa-status")).to_have_attribute("data-state", "running")
    page.wait_for_function("document.querySelector('#wa-activity').hidden === false")
    page.locator("#wa-stop").click()
    settled("stopped")
    assert 200 in streams, streams
    checks["real_sse_and_stop"] = True
    page.evaluate("window.originalMessage=document.querySelector('#wa-messages').firstElementChild")

    send("测试长回复")
    settled()
    expect(page.locator(".wa-message-assistant p").last).to_contain_text("合成材料 80")
    assert page.evaluate("window.originalMessage===document.querySelector('#wa-messages').firstElementChild")
    page.wait_for_function("window.inkSeen>0")
    checks["incremental_dom_and_ink_reveal"] = True

    send("保持执行")
    expect(page.locator("#wa-status")).to_have_attribute("data-state", "running")
    page.locator("#wa-messages").evaluate("e=>{e.scrollTop=0;e.dispatchEvent(new Event('scroll'))}")
    page.locator("#wa-stop").click()
    settled("stopped")
    assert page.locator("#wa-messages").evaluate("e=>e.scrollTop") == 0
    expect(page.locator("#wa-jump")).to_be_visible()
    page.locator("#wa-jump").click()
    assert page.locator("#wa-messages").evaluate("e=>e.scrollHeight-e.scrollTop-e.clientHeight") < 2
    checks["history_scroll_and_jump"] = True

    page.locator("#wa-input").fill("会话甲草稿")
    page.locator("#wa-new").click()
    page.locator("#wa-input").fill("会话乙草稿")
    page.locator(".wa-session").first.click()
    expect(page.locator("#wa-input")).to_have_value("会话甲草稿")
    expect(page.locator("#wa-new")).to_be_enabled()
    checks["session_draft_isolation"] = True

    page.locator("#wa-new").click()
    input_box = page.locator("#wa-input")
    input_box.fill("推荐岗位")
    before = len(posts)
    input_box.dispatch_event("compositionstart")
    input_box.press("Enter")
    assert len(posts) == before
    input_box.dispatch_event("compositionend")
    input_box.press("Enter")
    assert len(posts) == before
    input_box.press("Enter")
    settled()
    assert len(posts) == before + 1
    expect(page.locator(".wa-job")).to_have_count(1)
    checks["ime_ghost_enter_and_next_enter"] = True

    input_box.fill("第一行")
    input_box.press("Shift+Enter")
    expect(input_box).to_have_value("第一行\n")
    input_box.fill("\n".join("输入框自适应测试" for _ in range(30)))
    assert input_box.evaluate("e=>e.clientHeight") <= 240
    assert input_box.evaluate("e=>e.scrollHeight>e.clientHeight")
    checks["composer_height_cap_and_newline"] = True
    input_box.fill("")

    page.locator(".wa-job button").click()
    settled("waiting_input")
    page.locator("#wa-toggle-material").click()
    page.locator("#wa-existing-material").select_option("mat_confirmed")
    page.locator("#wa-use-material").click()
    settled()
    expect(page.locator("#wa-results")).to_be_visible()
    page.screenshot(path=str(OUT / "desktop-artifact.png"))
    page.locator("#wa-close-results").click()
    page.locator("#wa-process summary").click()
    assert page.locator('.wa-tool[data-state="completed"]').count() >= 1
    checks["tool_pairs_and_artifact_panel"] = True

    audits = {}
    for label, action in [
        ("expanded", lambda: None),
        ("hover", lambda: page.locator("#wa-toggle-material").hover()),
        ("default", lambda: page.locator("#wa-process summary").click()),
    ]:
        action()
        audit = page.evaluate(AUDIT, {"root": "#view-workbench"})
        assert audit["cut"] == 0, audit
        audits[label] = {k: audit[k] for k in ("ok", "cut", "hidden")}
    checks["clip_audits"] = audits
    page.screenshot(path=str(OUT / "desktop-conversation.png"))
    for width in (1440, 1024, 768, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width > 700 else 900})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), width
        assert page.locator("#wa-input").is_visible(), width
        assert page.locator("#wa-new").is_visible(), width
    checks["responsive_widths"] = [1440, 1024, 768, 375]
    page.screenshot(path=str(OUT / "mobile.png"))
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.locator('[data-theme-choice="dark"]').click()
    page.wait_for_function("() => getComputedStyle(document.querySelector('#wa-new')).color==='rgb(196, 194, 185)'")
    page.screenshot(path=str(OUT / "desktop-dark.png"))
    checks["dark_theme"] = page.locator("body").evaluate("e=>getComputedStyle(e).getPropertyValue('--surface').trim()")

    page.emulate_media(reduced_motion="reduce")
    page.locator("#wa-new").click()
    before_ink = page.evaluate("window.inkSeen")
    send("测试长回复")
    settled()
    assert page.evaluate("window.inkSeen") == before_ink
    checks["reduced_motion"] = True
    page.reload()
    settled()
    assert page.locator(".wa-ink").count() == 0
    checks["restore_without_replaying_animation"] = True
    page.locator("#wa-tab-overview").click()
    expect(page.locator("#wa-overview")).to_be_visible()
    page.locator('[data-view="profile"]').click()
    expect(page.locator("#view-profile")).to_be_visible()
    checks["overview_and_profile_navigation"] = True
    assert not errors, errors
    checks["page_errors"] = errors
    browser.close()

(OUT / "browser-verification.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(checks, ensure_ascii=False))
