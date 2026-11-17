"""Shared resume structure for print and PDF. Content remains immutable."""

from html import escape
import re
from urllib.parse import urlsplit

TEMPLATES = {"professional": "专业墨蓝", "classic": "经典黑白"}
WEB_LINK = re.compile(r'https?://[^\s<>"\'|，。；、（）【】]+')


def template_name(value="professional"):
    if value not in TEMPLATES:
        raise ValueError("请选择专业墨蓝或经典黑白模板")
    return value


def blocks(markdown):
    result, section = [], False
    for line in markdown.splitlines():
        text = re.sub(r"`([^`]+)`", r"\1", line).strip()
        if not text:
            continue
        heading = re.match(r"^(#{1,3}) (.*)$", text)
        if heading:
            level = len(heading.group(1))
            result.append({"kind": f"h{level}", "text": heading.group(2)})
            section = section or level == 2
        elif text.startswith("- "):
            result.append({"kind": "bullet", "text": text[2:]})
        else:
            kind = "contact" if not section else "meta" if result and result[-1]["kind"] == "h3" and re.match(r"^(?:19|20)\d{2}|^至今", text) else "link" if text.startswith(("作品集：", "项目链接：")) else "body"
            result.append({"kind": kind, "text": text})
    return result


def inline_text(text, *, pdf=False):
    parts, end = [], 0
    for match in WEB_LINK.finditer(text):
        url = match.group().rstrip('.,;:!?)]}')
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid:
            continue
        parts.append(escape(text[end:match.start()]))
        escaped = escape(url, quote=True)
        parts.append(f'<link href="{escaped}"><u>{escaped}</u></link>' if pdf else
                     f'<a href="{escaped}" target="_blank" rel="noopener noreferrer">{escaped}</a>')
        end = match.start() + len(url)
    parts.append(escape(text[end:]))
    return ''.join(parts)


def emphasized(text, *, pdf=False):
    """Bold only a short contribution label, with all user markup escaped."""
    label = re.match(r"^([^：:]{1,24}[：:])(.*)$", text)
    return f"<b>{escape(label[1])}</b>{inline_text(label[2], pdf=pdf)}" if label else inline_text(text, pdf=pdf)


def print_html(markdown, role="", template="professional"):
    template_name(template)
    content = []
    for item in blocks(markdown):
        kind, text = item["kind"], escape(item["text"])
        if kind in {"h1", "h2", "h3"}:
            content.append(f'<{kind} class="resume-{kind}">{text}</{kind}>')
            if kind == "h1" and role:
                content.append(f'<p class="resume-role">求职意向 · {escape(role)}</p>')
        elif kind == "bullet":
            content.append(f'<p class="resume-bullet"><span class="resume-dot" aria-hidden="true">•</span><span>{emphasized(item["text"])}</span></p>')
        else:
            content.append(f'<p class="resume-{kind}">{inline_text(item["text"])}</p>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>简历预览</title><link rel="stylesheet" href="/career-resume.css"></head><body class="resume-print">'
            f'<aside class="resume-print-note">{TEMPLATES[template]} · A4 单栏<span>Ctrl+P 打印 / 保存 PDF</span></aside>'
            f'<article class="resume-sheet" data-resume-template="{template}" aria-label="简历正文">'
            + ''.join(content) + '</article></body></html>').encode('utf-8')
