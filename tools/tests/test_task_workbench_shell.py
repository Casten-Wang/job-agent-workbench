"""任务式工作台外壳（集成工作台概念稿 W01–W06）的结构契约。

只检查静态结构与脚本中的路由约定，不启动浏览器。
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "web/static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC / "workbench.js").read_text(encoding="utf-8")
STYLE = (STATIC / "workbench.css").read_text(encoding="utf-8")


def section(html, element_id):
    start = html.index(f'id="{element_id}"')
    start = html.rindex("<", 0, start)
    tag = re.match(r"<(\w+)", html[start:]).group(1)
    depth, index = 0, start
    pattern = re.compile(rf"<(/?){tag}\b[^>]*>")
    for match in pattern.finditer(html, start):
        depth += -1 if match.group(1) else 1
        if depth == 0:
            return html[start:match.end()]
        index = match.end()
    raise AssertionError(f"unterminated {element_id}")


class TaskShellStructureTests(unittest.TestCase):
    def test_task_sidebar_replaces_numbered_navigation_inside_workbench(self):
        nav = section(HTML, "wb-tasknav")
        for element_id in ("wb-new-task", "wb-task-list", "wb-nav-profile", "wb-all-tools", "wb-settings-button"):
            self.assertIn(f'id="{element_id}"', nav)
        self.assertIn('href="/?workbench=legacy"', nav)
        self.assertNotIn("nav-index", nav)
        self.assertIn("body.wb-task-shell .app-shell > .sidebar", STYLE)

    def test_original_numbered_navigation_still_exists_for_legacy_mode(self):
        for hub in ("workbench", "agent", "find", "profile", "resume", "interview", "push", "data"):
            self.assertIn(f'data-hub="{hub}"', HTML)

    def test_taskbar_has_context_strip_and_four_steps(self):
        taskbar = section(HTML, "wb-taskbar")
        for element_id in ("wb-strip-job", "wb-strip-version", "wb-strip-material", "wb-strip-edit", "wb-stepper"):
            self.assertIn(f'id="{element_id}"', taskbar)
        steps = re.search(r"const STEPS=\[(.*?)\];", SCRIPT).group(1)
        self.assertEqual(re.findall(r"'([^']+)'\]", steps), ["寻找岗位", "准备材料", "复核申请", "模拟面试"])

    def test_start_screen_launches_in_place_task_flows(self):
        start = section(HTML, "wb-start")
        self.assertIn('id="wb-goal-form"', start)
        self.assertIn('id="wb-goal-input"', start)
        intents = re.findall(r'data-wb-intent="([^"]+)"', start)
        self.assertEqual(intents, ["jobs", "application", "interview", "notes"])
        self.assertIn('id="wb-continue-list"', start)
        self.assertIn('id="wb-side-materials"', start)
        self.assertIn('id="wb-side-connections"', start)
        # 意图按钮不跳出到专项页面链接
        self.assertNotIn("data-view-link", start)

    def test_job_picker_embeds_selection_entry_and_collection(self):
        jobs = section(HTML, "wb-jobs")
        self.assertIn('id="wb-jobs-rows"', jobs)
        self.assertIn("radio.name='wb-job-choice'", SCRIPT)
        for element_id in ("wb-jobs-tab-pool", "wb-jobs-tab-collect", "wb-jobs-paste", "wb-jobs-json", "wb-jobs-entry", "wb-jobs-collect", "wb-jobs-continue"):
            self.assertIn(f'id="{element_id}"', jobs)
        self.assertIn("选择岗位不会开始投递", jobs)
        # 粘贴 JD、导入 JSON 与采集复用原表单节点，不复制第二份
        for borrowed in ("jd-form", "import-form", "jd-result", "import-result"):
            self.assertIn(f"'{borrowed}'", SCRIPT)
        self.assertEqual(HTML.count('id="jd-form"'), 1)
        self.assertEqual(HTML.count('id="import-form"'), 1)

    def test_material_draft_is_edited_in_place_with_sources(self):
        draft = section(HTML, "wb-draft")
        self.assertEqual(re.findall(r'data-wb-draft="([^"]+)"', draft), ["resume", "greeting", "sources"])
        for element_id in ("wb-draft-host", "wb-draft-revise-button", "wb-draft-save", "wb-draft-review"):
            self.assertIn(f'id="{element_id}"', draft)
        self.assertIn("尚未发送", draft)
        # 草稿在「准备材料」步骤内显示，不再跳到单独结果页
        show = SCRIPT[SCRIPT.index("  function showArtifact("):SCRIPT.index("  function draftArtifacts(")]
        self.assertIn("renderDraft()", show)
        # 修改通过对话完成：选中内容只预填输入框，不直接改写草稿
        revise = SCRIPT[SCRIPT.index("  function reviseSelection("):SCRIPT.index("  async function draftToReview(")]
        self.assertIn("wa-input", revise)
        self.assertNotIn("send(", revise)

    def test_inline_delivery_review_only_adds_stricter_gates(self):
        review = section(HTML, "wb-review")
        for element_id in ("wb-review-host", "wb-review-checked", "wb-review-phrase", "wb-review-back"):
            self.assertIn(f'id="{element_id}"', review)
        self.assertIn("请输入：确认发送", review)
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        gate = app[app.index("function updateDeliveryStartState"):app.index("function deliveryFocusable")]
        # 原有风险确认与绑定检查保留，任务工作台的确认短语只是额外条件
        self.assertIn("riskChecked", gate)
        self.assertIn("!state.wbDeliveryBinding", gate)
        self.assertIn("deliveryGateOpen()", gate)
        start = app[app.index("async function startQueueDelivery"):]
        start = start[:start.index("postAction('offerpilot-deliver'")]
        self.assertIn("deliveryGateOpen()", start)
        self.assertIn("REVIEW_PHRASE='确认发送'", SCRIPT)
        # 就地复核：面板放进任务区；关闭时放回原位置
        self.assertIn("deliveryHost?.()", app)
        self.assertIn("deliveryClosed?.()", app)
        self.assertIn("queue-delivery-results", SCRIPT)

    def test_interview_focus_mode_collapses_the_general_chat(self):
        focus = SCRIPT[SCRIPT.index("  function syncInterviewFocus("):SCRIPT.index("  // ---- W03")]
        self.assertIn("wb-interview-focus", focus)
        self.assertIn("setAssistantOpen(false,false)", focus)
        self.assertIn("MutationObserver(syncInterviewFocus)", SCRIPT)
        # 沿用任务上下文预填综合面试的岗位与简历版本，不重复选择
        prefill = SCRIPT[SCRIPT.index("  function prefillInterview("):SCRIPT.index("  function interviewLive(")]
        self.assertIn("ci-job", prefill)
        self.assertIn("ci-resume-version", prefill)
        self.assertIn("!sel.value", prefill)  # 不覆盖用户已选的值

    def test_hr_message_task_has_its_own_steps_and_inline_confirmation(self):
        steps = re.search(r"const HR_STEPS=\[(.*?)\];", SCRIPT).group(1)
        self.assertEqual(re.findall(r"'([^']+)'\]", steps), ["整理消息", "起草回复", "确认发送", "准备面试"])
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        opener = app[app.index("function openHrReplyModal"):app.index("function updateHrReplyConfirmState")]
        self.assertIn("hrReplyHost?.()", opener)
        confirm = app[app.index("function updateHrReplyConfirmState"):app.index("function hrReplyFocusable")]
        self.assertIn("riskChecked", confirm)  # 原有风险确认保留
        self.assertIn("restoreHrReplyPanel()", SCRIPT)

    def test_old_pipeline_tabs_are_replaced_by_the_stepper_but_interview_modes_stay(self):
        self.assertIn(".ui-hub-tabs:not(.iv-mode-tabs)", STYLE)
        self.assertIn('class="ui-hub-tabs iv-mode-tabs"', HTML)

    def test_ids_stay_unique(self):
        ids = re.findall(r'\bid="([^"]+)"', HTML)
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_capability_maps_to_a_step_or_a_bottom_entry(self):
        from importlib import import_module
        import sys
        sys.path.insert(0, str(STATIC.parents[1]))
        catalog = import_module("interview_agent.workbench_catalog")
        step_for = re.search(r"const STEP_FOR=\{(.*?)\};", SCRIPT, re.S).group(1)
        stepped = set(re.findall(r"(\w+):'", step_for))
        bottom = {"profile", "profile_import", "notes", "mail", "push", "overview", "data", "settings"}
        for key, *_ in catalog.CAPABILITIES:
            with self.subTest(capability=key):
                self.assertIn(key, stepped | bottom)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TaskShellBorrowTests(unittest.TestCase):
    def test_borrowed_nodes_return_to_their_original_place(self):
        start = SCRIPT.index("  const borrowed=new Map();")
        end = SCRIPT.index("  function selectJobsTab(", start)
        harness = """
