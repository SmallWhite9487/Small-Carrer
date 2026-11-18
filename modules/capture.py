"""Local one-click capture from the user's own browser.

Some sites (LinkedIn among them) require a signed-in session and forbid
automated reading. Instead of driving a logged-in session, the app exposes a
tiny loopback HTTP endpoint and a bookmarklet: the user browses normally in
their own browser, clicks the bookmark on a job page they are already looking
at, and the page text lands in ``pending_jobs`` for AI evaluation.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit

from .core import EvaluationError, open_database, save_pending


MAX_BODY = 400_000
MAX_TEXT = 20_000
MAX_TITLE = 300
MAX_FIELD = 200
ALLOWED_ORIGIN = "*"

BOOKMARKLET = r"""(function(){
function pick(sel){var n=document.querySelector(sel);return n?(n.innerText||n.textContent||'').trim():'';}
var title='',company='',place='';
var lds=document.querySelectorAll('script[type="application/ld+json"]');
for(var i=0;i<lds.length;i++){
 try{
  var d=JSON.parse(lds[i].textContent);var items=Array.isArray(d)?d:[d];
  for(var j=0;j<items.length;j++){
   var o=items[j];if(!o||!o['@type'])continue;
   var ty=Array.isArray(o['@type'])?o['@type']:[o['@type']];
   if(ty.indexOf('JobPosting')<0)continue;
   if(o.title)title=o.title;
   if(o.hiringOrganization&&o.hiringOrganization.name)company=o.hiringOrganization.name;
   var a=o.jobLocation;if(Array.isArray(a))a=a[0];
   if(a&&a.address)place=[a.address.addressLocality,a.address.addressRegion].filter(Boolean).join(', ');
  }
 }catch(e){}
}
if(!title)title=pick('h1')||document.title;
if(!company)company=pick('[class*="company"]');
if(!place)place=pick('[class*="location"]');
var payload={url:location.href,title:title,company:company,location:place,
 text:(document.body.innerText||'').slice(0,__MAX_TEXT__)};
var target='http://127.0.0.1:__PORT__/job?token=__TOKEN__';
function fallback(){
 var raw=JSON.stringify(payload);
 function notice(){alert('已複製。回到 Small Career 按「從剪貼簿加入」。');}
 if(navigator.clipboard&&navigator.clipboard.writeText){
  navigator.clipboard.writeText(raw).then(notice,function(){prompt('請複製以下內容：',raw);});
 }else{prompt('請複製以下內容：',raw);}
}
fetch(target,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
 .then(function(r){return r.json();})
 .then(function(d){
  if(d&&d.ok){alert('已加入佇列：'+(d.title||title));}else{fallback();}
 })
 .catch(fallback);
})();"""


def bookmarklet(port: int, token: str) -> str:
    from urllib.parse import quote

    script = (BOOKMARKLET.replace("__PORT__", str(port))
              .replace("__TOKEN__", token)
              .replace("__MAX_TEXT__", str(MAX_TEXT))
              .replace("\n", ""))
    return "javascript:" + quote(script, safe="")


def job_markdown(payload: dict[str, object]) -> tuple[str, str]:
    url = payload.get("url")
    if not isinstance(url, str):
        raise EvaluationError("error.capture")
    url = url.strip()
    parts = urlsplit(url)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or len(url) > 2048):
        raise EvaluationError("error.capture")
    title_value = payload.get("title")
    text_value = payload.get("text")
    if not isinstance(title_value, str) or not isinstance(text_value, str):
        raise EvaluationError("error.capture")
    title = " ".join(title_value.split())[:MAX_TITLE]
    company = " ".join(str(payload.get("company") or "").split())[:MAX_FIELD] if isinstance(
        payload.get("company"), str) else ""
    location = " ".join(str(payload.get("location") or "").split())[:MAX_FIELD] if isinstance(
        payload.get("location"), str) else ""
    body = "\n".join(line.strip() for line in text_value.splitlines()
                     if line.strip())[:MAX_TEXT]
    if not title or not body:
        raise EvaluationError("error.capture")
    lines = [title, ""]
    if company:
        lines.append(f"Company: {company}")
    if location:
        lines.append(f"Location: {location}")
    lines.extend(["", body])
    return url, "\n".join(lines) + "\n"


class CaptureServer:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.token = secrets.token_urlsafe(18)
        self.added = 0
        self.notices: list[str] = []
        self._lock = threading.Lock()
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SmallCareerCapture"

            def log_message(self, format: str, *args: object) -> None:
                return

            def _reply(self, code: int, value: object) -> None:
                body = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:
                if urlsplit(self.path).path == "/ping":
                    self._reply(200, {"ok": True})
                else:
                    self._reply(404, {"ok": False})

            def do_POST(self) -> None:
                if urlsplit(self.path).path != "/job":
                    self._reply(404, {"ok": False})
                    return
                if not app.authorized(self.path):
                    self._reply(403, {"ok": False})
                    return
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    self._reply(400, {"ok": False})
                    return
                if length <= 0 or length > MAX_BODY:
                    self._reply(413, {"ok": False})
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._reply(400, {"ok": False})
                    return
                if not isinstance(payload, dict):
                    self._reply(400, {"ok": False})
                    return
                try:
                    url, content = job_markdown(payload)
                    added = app.store(url, content)
                except EvaluationError:
                    self._reply(400, {"ok": False})
                    return
                except (OSError, sqlite3.Error):
                    self._reply(500, {"ok": False})
                    return
                self._reply(200, {"ok": True, "added": added,
                                  "title": str(payload.get("title") or "")[:MAX_TITLE]})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def authorized(self, path: str) -> bool:
        from urllib.parse import parse_qs

        query = parse_qs(urlsplit(path).query)
        return secrets.compare_digest(query.get("token", [""])[0], self.token)

    def store(self, url: str, content: str) -> bool:
        connection = open_database(self.directory / "jobs.sqlite3")
        try:
            added = save_pending(connection, url, content)
        finally:
            connection.close()
        with self._lock:
            self.added += 1 if added else 0
            if added:
                self.notices.append(url)
        return added

    def start(self) -> None:
        self.thread.start()

    def drain(self) -> int:
        with self._lock:
            count = len(self.notices)
            self.notices.clear()
        return count

    def close(self) -> None:
        try:
            self.httpd.shutdown()
        except (OSError, RuntimeError):
            pass
        finally:
            self.httpd.server_close()

    def snippet(self) -> str:
        return bookmarklet(self.port, self.token)


def import_text(server: CaptureServer, text: str) -> tuple[bool, str, str]:
    """Queue a clipboard payload produced by the bookmarklet fallback."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False, "", "error.capture"
    if not isinstance(payload, dict):
        return False, "", "error.capture"
    try:
        url, content = job_markdown(payload)
    except EvaluationError:
        return False, "", "error.capture"
    try:
        added = server.store(url, content)
    except (OSError, sqlite3.Error):
        return False, "", "error.capture"
    title = str(payload.get("title") or "").strip()[:MAX_TITLE]
    return True, title, ("captured_added" if added else "captured_duplicate")
