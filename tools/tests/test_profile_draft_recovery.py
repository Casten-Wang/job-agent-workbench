"""Draft capture must include dynamic rows and never persist consent."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


SOURCE = (Path(__file__).resolve().parents[2] / "web/static/workbench.js").read_text(encoding="utf-8")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ProfileDraftRecoveryTests(unittest.TestCase):
    def capture(self, event):
        cache = SOURCE[SOURCE.index("  function cacheProfileDraft("):SOURCE.index("  function draftField(")]
        listeners = SOURCE[SOURCE.index("  window.addEventListener('offerpilot:profile-draft'"):SOURCE.index("  window.addEventListener('offerpilot:agent'")]
        harness = """
const callbacks={}, drafts={fields:{'profile-city':'stale','jd-text':'keep'}}, document={
  addEventListener:(event,fn)=>callbacks[event]=fn};
const window={addEventListener:(event,fn)=>callbacks[event]=fn};
const collectProfileForm=()=>({education:[{school:'Edited University'}],truth_confirmed:true});
const draftField=()=>false;
let stored;
const saveDrafts=()=>stored=JSON.parse(JSON.stringify(drafts));
""" + cache + listeners + """
callbacks[EVENT]({target:{closest:selector=>selector==='#profile-form'}});
process.stdout.write(JSON.stringify(stored));
""".replace("EVENT", json.dumps(event))
        result = subprocess.run([shutil.which("node"), "-e", harness], capture_output=True,
                                text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_dynamic_inputs_without_ids_are_captured(self):
        for event in ("input", "change"):
            with self.subTest(event=event):
                stored = self.capture(event)
                self.assertEqual(stored["profile"]["education"], [{"school": "Edited University"}])
                self.assertFalse(stored["profile"]["truth_confirmed"])
                self.assertEqual(stored["fields"], {"jd-text": "keep"})

    def test_programmatic_profile_updates_replace_the_cached_profile(self):
        stored = self.capture("offerpilot:profile-draft")
        self.assertEqual(stored["profile"]["education"], [{"school": "Edited University"}])
        self.assertFalse(stored["profile"]["truth_confirmed"])


if __name__ == "__main__":
    unittest.main()
