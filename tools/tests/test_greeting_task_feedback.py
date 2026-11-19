"""Exercise the actual queue poller with a fake clock and task responses."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

SOURCE = (Path(__file__).resolve().parents[2] / "web/static/app.js").read_text(encoding="utf-8")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class GreetingTaskFeedbackTests(unittest.TestCase):
    def run_poller(self, final_status, *, ready=False, task_id="task-1"):
        functions = SOURCE[SOURCE.index("function stopQueueGreetingWatch()"):SOURCE.index("const DELIVERY_STATUS_META")]
        harness = """
const state={queueGreetingWatch:null,offerpilotPollTimer:true,offerpilotLastTask:{id:'task-1',status:'running'}};
const timers=[], notices=[];let opened=0;
const window={setTimeout:fn=>{timers.push(fn);return timers.length},clearTimeout:()=>{}};
const document={getElementById:()=>({})};
const showInline=(node,message,kind)=>notices.push({message,kind});
const setStatus=()=>{};const refreshOfferPilot=async()=>{};
let isReady=false;
const approvedQueueRows=()=>[{id:'job-1',greeting:{ready:isReady}}];
const openDeliveryModal=()=>opened++;
""" + functions + """
(async()=>{
watchQueueGreetings(['job-1'],null,'task-1');
for(let i=0;i<40;i++){await timers.shift()();}
const runningAfter40=Boolean(state.queueGreetingWatch);
state.offerpilotLastTask={id:TASK_ID,status:FINAL,error:'真实模型错误 (network)'};
isReady=READY;
await timers.shift()();
console.log(JSON.stringify({runningAfter40,watching:Boolean(state.queueGreetingWatch),opened,notices}));
})();
""".replace("TASK_ID", json.dumps(task_id)).replace("FINAL", json.dumps(final_status)).replace("READY", json.dumps(ready))
        result = subprocess.run([shutil.which("node"), "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_running_task_does_not_lose_watcher_after_75_seconds(self):
        result = self.run_poller("running")
        self.assertTrue(result["runningAfter40"])
        self.assertTrue(result["watching"])
        self.assertEqual(result["opened"], 0)

    def test_failed_task_displays_reason_and_never_opens_preview(self):
        result = self.run_poller("failed")
        self.assertFalse(result["watching"])
        self.assertEqual(result["opened"], 0)
        self.assertIn("network", result["notices"][-1]["message"])
        self.assertEqual(result["notices"][-1]["kind"], "error")

    def test_ready_rows_open_only_the_review_preview(self):
        result = self.run_poller("completed", ready=True)
        self.assertEqual(result["opened"], 1)
        self.assertFalse(result["watching"])

    def test_unrelated_failure_does_not_end_current_watch(self):
        result = self.run_poller("failed", task_id="other-task")
        self.assertTrue(result["watching"])
        self.assertEqual(result["notices"], [])
