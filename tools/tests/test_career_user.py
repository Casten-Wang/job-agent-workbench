from pathlib import Path
from io import BytesIO
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'web'))
import backend
import career_user_runtime as personal


class CareerUserBridgeTests(unittest.TestCase):
    def test_note_routes_are_owner_bound_and_reject_unlisted_operations(self):
        with patch.object(personal, 'upstream', return_value={'items': []}) as upstream:
            _, status = personal.dispatch('POST', '/api/career-user/notes/subscriptions', {'mode': 'user'},
                                         {'url': 'https://xhslink.com/a/synthetic', 'interval_hours': 24})
            self.assertEqual(status, 201)
            self.assertEqual(upstream.call_args.args[1], '/v1/notes/subscriptions')
            personal.dispatch('GET', '/api/career-user/notes/inbox', {'mode': 'user', 'limit': '10'})
            self.assertEqual(upstream.call_args.args[1], '/v1/notes/inbox?limit=10')
            personal.dispatch('POST', '/api/career-user/notes/subscriptions/sub_test/pause', {'mode': 'user'}, {})
            self.assertEqual(upstream.call_args.args[1], '/v1/notes/subscriptions/sub_test/pause')
            for method, path, query, payload in (
                ('GET', '/api/career-user/notes/inbox', {'mode': 'demo'}, {}),
                ('GET', '/api/career-user/notes/inbox', {'mode': 'user', 'owner': 'other'}, {}),
                ('POST', '/api/career-user/notes/http://example.com', {'mode': 'user'}, {}),
                ('POST', '/api/career-user/notes/subscriptions/sub_test/pause', {'mode': 'user'}, {'owner': 'other'})):
                upstream.reset_mock()
                with self.assertRaises(backend.ApiError):
                    personal.dispatch(method, path, query, payload)
                upstream.assert_not_called()

    def test_knowledge_routes_are_user_only_and_use_fixed_personal_service(self):
        with patch.object(personal, 'upstream', return_value={'queued': 1}) as upstream:
            result, status = personal.dispatch('POST', '/api/career-user/knowledge/warmup', {'mode': 'user'}, {})
            self.assertEqual(status, 202)
            upstream.assert_called_once_with('POST', '/v1/knowledge/warmup', {})
            with self.assertRaises(backend.ApiError):
                personal.dispatch('POST', '/api/career-user/knowledge/warmup', {'mode': 'demo'}, {})
            upstream.reset_mock()
            with self.assertRaises(backend.ApiError):
                personal.dispatch('GET', '/api/career-user/knowledge/sources', {'mode': 'user', 'owner': 'other'})
            upstream.assert_not_called()

    def test_experience_file_is_extracted_locally_without_model_or_profile_writes(self):
        import base64
        with patch.object(personal, 'upstream') as upstream, patch.object(backend, 'get_store') as store:
            result, status = personal.dispatch('POST', '/api/career-user/experience-text', {'mode': 'user'},
                {'filename': '作品说明.txt', 'content_base64': base64.b64encode('实际作品说明'.encode()).decode()})
            self.assertEqual(status, 200)
            self.assertEqual(result['text'], '实际作品说明')
            upstream.assert_not_called()
            store.assert_not_called()
            for data in ({'filename': 'bad.txt', 'content_base64': '!!!'},
                         {'filename': 'bad.exe', 'content_base64': 'YQ=='},
                         {'filename': 'big.txt', 'content_base64': base64.b64encode(b'a' * 20001).decode()}):
                with self.assertRaises(backend.ApiError):
                    personal.dispatch('POST', '/api/career-user/experience-text', {'mode': 'user'}, data)

    def test_experience_import_requires_user_mode_and_uses_personal_engine(self):
        with patch.object(personal, 'upstream', return_value={'project_id': 'test'}) as upstream:
            data = {'kind': 'internship'}
            _, status = personal.dispatch('POST', '/api/career-user/experience-import', {'mode': 'user'}, data)
            self.assertEqual(status, 202)
            upstream.assert_called_once_with('POST', '/v1/career/experience-import', data)
            upstream.reset_mock()
            with self.assertRaises(backend.ApiError):
                personal.dispatch('POST', '/api/career-user/experience-import', {'mode': 'demo'}, data)
            upstream.assert_not_called()
    @unittest.skipUnless((Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/simsun.ttc').is_file(), 'Chinese font unavailable')
    def test_pdf_export_embeds_extractable_chinese_and_preserves_literal_markup(self):
        from pypdf import PdfReader
        with patch.object(personal, 'upstream', return_value={'markdown': '# 测试候选人\n## 项目经历\n- 校验 <script> 与 `输入`。'}) as upstream:
            pdf = personal.pdf_document('/api/career-user/resumes/resume_test/pdf', {'mode': 'user'})
        self.assertTrue(pdf.startswith(b'%PDF-'))
        reader = PdfReader(BytesIO(pdf))
        text = ''.join(page.extract_text() for page in reader.pages)
        self.assertIn('测试候选人', text)
        self.assertIn('<script>', text)
        self.assertIn('输入', text)
        self.assertNotIn('`', text)
        upstream.assert_called_once_with('GET', '/v1/career/resumes/resume_test')

    def test_pdf_export_rejects_demo_and_invalid_paths_before_reading_version(self):
        with patch.object(personal, 'upstream') as upstream:
            for path, query in [('/api/career-user/resumes/resume_test/pdf', {'mode': 'demo'}),
                                ('/api/career-user/resumes/../pdf', {'mode': 'user'})]:
                with self.assertRaises(backend.ApiError):
                    personal.pdf_document(path, query)
            upstream.assert_not_called()

    def test_demo_mode_and_arbitrary_routes_are_rejected(self):
        with patch.object(personal,'upstream') as upstream:
            with self.assertRaises(backend.ApiError):
                personal.dispatch('GET','/api/career-user/github/status',{'mode':'demo'})
            with self.assertRaises(backend.ApiError):
                personal.dispatch('GET','/api/career-user/http://example.com',{'mode':'user'})
            upstream.assert_not_called()

    def test_repository_query_is_limited_to_pagination(self):
        with patch.object(personal,'upstream',return_value={'items':[]}) as upstream:
            result,status=personal.dispatch('GET','/api/career-user/github/repositories',{'mode':'user','page':'2'})
            self.assertEqual(status,200)
            self.assertEqual(upstream.call_args.args[1],'/v1/career/github/repositories?page=2')
            with self.assertRaises(backend.ApiError):
                personal.dispatch('GET','/api/career-user/github/repositories',{'mode':'user','url':'https://example.com'})

    def test_resume_profile_comes_from_local_store_not_browser(self):
        profile={'truth_confirmed':True,'basic':{'name':'虚构候选人'}}
        with patch.object(backend,'get_store') as get_store,patch.object(backend,'profile_public',return_value=profile),patch.object(personal,'upstream',return_value={}) as upstream:
            personal.dispatch('POST','/api/career-user/resume-drafts',{'mode':'user'},{'session_id':'opuser_test'})
            self.assertEqual(upstream.call_args.args[2]['profile'],profile)
            self.assertEqual(get_store.call_args.args,('user',))
            with self.assertRaises(backend.ApiError):
                personal.dispatch('POST','/api/career-user/resume-drafts',{'mode':'user'},{'session_id':'opuser_test','profile':profile})

    def test_interview_target_is_frozen_on_server(self):
        responses=[{'target':{'role':'合成岗位'},'evidence':[]}, {'is_demo':False}]
        with patch.object(personal,'upstream',side_effect=responses) as upstream:
            personal.dispatch('POST','/api/career-user/interviews',{'mode':'user'},
                              {'material_id':'mat_user','session_id':'opuser_test','interview_mode':'mock_interview'})
            self.assertEqual(upstream.call_args.args[2]['target'],{'role':'合成岗位'})

    def test_missing_profile_is_not_replaced_with_invented_resume_facts(self):
        with patch.object(backend,'get_store'),patch.object(backend,'profile_public',return_value={'truth_confirmed':False,'basic':{}}),patch.object(personal,'upstream') as upstream:
            with self.assertRaisesRegex(backend.ApiError,'个人资料'):
                personal.dispatch('POST','/api/career-user/resume-drafts',{'mode':'user'},{'session_id':'opuser_test'})
            upstream.assert_not_called()

    def test_direct_resume_uses_confirmed_material_and_server_profile(self):
        profile={'truth_confirmed':True,'basic':{'name':'测试候选人'}}
        with patch.object(backend,'get_store'),patch.object(backend,'profile_public',return_value=profile),patch.object(personal,'upstream',return_value={'assessment_status':'not_assessed'}) as upstream:
            result,status=personal.dispatch('POST','/api/career-user/resume-drafts',{'mode':'user'},{'material_id':'mat_confirmed'})
            self.assertEqual(status,201)
            self.assertEqual(upstream.call_args.args[2],{'material_id':'mat_confirmed','profile':profile})
            self.assertNotIn('session_id',upstream.call_args.args[2])
            self.assertEqual(result['assessment_status'],'not_assessed')

    def test_print_document_escapes_user_text_and_requires_user_mode(self):
        with patch.object(personal,'upstream',return_value={'markdown':'# <script>alert(1)</script>\n- synthetic fact'}):
            html=personal.print_document('/api/career-user/resumes/resume_test/print',{'mode':'user'}).decode()
            self.assertNotIn('<script>',html)
            self.assertIn('&lt;script&gt;',html)
            self.assertIn('/career-resume.css',html)
            with self.assertRaises(backend.ApiError):
                personal.print_document('/api/career-user/resumes/resume_test/print',{'mode':'demo'})


class ResumeProfileEntryTests(unittest.TestCase):
    """定制简历从个人资料带出经历：条目选择、字段映射与草稿裁剪。"""

    PROFILE = {
        "truth_confirmed": True,
        "basic": {"name": "虚构候选人"},
        "education": [],
        "skills": {"tools": [], "strengths": []},
        "experiences": [
            {"company": "虚构公司甲", "title": "产品实习生", "start": "2026.06", "end": "2026.08",
             "summary": "负责新用户引导改版，访谈 12 位用户。"},
            {"company": "虚构公司乙", "title": "运营专员", "start": "2025.01", "end": "2025.06",
             "summary": "维护社群。"},
        ],
        "projects": [
            {"name": "虚构项目一", "role": "主设计", "start": "2026.01", "end": "2026.03",
             "summary": "设计排课工具。"},
        ],
    }

    def _dispatch(self, payload, profile=None, upstream=None):
        with patch.object(backend, 'get_store'), \
                patch.object(backend, 'profile_public', return_value=profile or self.PROFILE), \
                patch.object(personal, 'upstream', return_value=upstream or {'project_id': 'project_test'}) as mocked:
            result, status = personal.dispatch('POST', '/api/career-user/profile-experience', {'mode': 'user'}, payload)
        return result, status, mocked

    def test_profile_entries_compose_one_experience_import(self):
        result, status, upstream = self._dispatch({
            'items': [{'section': 'experiences', 'index': 0}, {'section': 'projects', 'index': 0}],
            'role': '产品经理', 'jd': '负责需求分析', 'confirmed': True, 'model_consent': True,
        })
        self.assertEqual(status, 202)
        self.assertEqual(result['project_id'], 'project_test')
        self.assertEqual(upstream.call_args.args[1], '/v1/career/experience-import')
        payload = upstream.call_args.args[2]
        self.assertEqual(payload['kind'], 'internship')
        self.assertEqual(payload['name'], '产品实习生')
        self.assertEqual(payload['organization'], '虚构公司甲')
        self.assertEqual(payload['position'], '产品实习生')
        self.assertEqual(payload['role'], '产品经理')
        self.assertIn('访谈 12 位用户', payload['context'])
        self.assertIn('项目经历：虚构项目一', payload['source_text'])
        self.assertIn('工作 / 实习经历：虚构公司甲 · 产品实习生（2026.06 - 2026.08）', payload['source_text'])
        self.assertTrue(payload['confirmed'] and payload['model_consent'])

    def test_profile_experience_requires_consent_role_and_known_entries(self):
        base = {'items': [{'section': 'experiences', 'index': 0}], 'role': '产品经理',
                'confirmed': True, 'model_consent': True}
        with patch.object(backend, 'get_store'), \
                patch.object(backend, 'profile_public', return_value=self.PROFILE), \
                patch.object(personal, 'upstream') as upstream:
            for change in ({'confirmed': False}, {'model_consent': False}, {'role': ' '},
                           {'items': []}, {'items': [{'section': 'experiences', 'index': 9}]},
                           {'items': [{'section': 'experiences', 'index': 0, 'note': '长' * 401}]},
                           {'items': [{'section': 'photo', 'index': 0}]}):
                with self.subTest(change=list(change)):
                    with self.assertRaises(backend.ApiError):
                        personal.dispatch('POST', '/api/career-user/profile-experience',
                                          {'mode': 'user'}, {**base, **change})
            with self.assertRaises(backend.ApiError):
                personal.dispatch('POST', '/api/career-user/profile-experience', {'mode': 'demo'}, base)
            upstream.assert_not_called()

    def test_entry_note_backfills_missing_summary(self):
        profile = dict(self.PROFILE)
        profile['experiences'] = [{'company': '虚构公司丙', 'title': '实习生', 'start': '', 'end': '', 'summary': ''}]
        _, _, upstream = self._dispatch({
            'items': [{'section': 'experiences', 'index': 0, 'note': '整理竞品文档'}],
            'role': '产品经理', 'confirmed': True, 'model_consent': True,
        }, profile=profile)
        payload = upstream.call_args.args[2]
        self.assertEqual(payload['kind'], 'internship')
        self.assertEqual(payload['context'], '整理竞品文档')
        self.assertIn('本人补充：整理竞品文档', payload['source_text'])

    def test_entry_without_summary_or_note_is_rejected(self):
        profile = dict(self.PROFILE)
        profile['projects'] = [{'name': '虚构项目二', 'role': '', 'start': '', 'end': '', 'summary': ''}]
        with patch.object(backend, 'get_store'), \
                patch.object(backend, 'profile_public', return_value=profile), \
                patch.object(personal, 'upstream') as upstream:
            with self.assertRaises(backend.ApiError):
                personal.dispatch('POST', '/api/career-user/profile-experience', {'mode': 'user'}, {
                    'items': [{'section': 'projects', 'index': 0}],
                    'role': '产品经理', 'confirmed': True, 'model_consent': True,
                })
            upstream.assert_not_called()

    def test_resume_draft_can_be_limited_to_checked_entries(self):
        with patch.object(backend, 'get_store'), \
                patch.object(backend, 'profile_public', return_value=self.PROFILE), \
                patch.object(personal, 'upstream', return_value={'markdown': '# 虚构候选人'}) as upstream:
            personal.dispatch('POST', '/api/career-user/resume-drafts', {'mode': 'user'}, {
                'material_id': 'material_test',
                'items': [{'section': 'projects', 'index': 0}, {'section': 'experiences', 'index': 1}],
            })
        sent = upstream.call_args.args[2]
        self.assertEqual([row['company'] for row in sent['profile']['experiences']], ['虚构公司乙'])
        self.assertEqual([row['name'] for row in sent['profile']['projects']], ['虚构项目一'])
        self.assertNotIn('items', sent)