class El { constructor(id){this.id=id;this.parentElement=null;this.parentNode=null;this.children=[];this.nextSibling=null;}
  append(c){if(c.parentElement)c.parentElement.remove(c);c.parentElement=this;c.parentNode=this;this.children.push(c);this.relink();}
  insertBefore(c,ref){if(c.parentElement)c.parentElement.remove(c);c.parentElement=this;c.parentNode=this;this.children.splice(this.children.indexOf(ref),0,c);this.relink();}
  remove(c){this.children=this.children.filter(x=>x!==c);c.parentElement=null;c.parentNode=null;this.relink();}
  relink(){this.children.forEach((c,i)=>c.nextSibling=this.children[i+1]||null);} }
const home=new El('home'), host=new El('host'), a=new El('jd-form'), b=new El('after');
home.append(a);home.append(b);
const byId={'jd-form':a};
const document={getElementById:id=>byId[id]||null};
""" + SCRIPT[start:end] + """
borrow('jd-form',host);
const moved=a.parentElement===host;
restoreBorrowed();
process.stdout.write(JSON.stringify({moved, back:a.parentElement===home, order:home.children.map(c=>c.id)}));
"""
        result = subprocess.run([shutil.which("node"), "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '{"moved":true,"back":true,"order":["jd-form","after"]}')


if __name__ == "__main__":
    unittest.main()
