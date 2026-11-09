"""可运行 HTTP 服务（stdlib http.server / ThreadingHTTPServer）。

仅用于本地联调与端到端冒烟；生产部署形态未在需求中约束（§0.3）。
不引用任何地图 SDK / AK / 坐标转换（NFR-06）。
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .app import App


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "StoreLedger/1.0"

        def log_message(self, fmt, *args):  # 不把令牌写入访问日志
            pass

        def _dispatch(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query, keep_blank_values=True)
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items()}
            resp = app.handle(self.command, path, query, headers, body)
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp.body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if resp.body:
                self.wfile.write(resp.body)

        do_GET = _dispatch
        do_POST = _dispatch
        do_PATCH = _dispatch
        do_PUT = _dispatch
        do_DELETE = _dispatch

    return Handler


def serve(app: App, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.serve_forever()
    return httpd
