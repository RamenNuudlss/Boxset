"""Start the Boxset app: a desktop window (Edge WebView2 via pywebview), or a
browser tab with --browser (also the fallback when WebView2 isn't available)."""
from __future__ import annotations

import sys
import threading
import time
import webbrowser

from .api import Api
from .server import make_server


def main(project_path: str | None = None, browser: bool = False, port: int = 0):
    from .. import winfix
    winfix.apply()
    api = Api()
    installed = None
    if project_path and project_path.lower().endswith((".boxtheme", ".zip")):
        # double-clicked theme pack: install it, then open the app as usual
        from .. import core
        try:
            installed = core.install_theme(project_path)
        except Exception as e:  # shown once the window is up
            installed = e
        project_path = None
    api.load_initial(project_path)
    if installed is not None:
        msg = f"Installed the theme '{installed}'" if isinstance(installed, str) else f"Couldn't install that theme: {installed}"
        threading.Timer(2.5, lambda: api.push({"type": "toast", "level": "info" if isinstance(installed, str) else "error",
                                               "message": msg})).start()
    httpd, port, token = make_server(api, port)
    url = f"http://127.0.0.1:{port}/?t={token}"

    if not browser:
        try:
            import webview
        except ImportError:
            browser = True
    if browser:
        print(f"Boxset is running at {url}\nClose this window to quit.", flush=True)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    window = webview.create_window("Boxset", url, width=1380, height=880, min_size=(1120, 720),
                                   background_color="#1C1D21", text_select=False)
    api.window = window

    def on_loaded():
        # dropped files from Explorer arrive here with their full paths
        try:
            from webview.dom import DOMEventHandler

            def on_drop(e):
                files = (e.get("dataTransfer") or {}).get("files") or []
                paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
                if paths:
                    try:
                        api.add_paths(paths)
                    except RuntimeError as err:
                        api.push({"type": "toast", "level": "error", "message": str(err)})

            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
            window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        except Exception:
            pass

    window.events.loaded += on_loaded

    def on_closing():
        if api.status.get("running"):
            if api.job:
                api.job.cancel()
        return True

    window.events.closing += on_closing
    webview.start(gui="edgechromium" if sys.platform == "win32" else None, private_mode=False)
    httpd.shutdown()
    return 0
