"""Local-only QR display for the single-note validation run."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlsplit

OUTPUT = Path(__file__).resolve().parent / "output"
URL = "http://127.0.0.1:18743"
refresh_requested = threading.Event()

PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>小红书扫码验证</title>
<style>
body{font:18px system-ui,sans-serif;margin:32px;background:#f5f5f5;color:#202020}
main{max-width:600px;margin:auto;background:white;padding:28px;border-radius:12px}
button{font:inherit;padding:12px 20px;cursor:pointer} img{display:block;width:100%;
max-width:376px;height:auto;image-rendering:pixelated;padding:28px;background:white;
box-sizing:border-box}[hidden]{display:none}
#status{min-height:2em}small{color:#666}
</style><main><h1>小红书扫码验证</h1>
<p>准备好小红书 App 后，点击刷新，再扫码并在手机确认登录。</p>
<button id="refresh">刷新二维码</button><p id="status">正在连接验证程序…</p>
<img id="qr" alt="等待生成登录二维码" hidden>
<small>请保留此页面。此次只验证一篇图文面经，不采集评论。</small></main>
<script>
const statusText=document.querySelector('#status'), qr=document.querySelector('#qr');
const button=document.querySelector('#refresh'); let revision='';
const labels={starting:'正在打开登录页面…',refreshing_login_qr:'正在生成新二维码…',
waiting_for_user_login:'请使用小红书 App 扫码；过期时点击上方刷新按钮。',
browser_login_confirmed:'网页已完成登录，正在检查接口会话…',
checking_api_login:'正在确认接口是否认可登录会话…',
authenticated_searching:'已确认登录，正在搜索面经…',fetching_one_note:'正在读取一篇面经…',
downloading_images:'正在下载图片…',note_and_images_verified:'正文和图片验证通过。',
not_completed:'验证尚未完成，请回到聊天查看原因。'};
async function update(){
 try{
  const r=await fetch('/status',{cache:'no-store'}), s=await r.json();
  statusText.textContent=labels[s.stage]||s.stage;
  button.disabled=s.stage!=='waiting_for_user_login';
  qr.hidden=s.stage!=='waiting_for_user_login';
  if(!qr.hidden && s.qr_path!==revision){revision=s.qr_path; qr.src='/qr?v='+Date.now();}
 }catch{statusText.textContent='验证程序已断开，请回到聊天让我重新启动。';
 button.disabled=true; qr.hidden=true;}
}
button.onclick=async()=>{button.disabled=true; qr.hidden=true;
 statusText.textContent='正在生成新二维码…';
 try{await fetch('/refresh',{method:'POST'});}catch{await update();}
};
update();setInterval(update,1500);
</script></html>"""


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/":
            self.reply(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif route == "/status":
            self.reply(200, "application/json", (OUTPUT / "status.json").read_bytes())
        elif route == "/qr" and (OUTPUT / "login-qr.png").exists():
            self.reply(200, "image/png", (OUTPUT / "login-qr.png").read_bytes())
        else:
            self.reply(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path != "/refresh" or self.headers.get("Origin", URL) != URL:
            self.reply(403, "text/plain", b"Not allowed")
            return
        refresh_requested.set()
        self.reply(202, "text/plain", b"Refresh requested")

    def log_message(self, *args):
        pass


def start():
    server = ThreadingHTTPServer(("127.0.0.1", 18743), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
