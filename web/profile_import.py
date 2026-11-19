"""Extract local resume text without uploading it or saving the source file."""

from __future__ import annotations

import io
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 60_000
SUFFIXES = {".md", ".txt", ".docx", ".pdf"}


class TextLayerUnusable(ValueError):
    """PDF 没有可用文字层（乱码或纯图片）；调用方可改走图片识别。消息可直接展示。"""


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
    text = _fold_cjk_radicals(text.replace("\x00", "")).strip()
    if not text:
        if suffix == ".pdf":
            raise TextLayerUnusable("这份 PDF 里没有可读取的文字（可能是扫描图片）。")
        raise ValueError("未读取到简历文字；请确认文件内容不是空白")
    if looks_garbled(text):
        raise (TextLayerUnusable if suffix == ".pdf" else ValueError)(GARBLED_MESSAGE)
    if len(text) > MAX_TEXT:
        raise ValueError("简历文字过长，请精简至 60000 字符以内")
    return text


def _fold_cjk_radicals(text: str) -> str:
    """PDF 常把「生」抽成康熙部首「⽣」（U+2F63）；折回通用汉字，否则搜索与核对都会对不上。"""
    return "".join(
        unicodedata.normalize("NFKC", char) if 0x2E80 <= ord(char) <= 0x2FDF else char for char in text
    )


GARBLED_MESSAGE = (
    "这份文件的文字层是乱码（常见于字体没有标准编码的 PDF 导出），读出来的不是真实文字，"
    "继续解析只会得到错误字段。请在原软件里用「打印 → 存储为 PDF」重新导出，或改传 DOCX / Markdown / TXT。"
)


def _plausible(char: str) -> bool:
    code = ord(char)
    return (
        char.isascii()
        or 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0xF900 <= code <= 0xFAFF  # 汉字
        or 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF  # 中日文标点、全角
        or 0x00A0 <= code <= 0x024F  # 拉丁扩展（带重音字母）
        or 0x2000 <= code <= 0x206F or 0x2190 <= code <= 0x27BF  # 通用标点、箭头、符号
    )


def looks_garbled(text: str, threshold: float = 0.2, minimum: int = 30) -> bool:
    """字体缺少 ToUnicode 映射的 PDF 会抽出大量私有/异文字符；这类文本不能交给模型猜。"""
    chars = [char for char in text if not char.isspace()]
    if len(chars) < minimum:
        return False
    return sum(not _plausible(char) for char in chars) / len(chars) > threshold


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
