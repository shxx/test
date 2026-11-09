"""真实 HTTP 冒烟：经 stdlib http.server 起服务，验证端点可达与令牌链路。"""
from __future__ import annotations

import http.client
import json
import threading
import unittest

from ledger.app import App
from ledger.config import Settings
from ledger.db import connect
from tests.support import template


class TestHttpSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmpl, _ = template()
        conn = connect(":memory:")
        tmpl.backup(conn)
        from ledger.server import make_handler
        from http.server import ThreadingHTTPServer
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(conn, Settings(pbkdf2_iterations=1000))))
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
        r = conn.getresponse()
        data = r.read()
        out = (r.status, dict(r.getheaders()), data)
        conn.close()
        return out

    def test_login_stores_kpi_over_real_socket(self):
        status, _, data = self.req("POST", "/api/v1/auth/login",
                                   {"username": "east", "password": "Demo@12345"})
        self.assertEqual(200, status)
        token = json.loads(data)["data"]["token"]
        status, _, data = self.req("GET", "/api/v1/stores", token=token)
        self.assertEqual(200, status)
        self.assertEqual(2767, json.loads(data)["data"]["total"])
        status, _, data = self.req("GET", "/api/v1/kpi", token=token)
        self.assertEqual(200, status)
        self.assertEqual(2767, json.loads(data)["data"]["store_count"])
        status, _, data = self.req("GET", "/api/v1/stores/CANARY_SOUTH", token=token)
        self.assertEqual(403, status)
        self.assertEqual("OUT_OF_DOMAIN", json.loads(data)["error"]["code"])
        status, _, data = self.req("GET", "/healthz")
        self.assertEqual(200, status)


if __name__ == "__main__":
    unittest.main()
