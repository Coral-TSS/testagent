"""Tiny web app for browser/pytest executor tests. `/` is correct; `/bug/` accepts amount 0."""

from __future__ import annotations

import threading
from functools import cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html><html lang="en">
<head><meta charset="utf-8"><title>Mini shop</title></head>
<body><h1>New purchase order</h1>
<label for="amount">Amount</label><input id="amount" type="number">
<button id="submit">Submit</button>
<div id="msg" role="status"></div>
<script>
const BUG = %s;
document.getElementById('submit').onclick = () => {
  const v = Number(document.getElementById('amount').value);
  document.getElementById('msg').textContent = (v > 0 || BUG)
    ? 'Submitted successfully' : 'Amount must be greater than 0';
};
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] in ("/", "/bug/"):
            body = (PAGE % ("true" if self.path.startswith("/bug/") else "false")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


class MiniShop:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


@cache
def browser_available() -> bool:
    import os

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False
