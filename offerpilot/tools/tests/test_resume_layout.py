"""Resume templates preserve literal content, readable text and page structure."""
from io import BytesIO
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'web'))
import career_user_runtime as personal
import backend
from resume_layout import blocks, print_html
from resume_pdf import render_pdf


SAMPLE = '# 排版样例\nexample@example.invalid | 上海\n\n## 实习与工作经历\n### 示例团队 · 产品实习生\n2026.06 - 2026.08\n- 需求分析：整理用户反馈，记录方案取舍。\n作品集：https://example.invalid/work\n'


class ResumeLayoutTests(unittest.TestCase):
    def test_web_links_are_clickable_without_interpreting_user_markup(self):
        text = '# 链接样例\nhttps://portfolio.example.invalid/work?a=1&b=2\n## 作品集\n作品集：https://example.invalid/case。\n- 来源：javascript:alert(1) <script>data</script>\n'
        html = print_html(text).decode()
        self.assertIn('href="https://portfolio.example.invalid/work?a=1&amp;b=2"', html)
        self.assertIn('href="https://example.invalid/case"', html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;data&lt;/script&gt;', html)

    @unittest.skipUnless((Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/simsun.ttc').is_file(), 'Chinese fonts unavailable')
    def test_pdf_contains_embedded_fonts_and_clickable_portfolio_links(self):
        from pypdf import PdfReader
        source = SAMPLE + '\n项目链接：https://github.com/example/demo\n'
        for template in ('professional', 'classic'):
            reader = PdfReader(BytesIO(render_pdf(source, template=template)))
            uris = set()
            fonts = []
            for page in reader.pages:
                for ref in page.get('/Annots', []):
                    action = ref.get_object().get('/A', {})
                    if action.get('/S') == '/URI':
                        uris.add(str(action['/URI']))
                for font in page['/Resources']['/Font'].values():
                    font = font.get_object()
                    if font.get('/FontDescriptor'):
                        descriptor = font['/FontDescriptor'].get_object()
                        fonts.append((str(font['/BaseFont']), '/FontFile2' in descriptor))
            self.assertIn('https://example.invalid/work', uris)
            self.assertIn('https://github.com/example/demo', uris)
            self.assertTrue(fonts)
            self.assertTrue(all(embedded for _, embedded in fonts))
            self.assertTrue(any(('MicrosoftYaHei' if template == 'professional' else 'SimSun') in name for name, _ in fonts))

    def test_content_roles_and_user_markup_are_preserved_safely(self):
        rows = blocks(SAMPLE)
        self.assertEqual(rows[1]['kind'], 'contact')
        self.assertEqual(rows[4]['kind'], 'meta')
        self.assertEqual(rows[-1]['kind'], 'link')
        for template in ('professional', 'classic'):
            html = print_html(SAMPLE + '- 校验：<script>alert(1)</script> 与 `原文`。', '产品经理', template).decode()
            self.assertIn('求职意向 · 产品经理', html)
            self.assertIn('<b>需求分析：</b>', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)
            self.assertNotIn('`', html)
            self.assertIn('example@example.invalid', html)

    def test_export_accepts_only_known_templates_before_reading_saved_content(self):
        with patch.object(personal, 'upstream') as upstream:
            for function, suffix in ((personal.pdf_document, 'pdf'), (personal.print_document, 'print')):
                for query in ({'mode': 'user', 'template': 'unknown'}, {'mode': 'demo', 'template': 'classic'},
                              {'mode': 'user', 'template': 'classic', 'stylesheet': 'https://example.com'}):
                    with self.assertRaises(backend.ApiError):
                        function('/api/career-user/resumes/resume_test/' + suffix, query)
            upstream.assert_not_called()

    @unittest.skipUnless((Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/simsun.ttc').is_file(), 'Chinese fonts unavailable')
    def test_both_pdf_templates_are_a4_extractable_and_do_not_mutate_saved_text(self):
        from pypdf import PdfReader
        original = {'markdown': SAMPLE, 'job_snapshot': {'role': '产品经理'}}
        with patch.object(personal, 'upstream', return_value=original):
            for template in ('professional', 'classic'):
                pdf = personal.pdf_document('/api/career-user/resumes/resume_test/pdf', {'mode': 'user', 'template': template})
                reader = PdfReader(BytesIO(pdf))
                text = ''.join(page.extract_text() for page in reader.pages)
                self.assertIn('排版样例', text)
                self.assertIn('需求分析', text)
                self.assertIn('求职意向', text)
                self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.28, places=1)
                self.assertEqual(len(reader.pages), 1)
        self.assertEqual(original['markdown'], SAMPLE)

    @unittest.skipUnless((Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/simsun.ttc').is_file(), 'Chinese fonts unavailable')
    def test_long_resume_paginates_without_dropping_text_or_leaving_lone_headings(self):
        from pypdf import PdfReader
        source = '# 长内容样例\n'
        for index in range(14):
            source += f'\n## 经历栏目{index}\n### 工作条目{index}\n- 关键贡献：' + '整理输入与异常处理，保留可追溯的结果。' * 10 + '\n'
        for template in ('professional', 'classic'):
            reader = PdfReader(BytesIO(render_pdf(source, template=template)))
            self.assertGreater(len(reader.pages), 1)
            combined = ''.join(page.extract_text() for page in reader.pages)
            for index in range(14):
                self.assertIn(f'经历栏目{index}', combined)
                self.assertIn(f'工作条目{index}', combined)
            for page in reader.pages:
                last_line = page.extract_text().strip().splitlines()[-1].strip()
                self.assertFalse(last_line.startswith(('经历栏目', '工作条目')))
