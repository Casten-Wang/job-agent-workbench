"""Bounded PDF/PPTX text extraction, with optional local Windows OCR.

The worker reads only server-owned files and emits text; document instructions,
macros, external relationships and repository code are never executed.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET
import zipfile

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_UNITS = 100
MAX_TEXT = 200_000
MAX_XML = 4 * 1024 * 1024
MAX_EXPANDED = 40 * 1024 * 1024
EXTRACTOR_VERSION = 2
WORKER_TIMEOUT = 90
OCR_IMAGE_LIMIT = 2400


class DocumentError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def run_local(command, *, timeout):
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'LOCALAPPDATA', 'USERPROFILE'}}
    return subprocess.run(command, capture_output=True, timeout=timeout, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def local_ocr(images, directory):
    if not images:
        return []
    powershell = shutil.which('powershell.exe') if os.name == 'nt' else None
    if not powershell:
        return [{'text': '', 'error': 'document_ocr_unavailable'} for _ in images]
    request = directory / 'ocr-input.json'
    request.write_text(json.dumps([str(p.resolve()) for p in images]), encoding='utf-8')
    try:
        result = run_local([powershell, '-NoProfile', '-NonInteractive', '-File',
            str(Path(__file__).with_name('document_ocr.ps1')), '-InputList', str(request.resolve())], timeout=45)
        if result.returncode:
            raise ValueError('OCR failed')
        rows = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(rows, list) or len(rows) != len(images):
            raise ValueError('OCR output shape differs')
        return rows
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return [{'text': '', 'error': 'document_ocr_failed'} for _ in images]


def xml_member(bundle, name):
    entry = bundle.getinfo(name)
    if entry.file_size > MAX_XML or entry.flag_bits & 1:
        raise DocumentError('document_xml_budget')
    data = bundle.read(entry)
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise DocumentError('document_unsafe_xml')
    return ET.fromstring(data)


def relationships(bundle, part):
    relfile = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
    if relfile not in bundle.namelist():
        return {}
    result = {}
    for row in xml_member(bundle, relfile):
        if row.attrib.get('TargetMode') == 'External':
            continue
        target = row.attrib.get('Target', '')
        if '\\' in target or ':' in target or not target:
            raise DocumentError('document_unsafe_relationship')
        target = posixpath.normpath(target.lstrip('/') if target.startswith('/') else
                                   posixpath.join(posixpath.dirname(part), target))
        if not target.startswith('ppt/') or '/..' in target:
            raise DocumentError('document_unsafe_relationship')
        result[row.attrib['Id']] = (target, row.attrib.get('Type', '').rsplit('/', 1)[-1])
    return result


def local_name(tag):
    return tag.rsplit('}', 1)[-1]


def image_png(data, output):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((OCR_IMAGE_LIMIT, OCR_IMAGE_LIMIT))
        image.convert('RGB').save(output, format='PNG')


def pptx_units(content, directory):
    units, pending, images = [], [], []
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or len(names) > 5000:
            raise DocumentError('document_invalid_package')
        if sum(info.file_size for info in bundle.infolist()) > MAX_EXPANDED:
            raise DocumentError('document_expanded_budget')
        presentation = xml_member(bundle, 'ppt/presentation.xml')
        rels = relationships(bundle, 'ppt/presentation.xml')
        slide_ids = [node for node in presentation.iter() if local_name(node.tag) == 'sldId']
        if not 1 <= len(slide_ids) <= MAX_UNITS:
            raise DocumentError('document_page_limit')
        for number, slide_id in enumerate(slide_ids, 1):
            rid = next((v for k, v in slide_id.attrib.items() if k.endswith('}id')), None)
            path, kind = rels.get(rid, ('', ''))
            if kind != 'slide' or not path.startswith('ppt/slides/'):
                raise DocumentError('document_invalid_slide')
            slide = xml_member(bundle, path)
            paragraphs = []
            for paragraph in slide.iter():
                if local_name(paragraph.tag) == 'p':
                    text = ''.join(n.text or '' if local_name(n.tag) == 't' else '\n'
                        for n in paragraph.iter() if local_name(n.tag) in {'t', 'br'})
                    if text.strip():
                        paragraphs.append(text)
            unit = {'unit_type': 'slide', 'unit_number': number, 'text': '\n'.join(paragraphs),
                    'extraction_kind': 'pptx_text'}
            units.append(unit)
            if unit['text'].strip():
                continue
            slide_rels = relationships(bundle, path)
            refs = [v for n in slide.iter() if local_name(n.tag) == 'blip'
                    for k, v in n.attrib.items() if k.endswith('}embed')]
            if len(refs) > 8:
                raise DocumentError('document_image_budget')
            for i, ref in enumerate(dict.fromkeys(refs)):
                image_path, relation_kind = slide_rels.get(ref, ('', ''))
                if relation_kind != 'image':
                    continue
                entry = bundle.getinfo(image_path)
                if entry.file_size > MAX_DOCUMENT_BYTES:
                    raise DocumentError('document_image_budget')
                output = directory / f'slide-{number}-{i}.png'
                image_png(bundle.read(entry), output)
                images.append(output)
                pending.append(number - 1)
    for index, result in zip(pending, local_ocr(images, directory)):
        unit = units[index]
        unit['text'] += ('\n' if unit['text'] else '') + result.get('text', '')
        unit.update(extraction_kind='pptx_ocr', ocr_language=result.get('language'),
                    error=result.get('error'))
    return units


def pdf_units(content, directory, source):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        raise DocumentError('document_encrypted')
    if not 1 <= len(reader.pages) <= MAX_UNITS:
        raise DocumentError('document_page_limit')
    units, pending, images = [], [], []
    renderer = shutil.which('pdftoppm')
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ''
        unit = {'unit_type': 'page', 'unit_number': number, 'text': text, 'extraction_kind': 'pdf_text'}
        units.append(unit)
        if text.strip():
            continue
        unit['extraction_kind'] = 'pdf_ocr'
        if not renderer:
            unit['error'] = 'document_ocr_unavailable'
            continue
        prefix = directory / f'page-{number}'
        rendered = run_local([renderer, '-f', str(number), '-l', str(number), '-singlefile',
            '-scale-to', str(OCR_IMAGE_LIMIT), '-png', str(source), str(prefix)], timeout=12)
        if rendered.returncode or not prefix.with_suffix('.png').is_file():
            unit['error'] = 'document_render_failed'
            continue
        images.append(prefix.with_suffix('.png'))
        pending.append(number - 1)
    for index, result in zip(pending, local_ocr(images, directory)):
        units[index].update(text=result.get('text', ''), ocr_language=result.get('language'), error=result.get('error'))
    return units


def extract_direct(source):
    source = Path(source).resolve()
    if not source.is_file() or source.stat().st_size > MAX_DOCUMENT_BYTES:
        raise DocumentError('document_size_budget')
    content = source.read_bytes()
    with tempfile.TemporaryDirectory(prefix='offerpilot-document-') as folder:
        directory = Path(folder)
        if source.suffix.lower() == '.pdf':
            units = pdf_units(content, directory, source)
        elif source.suffix.lower() == '.pptx':
            units = pptx_units(content, directory)
        else:
            raise DocumentError('document_unsupported')
    total = 0
    for unit in units:
        unit['text'] = unit['text'].replace('\x00', '').strip()
        total += len(unit['text'])
        if total > MAX_TEXT:
            raise DocumentError('document_text_budget')
        unit['text_sha256'] = hashlib.sha256(unit['text'].encode('utf-8')).hexdigest()
        unit['needs_review'] = unit['extraction_kind'].endswith('_ocr')
    return {'extractor_version': EXTRACTOR_VERSION, 'sha256': hashlib.sha256(content).hexdigest(),
            'units': units, 'unit_count': len(units),
            'units_without_text': [u['unit_number'] for u in units if not u['text']]}


def extract_document(source):
    """Isolate parsers and OCR from the HTTP process, with a fixed timeout."""
    try:
        result = run_local([sys.executable, '-I', '-B', str(Path(__file__).resolve()), str(Path(source).resolve())],
                           timeout=WORKER_TIMEOUT)
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise DocumentError('document_worker_failed')
        value = json.loads(result.stdout.decode('utf-8'))
        if 'error' in value:
            raise DocumentError(value['error'])
        return value
    except subprocess.TimeoutExpired:
        raise DocumentError('document_timeout') from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DocumentError('document_worker_failed') from None


if __name__ == '__main__':
    try:
        value = extract_direct(sys.argv[1])
    except DocumentError as error:
        value = {'error': error.code}
    except ImportError:
        value = {'error': 'document_dependency_missing'}
    except Exception:
        value = {'error': 'document_invalid'}
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False).encode('utf-8'))
