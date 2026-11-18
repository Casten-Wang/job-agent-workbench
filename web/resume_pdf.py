"""Local PDF rendering of the already saved resume, with embedded Chinese text."""

from html import escape
from io import BytesIO
import os
from pathlib import Path
from resume_layout import blocks, emphasized, inline_text, template_name


def cjk_font_candidates(classic):
    """(正文字体候选, 粗体候选)：Windows 优先，其次 macOS 与常见 Linux 中文字体；reportlab 只能嵌入 TrueType 轮廓。"""
    windows = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    mac = Path('/System/Library/Fonts')
    linux = [Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'), Path('/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf')]
    if classic:
        regular = [windows / 'simsun.ttc', mac / 'Supplemental/Songti.ttc', *linux]
        heavy = [windows / 'simhei.ttf', windows / 'simsun.ttc', mac / 'STHeiti Medium.ttc', *linux]
    else:
        regular = [windows / 'msyh.ttc', windows / 'simsun.ttc', mac / 'STHeiti Light.ttc', mac / 'STHeiti Medium.ttc', *linux]
        heavy = [windows / 'msyhbd.ttc', windows / 'simsun.ttc', mac / 'STHeiti Medium.ttc', *linux]
    return regular, heavy


def render_pdf(markdown, *, role='', template='professional'):
    template_name(template)
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate

    classic = template == 'classic'
    font, bold = ('OfferPilotSong', 'OfferPilotHei') if classic else ('OfferPilotSans', 'OfferPilotSansBold')
    for name, candidates in zip((font, bold), cjk_font_candidates(classic)):
        path = next((item for item in candidates if item.is_file()), None)
        if path is None:
            raise ValueError('直接导出 PDF 需要本机中文字体；可改用打印页保存 PDF。')
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
    pdfmetrics.registerFontFamily(font, normal=font, bold=bold, italic=font, boldItalic=bold)
    ink, accent, muted, rule = map(HexColor, ('#18212b', '#222222' if classic else '#234e70', '#596675', '#cbd3dc'))
    body = ParagraphStyle('body', fontName=font, fontSize=10.2, leading=16.3, textColor=ink,
                          spaceAfter=5, wordWrap='CJK', allowWidows=0, allowOrphans=0)
    styles = {
        'h1': ParagraphStyle('name', parent=body, fontName=bold, fontSize=24, leading=31, spaceAfter=3, keepWithNext=True, alignment=1 if classic else 0),
        'h2': ParagraphStyle('section', parent=body, fontName=bold, fontSize=11.2, leading=17, textColor=accent, spaceBefore=13, spaceAfter=3, keepWithNext=True),
        'h3': ParagraphStyle('entry', parent=body, fontName=bold, fontSize=10.7, leading=17, spaceBefore=8, spaceAfter=3, keepWithNext=True),
        'role': ParagraphStyle('role', parent=body, fontName=bold, fontSize=10, leading=16, textColor=accent, spaceAfter=4, keepWithNext=True, alignment=1 if classic else 0),
        'contact': ParagraphStyle('contact', parent=body, fontSize=9, leading=14, textColor=muted, spaceAfter=4, keepWithNext=True, alignment=1 if classic else 0),
        'meta': ParagraphStyle('meta', parent=body, fontSize=9, leading=14, textColor=muted, spaceAfter=5, keepWithNext=True),
        'link': ParagraphStyle('link', parent=body, fontSize=9, leading=14, textColor=accent, spaceAfter=5),
        'bullet': ParagraphStyle('bullet', parent=body, leftIndent=10, firstLineIndent=-9, spaceAfter=6),
    }
    content = []
    if not classic:
        rule_top = HRFlowable(width='100%', thickness=2, color=accent, spaceAfter=12)
        rule_top.keepWithNext = True
        content.append(rule_top)
    for item in blocks(markdown):
        kind = item['kind']
        text = ('• ' + emphasized(item['text'], pdf=True) if kind == 'bullet' else
                escape(item['text']) if kind in {'h1', 'h2', 'h3'} else inline_text(item['text'], pdf=True))
        content.append(Paragraph(text, styles.get(kind, body)))
        if kind == 'h1' and role:
            content.append(Paragraph('求职意向 · ' + escape(role), styles['role']))
        if kind == 'h2':
            line = HRFlowable(width='100%', thickness=.5, color=rule, spaceAfter=6)
            line.keepWithNext = True
            content.append(line)
    def page_footer(canvas, document):
        canvas.saveState()
        canvas.setFillColor(muted)
        canvas.setFont(font, 8)
        canvas.drawCentredString(A4[0] / 2, 9 * mm, str(document.page))
        canvas.restoreState()
    output = BytesIO()
    SimpleDocTemplate(output, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=14 * mm, bottomMargin=16 * mm, title='Resume').build(
                          content, onFirstPage=page_footer, onLaterPages=page_footer)
    return output.getvalue()
