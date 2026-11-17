import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape
import zipfile

from pypdf import PdfReader, PdfWriter
from PIL import Image, ImageDraw, ImageFont

from interview_agent.document_text import (
    DocumentError, extract_direct, extract_document, local_ocr,
)
from interview_agent.knowledge_source import document_documents
from interview_agent.knowledge import tokens
import test_knowledge


def pdf_bytes(texts):
    """Real minimal PDFs combined with pypdf, with exact known page text."""
    writer = PdfWriter()
    for text in texts:
        stream = f'BT /F1 12 Tf 40 700 Td ({text}) Tj ET'.encode('ascii')
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
        content = bytearray(b'%PDF-1.4\n'); offsets = [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(content)); content.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
        start = len(content);content.extend(b'xref\n0 6\n0000000000 65535 f \n')
        for offset in offsets[1:]:content.extend(f'{offset:010d} 00000 n \n'.encode())
        content.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
        writer.add_page(PdfReader(io.BytesIO(content)).pages[0])
    output = io.BytesIO();writer.write(output);return output.getvalue()


def pptx_bytes(slides, targets=None):
    """A package whose presentation order deliberately differs from filename order."""
    output = io.BytesIO()
    ns = 'http://schemas.openxmlformats.org/'
    with zipfile.ZipFile(output, 'w') as bundle:
        ids, rels = [], []
        for i, (filename, text) in enumerate(slides, 1):
            ids.append(f'<p:sldId id="{255+i}" r:id="rId{i}"/>')
            target = targets[i-1] if targets else f'slides/{filename}.xml'
            rels.append(f'<Relationship Id="rId{i}" Type="{ns}officeDocument/2006/relationships/slide" Target="{target}"/>')
            bundle.writestr(f'ppt/slides/{filename}.xml',
                f'<p:sld xmlns:p="{ns}presentationml/2006/main" xmlns:a="{ns}drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
        bundle.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{ns}presentationml/2006/main" xmlns:r="{ns}officeDocument/2006/relationships"><p:sldIdLst>{"".join(ids)}</p:sldIdLst></p:presentation>')
        bundle.writestr('ppt/_rels/presentation.xml.rels', f'<Relationships xmlns="{ns}package/2006/relationships">{"".join(rels)}</Relationships>')
    return output.getvalue()


class DocumentTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def source(self, name, data):
        path = self.root / name; path.write_bytes(data);return path

    def test_native_pdf_pages_and_pptx_presentation_order_are_exact(self):
        pdf = extract_document(self.source('pitch.pdf', pdf_bytes(['PageOneRevenue', 'PageTwoRisk'])))
        self.assertEqual([u['text'] for u in pdf['units']], ['PageOneRevenue', 'PageTwoRisk'])
        self.assertEqual([u['unit_number'] for u in pdf['units']], [1, 2])
        pptx = extract_document(self.source('pitch.pptx', pptx_bytes([('slide10', '门店风险预警'), ('slide2', '第二张决策依据')])))
        self.assertEqual([u['text'] for u in pptx['units']], ['门店风险预警', '第二张决策依据'])
        self.assertTrue(all(not u['needs_review'] for u in pptx['units']))

    def test_encrypted_pdf_invalid_relationship_and_budget_fail_safely(self):
        writer = PdfWriter();writer.add_page(PdfReader(io.BytesIO(pdf_bytes(['private']))).pages[0]);writer.encrypt('test')
        out = io.BytesIO();writer.write(out)
        with self.assertRaisesRegex(DocumentError, 'document_encrypted'):
            extract_document(self.source('locked.pdf',out.getvalue()))
        with self.assertRaisesRegex(DocumentError, 'document_unsafe_relationship'):
            extract_direct(self.source('bad.pptx',pptx_bytes([('slide1','x')], ['../../../outside.xml'])))
        with patch('interview_agent.document_text.MAX_TEXT', 2):
            with self.assertRaisesRegex(DocumentError, 'document_text_budget'):
                extract_direct(self.source('long.pptx',pptx_bytes([('slide1','long text') ])))

    def test_no_text_is_reported_and_worker_timeout_is_explicit(self):
        value = extract_direct(self.source('empty.pptx',pptx_bytes([('slide1','')])))
        self.assertEqual(value['units_without_text'], [1])
        with patch('interview_agent.document_text.run_local', side_effect=subprocess.TimeoutExpired('worker', 1)):
            with self.assertRaisesRegex(DocumentError, 'document_timeout'):
                extract_document(self.root / 'source.pdf')

    def test_document_cache_handles_long_windows_repository_snapshot_paths(self):
        directory=self.root/'knowledge'/'owner'/'sources'/('repository-'+'x'*80)/('a'*40)
        directory.mkdir(parents=True)
        docs,metadata=document_documents(directory,{'path':'pitch.pdf'},pdf_bytes(['LongPathEvidence']))
        self.assertEqual(docs[0]['text'],'LongPathEvidence')
        self.assertEqual(metadata['text_units'],1)
        with patch('interview_agent.knowledge_source.extract_document',side_effect=AssertionError('Use verified cache')):
            again,_=document_documents(directory,{'path':'pitch.pdf'},pdf_bytes(['LongPathEvidence']))
        self.assertEqual(again[0]['text'],docs[0]['text'])

    def test_chinese_ocr_spacing_is_searchable_without_rewriting_evidence(self):
        self.assertTrue(set(tokens('门店经营风险')).issubset(tokens('门 店 经 营 风 险')))
        self.assertIn('permission_check',tokens('permission_check'))

    @unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows OCR integration')
    def test_local_ocr_batch_preserves_two_distinct_images(self):
        images = []
        for i, text in enumerate(('LOCAL REVENUE', 'LOCAL RISK')):
            image=Image.new('RGB',(800,180),'white')
            ImageDraw.Draw(image).text((30,45),text,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',48),fill='black')
            target=self.root/f'page-{i}.png';image.save(target);images.append(target)
        rows=local_ocr(images,self.root)
        self.assertEqual(len(rows),2)
        self.assertIn('REVENUE',rows[0]['text'].upper())
        self.assertIn('RISK',rows[1]['text'].upper())


class KnowledgeDocumentTests(unittest.TestCase):
    def setUp(self):
        self.case = test_knowledge.KnowledgeTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)

    def test_document_search_has_page_slide_citations_and_cached_offline_rebuild(self):
        case = self.case
        files={'README.md': b'Project overview\n', 'pitch.pdf': pdf_bytes(['RevenuePageOne','RiskPageTwo']),
               'pitch.pptx': pptx_bytes([('slide10','门店经营风险'),('slide2','第二页决策依据')])}
        case.remote.sources=files
        original=case.remote.get_json
        def wrapped(path):
            value=original(path)
            content=value['content'];value['content']='\n'.join(content[i:i+60] for i in range(0,len(content),60))+'\n'
            return value
        case.remote.get_json=wrapped
        case.cached(files);case.project();case.start()
        source=case.wait()[0]
        self.assertEqual(source['status'],'ready')
        self.assertEqual(source['coverage']['document_files'],2)
        self.assertEqual(source['coverage']['document_text_units'],4)
        snapshot=source['snapshot_id']
        rows=case.call('POST','/search',{'snapshot_ids':[snapshot],'query':'门店经营风险 RevenuePageOne','top_k':20})['items']
        docs=[r for r in rows if r['source_kind']=='document_text']
        self.assertTrue(any(r.get('page_number')==1 for r in docs))
        self.assertTrue(any(r.get('slide_number')==1 for r in docs))
        self.assertEqual(len({r['evidence_id'] for r in docs}),len(docs))
        self.assertTrue(all(r['line_basis']=='extracted_text' and '#L' not in r['source_url'] for r in docs))
        document_only=case.call('POST','/search',{'snapshot_ids':[snapshot],'query':'门店风险 RevenuePageOne',
            'source_kind':'document_text'})['items']
        self.assertTrue(document_only)
        self.assertTrue(all(r['source_kind']=='document_text' for r in document_only))
        code_only=case.call('POST','/search',{'snapshot_ids':[snapshot],'query':'Project',
            'source_kind':'source_text'})['items']
        self.assertTrue(code_only)
        self.assertTrue(all(r['source_kind']=='source_text' for r in code_only))
        case.call('POST','/search',{'snapshot_ids':[snapshot],'query':'x','source_kind':'unknown'},400)
        case.call('POST','/search',{'snapshot_ids':[snapshot],'query':'x','source_kind':[]},400)
        source['index_version']=0;case.client.app.state.knowledge.save_source(source)
        with patch('interview_agent.knowledge_source.extract_document',side_effect=AssertionError('Cached text must be reused')):
            case.client.app.state.knowledge.client_factory=case.offline
            case.call('POST','/warmup',{},202)
            rebuilt=case.wait()[0]
        self.assertEqual(rebuilt['status'],'ready')
        self.assertEqual(rebuilt['snapshot_id'],snapshot)

    def test_failed_document_does_not_hide_searchable_code(self):
        case=self.case
        files={'src/main.py': b'def reliable_source():\n    return True\n', 'broken.pdf': b'not a PDF'}
        case.remote.sources=files;case.cached(files);case.project();case.start()
        source=case.wait()[0]
        self.assertEqual(source['status'],'partial')
        self.assertEqual(source['coverage']['exclusion_reasons']['document_invalid'],1)
        self.assertTrue(case.call('POST','/search',{'snapshot_ids':[source['snapshot_id']],'query':'reliable_source'})['items'])


if __name__=='__main__':
    unittest.main()
