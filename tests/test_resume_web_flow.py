"""Same-origin workbench through the real career engine; synthetic sources only."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import json
import time
from test_experience_import import ExperienceAgent, INPUT

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'offerpilot' / 'web'))
import test_career_pipeline as pipeline
import backend
import server
import career_user_runtime


class ResumeWebFlowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.engine = pipeline.CareerPipelineTests()
        self.engine.setUp()
        self.stack.callback(self.engine.tearDown)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(backend, 'WEB_DIR', root))
        def upstream(method, path, payload=None):
            return self.engine.call(method, path, payload, expected=202 if method == 'POST' and path.endswith(('/projects', '/experience-import')) else 201 if method == 'POST' and ('resume-drafts' in path) else 200)
        self.stack.enter_context(patch.object(career_user_runtime, 'upstream', upstream))
        self.http = server.make_server('127.0.0.1', 0)
        thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        thread.start()
        self.stack.callback(self.http.server_close)
        self.stack.callback(self.http.shutdown)
        self.url = f'http://127.0.0.1:{self.http.server_port}'

    def request(self, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        with urllib.request.urlopen(urllib.request.Request(self.url + path, body, {'Content-Type': 'application/json'})) as response:
            return response.read()

    def api(self, path, data=None):
        return json.loads(self.request('/api/career-user' + path + '?mode=user', data))

    def test_select_preview_save_reopen_and_print(self):
        repos = self.api('/github/repositories')
        self.assertTrue(repos['items'])
        project = self.engine.prepare()
        material = self.api(f"/projects/{project['project_id']}/confirm", {'claim_ids': [project['claims'][0]['claim_id']], 'confirmed': True})
        self.request('/api/action', {'action': 'save-profile', 'mode': 'user', 'profile': {'truth_confirmed': True, 'basic': {'name': 'Synthetic Candidate'}, 'skills': {'tools': ['Python']}}})
        draft = self.api('/resume-drafts', {'material_id': material['material_id']})
        self.assertIn('Synthetic Candidate', draft['markdown'])
        version = self.api(f"/resume-drafts/{draft['draft_id']}/save", {'confirmed': True})
        repeat = self.api(f"/resume-drafts/{draft['draft_id']}/save", {'confirmed': True})
        self.assertEqual(version['created_at'], repeat['created_at'])
        saved = self.api('/resumes/' + version['resume_version_id'])
        self.assertEqual(saved['markdown'], draft['markdown'])
        self.assertEqual(saved['markdown_sha256'], draft['markdown_sha256'])
        html = self.request(f"/api/career-user/resumes/{version['resume_version_id']}/print?mode=user").decode()
        self.assertRegex(html, r'<h1(?: [^>]*)?>Synthetic Candidate</h1>')
        self.assertIn('career-resume.css', html)
        pdf = self.request(f"/api/career-user/resumes/{version['resume_version_id']}/pdf?mode=user")
        self.assertTrue(pdf.startswith(b'%PDF-'))
        for template in ('professional', 'classic'):
            html = self.request(f"/api/career-user/resumes/{version['resume_version_id']}/print?mode=user&template={template}").decode()
            self.assertIn(f'data-resume-template="{template}"', html)
            pdf = self.request(f"/api/career-user/resumes/{version['resume_version_id']}/pdf?mode=user&template={template}")
            self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertEqual(self.api('/resumes/' + version['resume_version_id'])['markdown_sha256'], draft['markdown_sha256'])
        self.assertEqual(self.engine.agent.calls, ['prepare'])

    def test_manual_file_text_preview_save_and_pdf_without_github(self):
        import base64
        self.engine.client.app.state.career.agent = ExperienceAgent()
        self.engine.client.app.state.career.auth.token = lambda: self.fail('Unexpected GitHub access')
        text = '访谈了12位用户，整理注册流程的反馈。'
        extracted = self.api('/experience-text', {'filename': '作品说明.txt', 'content_base64': base64.b64encode(text.encode()).decode()})
        self.assertEqual(extracted['text'], text)
        project = self.api('/experience-import', {**INPUT, 'source_text': extracted['text']})
        for _ in range(100):
            project = self.api('/projects/' + project['project_id'])
            if project['status'] != 'preparing':
                break
            time.sleep(.01)
        self.assertEqual(project['status'], 'ready')
        material = self.api(f"/projects/{project['project_id']}/confirm", {'claim_ids': [project['claims'][0]['claim_id']], 'confirmed': True})
        self.request('/api/action', {'action': 'save-profile', 'mode': 'user', 'profile': {'truth_confirmed': True,
            'basic': {'name': '虚构产品候选人', 'wechat': 'sample_wechat', 'email': 'candidate@example.invalid',
                      'links': 'https://portfolio.example.invalid/home'},
            'projects': [{'name': '个人作品项目', 'role': '产品', 'summary': '作品说明：https://portfolio.example.invalid/case'}]}})
        draft = self.api('/resume-drafts', {'material_id': material['material_id']})
        self.assertIn('## 实习与工作经历', draft['markdown'])
        self.assertIn('## 项目经历', draft['markdown'])
        for text in ('sample_wechat', 'candidate@example.invalid', 'https://portfolio.example.invalid/home', '个人作品项目', INPUT['portfolio_url']):
            self.assertIn(text, draft['markdown'])
        version = self.api(f"/resume-drafts/{draft['draft_id']}/save", {'confirmed': True})
        saved = self.api('/resumes/' + version['resume_version_id'])
        self.assertEqual(saved['markdown'], draft['markdown'])
        pdf = self.request(f"/api/career-user/resumes/{version['resume_version_id']}/pdf?mode=user")
        self.assertTrue(pdf.startswith(b'%PDF-'))
        from io import BytesIO
        from pypdf import PdfReader
        uris = {str(ref.get_object().get('/A', {}).get('/URI')) for page in PdfReader(BytesIO(pdf)).pages for ref in page.get('/Annots', [])}
        self.assertIn('https://portfolio.example.invalid/home', uris)
        self.assertIn(INPUT['portfolio_url'], uris)


if __name__ == '__main__':
    if '--serve' in sys.argv:
        fixture = ResumeWebFlowTests()
        fixture.setUp()
        print(fixture.url, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            fixture.doCleanups()
    else:
        unittest.main()
