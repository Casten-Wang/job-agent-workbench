"""Anonymous, single-note collector. No search, account cookies or signatures."""

import html
import http.cookiejar
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
HOSTS = {"xhslink.com", "www.xhslink.com", "xiaohongshu.com", "www.xiaohongshu.com",
         "rednote.com", "www.rednote.com"}
NOTE_ID = re.compile(r"/(?:explore|discovery/item)/([a-fA-F0-9]{24})(?:/|$)")
MAX_HTML = 4 * 1024 * 1024


class NoteFailure(ValueError):
    def __init__(self, reason):
        self.reason = reason


def checked_url(url):
    if not isinstance(url, str) or len(url) > 4096 or any(c.isspace() for c in url):
        raise NoteFailure("invalid_url")
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.port not in (None, 443)
                or parsed.username or parsed.password or "\\" in url):
            raise NoteFailure("invalid_url")
    except ValueError:
        raise NoteFailure("invalid_url") from None
    return parsed


def result(reason, **data):
    return {"ok": reason == "success", "reason": reason, "title": "", "author": "", "content": "", "images": [], **data}


def state_object(page):
    marker = re.search(r"window\.__INITIAL_STATE__\s*=\s*", page)
    if not marker or marker.end() >= len(page) or page[marker.end()] != "{":
        raise NoteFailure("parse_error")
    start, depth, quoted, escaped = marker.end(), 0, False, False
    for pos in range(start, len(page)):
        char = page[pos]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                raw = page[start:pos + 1]
                # Match string literals first: never rewrite the user's prose.
                tokens = r'"(?:\\.|[^"\\])*"|\b(?:undefined|NaN)\b|new\s+(?:Map|Set)\(\s*\[\s*\]\s*\)'
                def normalize(match):
                    value = match.group()
                    if value.startswith('"'):
                        return value
                    return "{}" if "Map" in value else "[]" if "Set" in value else "null"
                return json.loads(re.sub(tokens, normalize, raw))
    raise NoteFailure("parse_error")


def parse_note(page, note_id):
    try:
        state = state_object(page)
        note = state.get("noteData", {}).get("data", {}).get("noteData")
        # Current desktop pages can carry a noteDetailMap instead of noteData.
        if not isinstance(note, dict):
            details = state.get("note", {}).get("noteDetailMap", {})
            note = details.get(note_id, {}).get("note") if isinstance(details, dict) else None
        if not isinstance(note, dict):
            raise NoteFailure("parse_error")
        if note.get("noteId") != note_id:
            raise NoteFailure("id_mismatch")
        desc = note.get("desc", "")
        if not isinstance(desc, str) or not desc.strip():
            raise NoteFailure("empty_content")
        content = re.sub(r"[^\S\n]+", " ", html.unescape(desc).replace("\r\n", "\n").replace("\r", "\n"))
        content = "\n".join(line.strip() for line in content.split("\n")).strip()
        tags = []
        for tag in note.get("tagList") or []:
            name = tag.get("name") if isinstance(tag, dict) else None
            if isinstance(name, str) and name.strip() and "#" + name.strip() not in content:
                tags.append("#" + name.strip())
        if tags:
            content += "\n" + " ".join(dict.fromkeys(tags))
        images = []
        for item in note.get("imageList") or []:
            if not isinstance(item, dict):
                continue
            choices = [item.get("urlDefault"), item.get("urlPre")]
            choices += [x.get("url") for x in item.get("infoList", []) if isinstance(x, dict)]
            address = next((u for u in choices if isinstance(u, str) and u.startswith(("https://", "http://"))), None)
            if address and address not in images:
                images.append(address)
        if note.get("type") == "video":
            images = images[:1]
        title, author = note.get("title", ""), (note.get("user") or {}).get("nickName", "")
        if not isinstance(title, str) or not isinstance(author, str):
            raise NoteFailure("parse_error")
        return result("success", title=html.unescape(title), author=html.unescape(author), content=content, images=images)
    except NoteFailure as error:
        return result(error.reason)
    except (ValueError, TypeError, AttributeError, RecursionError):
        return result("parse_error")


def login_page(url, page=""):
    path = urllib.parse.urlsplit(url).path.lower()
    return (any(word in path for word in ("/login", "/captcha", "/security", "/website-login"))
            or bool(re.search(r"<title[^>]*>[^<]*(?:登录|验证|captcha)", page, re.I))
            or any(word in page for word in ("请完成安全验证", "访问频次异常", "登录后查看", "请先登录")))


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, gate):
        self.gate = gate

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        if login_page(newurl):
            raise NoteFailure("need_login")
        self.gate()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_gate_lock = threading.Lock()
_next_request = 0.0


def local_gate():
    global _next_request
    with _gate_lock:
        time.sleep(max(0, _next_request - time.monotonic()))
        _next_request = time.monotonic() + 4


class NoteCollector:
    def __init__(self, gate=local_gate):
        self.gate = gate

    def fetch(self, url):
        """Only an explicit single URL; anonymous cookies live for this call only."""
        try:
            parsed = checked_url(url)
            deadline, requests = time.monotonic() + 90, 0
            def gate():
                nonlocal requests
                requests += 1
                if requests > 6 or time.monotonic() >= deadline:
                    raise NoteFailure("unreachable")
                self.gate()
                if time.monotonic() >= deadline:
                    raise NoteFailure("unreachable")
            opener = urllib.request.build_opener(SafeRedirect(gate),
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

            def read(address):
                checked_url(address)
                gate()
                request = urllib.request.Request(address, headers={"User-Agent": UA, "Accept": "text/html"})
                with opener.open(request, timeout=12) as response:
                    final = response.geturl()
                    checked_url(final)
                    chunks, size = [], 0
                    # read1 returns after one buffered/socket read, allowing a deadline check.
                    reader = getattr(response, "read1", response.read)
                    while size <= MAX_HTML:
                        if time.monotonic() >= deadline:
                            raise NoteFailure("unreachable")
                        chunk = reader(min(65536, MAX_HTML + 1 - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                    raw = b"".join(chunks)
                    if len(raw) > MAX_HTML:
                        raise NoteFailure("parse_error")
                    page = raw.decode("utf-8", errors="replace")
                    if login_page(final, page):
                        raise NoteFailure("need_login")
                    return final, page

            final = url
            if parsed.hostname in {"xhslink.com", "www.xhslink.com"}:
                final, _ = read(url)
            if login_page(final):
                raise NoteFailure("need_login")
            parsed = checked_url(final)
            matched = NOTE_ID.search(parsed.path)
            if not matched:
                return result("no_post_id")
            note_id = matched.group(1)
            read("https://www.xiaohongshu.com/")
            address = "https://www.xiaohongshu.com/explore/" + note_id
            if parsed.query:
                address += "?" + parsed.query
            _, page = read(address)
            return parse_note(page, note_id)
        except NoteFailure as error:
            return result(error.reason)
        except urllib.error.HTTPError as error:
            return result("need_login" if error.code in (401, 403) else "rate_limited" if error.code == 429
                          else "not_found" if error.code in (404, 410) else "unreachable")
        except (OSError, urllib.error.URLError, TimeoutError):
            return result("unreachable")


def collect_note(url):
    return NoteCollector().fetch(url)
