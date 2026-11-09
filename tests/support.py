"""测试脚手架：一次性构造合成 fixture 模板，每个用例用 SQLite backup 克隆隔离。

模板是**合成**数据（etl.py），不是真实底表；测试断言的是域裁决逻辑、
接口契约、DQ 口径与审计行为，不声称真实 13 258 行底表已核对。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ledger.app import App  # noqa: E402
from ledger.auth import token_hash  # noqa: E402
from ledger.config import Settings  # noqa: E402
from ledger.db import connect, init_schema  # noqa: E402
from ledger.etl import DEFAULT_PASSWORD, build_synthetic_fixture  # noqa: E402

_TEMPLATE = None
_TEMPLATE_INFO = None


def template():
    global _TEMPLATE, _TEMPLATE_INFO
    if _TEMPLATE is None:
        _TEMPLATE = connect(":memory:")
        init_schema(_TEMPLATE)
        # 降低 PBKDF2 迭代以加速测试（仅影响合成账号，生产默认 120000）
        _TEMPLATE_INFO = build_synthetic_fixture(_TEMPLATE, Settings(pbkdf2_iterations=1000))
    return _TEMPLATE, _TEMPLATE_INFO


def template_info() -> dict[str, Any]:
    return template()[1]


def fresh_app(settings: Settings | None = None) -> App:
    tmpl, _ = template()
    cfg = settings or Settings(pbkdf2_iterations=1000)
    conn = connect(":memory:")
    tmpl.backup(conn)
    return App(conn, cfg)


class ApiClient:
    def __init__(self, app: App):
        self.app = app
        self.token: str | None = None

    def login(self, username: str, password: str = DEFAULT_PASSWORD) -> Any:
        resp = self.post("/api/v1/auth/login", {"username": username, "password": password})
        if resp.status == 200:
            self.token = resp.json_body()["data"]["token"]
        return resp

    def _headers(self, headers=None):
        h = dict(headers or {})
        if self.token:
            h.setdefault("Authorization", "Bearer " + self.token)
        return h

    def get(self, path: str, query=None, headers=None):
        return self.app.handle("GET", path, query or {}, self._headers(headers), b"")

    def post(self, path: str, payload=None, headers=None):
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        return self.app.handle("POST", path, {}, self._headers(headers), body)

    def patch(self, path: str, payload=None, headers=None):
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        return self.app.handle("PATCH", path, {}, self._headers(headers), body)

    def data(self, resp) -> Any:
        return resp.json_body()["data"]

    def code(self, resp) -> str | None:
        err = resp.json_body().get("error")
        return err["code"] if err else None


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.app = fresh_app()
        self.client = ApiClient(self.app)

    def assertNoCsvProduced(self, resp):
        """拒绝导出时不得产出 CSV 文件：无附件头、无 BOM、响应是错误信封。"""
        self.assertNotIn("Content-Disposition", resp.headers)
        self.assertNotIn("X-Export-Row-Count", resp.headers)
        self.assertTrue(resp.headers.get("Content-Type", "").startswith("application/json"))
        self.assertFalse(resp.body.startswith(b"\xef\xbb\xbf"))
        body = resp.json_body()
        self.assertIsNone(body["data"])
        self.assertIsNotNone(body["error"])

    def login(self, username: str):
        r = self.client.login(username)
        self.assertEqual(200, r.status, r.body.decode("utf-8", "replace"))
        return r.json_body()["data"]["token"]

    def raw_session(self, user_id: str, role_version: int = 1, token: str = "rawtoken") -> str:
        """直接插入会话记录（用于测试过期/吊销/角色版本等中间件分支）。"""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        row = self.app.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        self.app.conn.execute(
            "INSERT OR REPLACE INTO sessions(token_hash,user_id,role_snapshot,domain_snapshot,"
            "role_version,issued_at,expires_at,revoked,last_seen_at) VALUES (?,?,?,?,?,?,?,0,?)",
            (token_hash(token), user_id, row["role"], "{}", role_version,
             (now - timedelta(hours=1)).isoformat(), (now + timedelta(hours=1)).isoformat(),
             now.isoformat()),
        )
        self.app.conn.commit()
        return token
