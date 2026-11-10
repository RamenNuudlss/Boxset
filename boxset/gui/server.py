"""Local server between the interface and the engine.

Bound to 127.0.0.1 only, and every API, file and event request must carry a
random per-launch token, so other programs and web pages on the machine
can't drive the app or read files through it.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("text/javascript", ".js")

PUBLIC_METHODS = {
    "state", "manifest", "recent", "new_project", "open_project", "save_project_as", "pick_files", "pick_folder",
    "add_paths", "cancel_render", "clear_menus", "remove_theme", "refresh_burners", "set_burner", "update_film", "move_film", "remove_film", "set", "set_option", "pick_option_file",
    "install_theme", "trust_project_themes", "render_menus", "build", "make_iso", "cancel", "open_folder", "burn",
}


def _byte_range(header: str, size: int):
    """(start, end) for a Range header on a file of `size` bytes. None if the header
    isn't a single byte range we understand; False if it lies outside the file."""
    if not header.startswith("bytes=") or "," in header:
        return None
    a, sep, b = header[6:].strip().partition("-")
    a, b = a.strip(), b.strip()
    if not sep or not (a or b) or not (a.isdigit() or not a) or not (b.isdigit() or not b):
        return None
    if not a:                                   # "-500": the last 500 bytes
        if int(b) == 0 or size == 0:
            return False
        return max(0, size - int(b)), size - 1
    start = int(a)
    end = min(int(b), size - 1) if b else size - 1
    if start >= size or end < start:
        return False
    return start, end


def make_server(api, port: int = 0):
    token = secrets.token_urlsafe(24)

    def file_url(path):
        if not path:
            return None
        v = int(os.path.getmtime(path)) if os.path.exists(path) else 0
        return f"/file?p={urllib.parse.quote(os.path.abspath(path))}&v={v}&t={token}"

    api.file_url = file_url

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _authed(self, qs):
            return secrets.compare_digest(self.headers.get("X-Boxset-Token", "") or qs.get("t", [""])[0], token)

        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                return self._static("index.html")
            if u.path.startswith("/static/"):
                return self._static(u.path[len("/static/"):])
            if u.path == "/file":
                if not self._authed(qs):
                    return self._send(403, b"{}")
                return self._file(qs.get("p", [""])[0])
            if u.path == "/events":
                if not self._authed(qs):
                    return self._send(403, b"{}")
                return self._events()
            self._send(404, b"{}")

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if not u.path.startswith("/api/"):
                return self._send(404, b"{}")
            if not self._authed({}):
                return self._send(403, json.dumps({"ok": False, "error": "Not allowed"}).encode())
            name = u.path[5:]
            if name not in PUBLIC_METHODS:
                return self._send(404, json.dumps({"ok": False, "error": f"No method {name}"}).encode())
            n = int(self.headers.get("Content-Length") or 0)
            try:
                args = json.loads(self.rfile.read(n) or b"{}").get("args", [])
                result = getattr(api, name)(*args)
                body = {"ok": True, "result": result}
            except Exception as e:  # errors go back to the interface as messages
                body = {"ok": False, "error": str(e) or e.__class__.__name__}
            self._send(200, json.dumps(body, default=str).encode())

        def _static(self, rel):
            path = os.path.abspath(os.path.join(WEB_DIR, rel))
            if not path.startswith(WEB_DIR + os.sep) or not os.path.isfile(path):
                return self._send(404, b"{}")
            with open(path, "rb") as fh:
                data = fh.read()
            self._send(200, data, mimetypes.guess_type(path)[0] or "application/octet-stream")

        def _file(self, p):
            path = os.path.abspath(p)
            # compare the way the file system does (Windows ignores case in paths)
            where = os.path.normcase(path)
            roots = [os.path.normcase(r) for r in api.allowed_roots()]
            if not any(where.startswith(r + os.sep) for r in roots) or not os.path.isfile(path):
                return self._send(404, b"{}")
            size = os.path.getsize(path)
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            if rng:
                span = _byte_range(rng, size)
                if span is None:          # a range we can't make sense of: send the whole file
                    rng = None
                elif span is False:       # a range past the end of the file
                    return self._send(416, b"{}", extra={"Content-Range": f"bytes */{size}"})
                else:
                    start, end = span
            length = end - start + 1
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            with open(path, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = api.subscribe()
            try:
                self.wfile.write(b": hello\n\n")
                self.wfile.flush()
                while True:
                    try:
                        e = q.get(timeout=15)
                        data = json.dumps(e, default=str)
                        self.wfile.write(f"data: {data}\n\n".encode())
                    except Exception:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                api.unsubscribe(q)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1], token
