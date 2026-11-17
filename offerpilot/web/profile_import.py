"""Extract local resume text without uploading it or saving the source file."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 60_000
SUFFIXES = {".md", ".txt", ".docx", ".pdf"}


def extract_resume_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError("请选择 PDF、DOCX、Markdown 或 TXT 简历文件")
    if not content:
        raise ValueError("简历文件为空，请重新选择")
    if len(content) > MAX_BYTES:
        raise ValueError("简历文件不能超过 5 MB")
    if suffix == ".pdf":
        text = _pdf_text(content)
    elif suffix == ".docx":
        text = _docx_text(content)
    else:
        text = _plain_text(content)
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("未读取到简历文字；扫描图片 PDF 请先转为可复制文字的文件")
    if len(text) > MAX_TEXT:
        raise ValueError("简历文字过长，请精简至 60000 字符以内")
    return text


def _plain_text(content: bytes) -> str:
    encodings = ("utf-16",) if content.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text or any(ord(char) < 32 and char not in "\r\n\t" for char in text):
            break
        return text
    raise ValueError("无法读取文本编码，请将简历另存为 UTF-8 的 TXT 或 Markdown")


def _docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            entry = document.getinfo("word/document.xml")
            if entry.file_size > 8 * 1024 * 1024:
                raise ValueError("DOCX 正文过大，请精简简历后重试")
            xml = document.read(entry)
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("DOCX 格式不受支持，请重新另存为 DOCX")
        root = ElementTree.fromstring(xml)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        return "\n".join(
            "".join(
                node.text or "" if node.tag == ns + "t" else "\t" if node.tag == ns + "tab" else "\n"
                for node in paragraph.iter()
                if node.tag in {ns + "t", ns + "tab", ns + "br"}
            )
            for paragraph in root.iter(ns + "p")
        )
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError("DOCX 文件损坏或已加密，请重新另存为 DOCX 后导入") from exc


def _pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("本机缺少 PDF 解析依赖 pypdf，请安装 requirements-offerpilot.txt 中的依赖") from exc
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF，请先移除密码后导入")
        if len(reader.pages) > 30:
            raise ValueError("简历 PDF 不能超过 30 页，请精简后导入")
        parts = []
        total = 0
        for page in reader.pages:
            part = page.extract_text() or ""
            total += len(part)
            if total > MAX_TEXT:
                raise ValueError("简历文字过长，请精简至 60000 字符以内")
            parts.append(part)
        return "\n".join(parts)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("无法解析 PDF，请重新导出为含文字层的 PDF 后导入") from exc
