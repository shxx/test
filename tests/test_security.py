"""L3 安全：哨兵行跨域零泄漏、篡改、防枚举、负向端点、注入、脱敏配置矩阵。"""
from __future__ import annotations

import json

from ledger.config import Settings
from tests.support import BaseCase, fresh_app


CANARIES = [
    "CANARY_EAST", "CANARY_SOUTH", "CANARY_NORTH", "CANARY_WEST",
    "CANARY_SHANHE", "CANARY_HUANPENG", "CANARY_LIRUI",
]


class TestCanaryNoLeak(BaseCase):
    """T-SEC-1：每个域插入哨兵行，遍历全部读端点断言跨域行零泄漏（DR-01）。"""

    def test_all_read_endpoints_never_leak_other_domain_rows(self):
        for username, own in (("hq", None), ("east", "CANARY_EAST"),
                              ("south", "CANARY_SOUTH"), ("north", "CANARY_NORTH"),
                              ("west", "CANARY_WEST"), ("shanhe", "CANARY_SHANHE"),
                              ("huanpeng", "CANARY_HUANPENG"), ("lirui", "CANARY_LIRUI")):
            app = fresh_app()
            from tests.support import ApiClient
            c = ApiClient(app)
            self.assertEqual(200, c.login(username).status, username)

            # 元数据派生集合
            meta = c.data(c.get("/api/v1/me/domain"))
            # 台账全量分页遍历
            seen = set()
            page = 1
            total = None
            while True:
                d = c.data(c.get("/api/v1/stores", {"page": str(page), "page_size": "200"}))
                total = d["total"]
                ids = [i["store_id"] for i in d["items"]]
                seen.update(ids)
                if page * 200 >= total:
                    break
                page += 1
            self.assertEqual(total, len(seen), username)
            for canary in CANARIES:
                if canary == own:
                    self.assertIn(canary, seen, f"{username} 应能看见本域哨兵 {canary}")
                elif username == "hq":
                    self.assertIn(canary, seen, "总部应能看见全部哨兵")
                else:
                    self.assertNotIn(canary, seen, f"{username} 泄漏了 {canary}")

            # KPI 聚合不含域外计数
            kpi = c.data(c.get("/api/v1/kpi"))
            self.assertEqual(len(seen), kpi["store_count"], username)

    def test_detail_cross_domain_uniform_403(self):
        self.login("east")
        for sid in ("CANARY_SOUTH", "CANARY_HUANPENG", "CANARY_LIRUI",
                    "DOES_NOT_EXIST", "DEAD000"):
            r = self.client.get("/api/v1/stores/" + sid)
            self.assertEqual(403, r.status, sid)
            self.assertEqual("OUT_OF_DOMAIN", self.client.code(r), sid)
            self.assertNotIn(sid, json.dumps(r.json_body(), ensure_ascii=False))

    def test_yearly_also_domain_scoped(self):
        self.login("hq")
        d = self.client.data(self.client.get("/api/v1/stores/CANARY_EAST"))
        self.assertEqual(3, len(d["yearly"]))
        self.login("south")
        r = self.client.get("/api/v1/stores/CANARY_EAST")
        self.assertEqual(403, r.status)


class TestClientTampering(BaseCase):
    def test_client_role_domain_params_ignored(self):
        self.login("east")
        base = self.client.data(self.client.get("/api/v1/stores", {"page_size": "200"}))
        for params in (
            {"role": "HQ", "domain": "all"},
            {"d_scope": "华南", "region_scope": "华南"},
            {"brand_scope": "欢朋", "domain_type": "all"},
        ):
            d = self.client.data(self.client.get("/api/v1/stores",
                                                 {"page_size": "200", **params}))
            self.assertEqual(base["total"], d["total"])
            self.assertEqual([i["store_id"] for i in base["items"]],
                             [i["store_id"] for i in d["items"]])

    def test_region_filter_other_value_cannot_widen(self):
        self.login("east")
        d = self.client.data(self.client.get("/api/v1/stores", {"region": "华南"}))
        self.assertEqual(2767, d["total"])
        self.assertEqual(["region"], d["scope"]["locked_dimension_ignored"])
        for item in d["items"]:
            self.assertEqual("华东", item["region"])

    def test_out_of_domain_filter_value_gives_no_hit(self):
        self.login("east")
        d = self.client.data(self.client.get("/api/v1/stores", {"province": "广东"}))
        self.assertEqual(0, d["total"])
        self.assertEqual([], d["items"])

    def test_sql_injection_payloads_are_parameterized(self):
        self.login("hq")
        payloads = [
            {"province": "' OR 1=1 --"},
            {"province": "江苏' UNION SELECT * FROM users --"},
            {"sort": "store_id; DROP TABLE stores; --"},
            {"order": "asc; DELETE FROM audit_log"},
            {"city": "%' OR '1'='1"},
        ]
        for p in payloads:
            r = self.client.get("/api/v1/stores", p)
            self.assertIn(r.status, (200, 400), p)
            if r.status == 200:
                self.assertLessEqual(self.client.data(r)["total"], 13258)
        # 表结构与数据未被破坏
        n = self.app.conn.execute("SELECT COUNT(*) c FROM stores").fetchone()["c"]
        self.assertGreater(n, 13000)


class TestNegativeEndpoints(BaseCase):
    def test_forbidden_paths_404(self):
        self.login("hq")
        for method, path in (
            ("GET", "/api/v1/dict/provinces"),
            ("GET", "/api/v1/dict/cities"),
            ("GET", "/api/v1/stores/all"),
            ("GET", "/api/v1/exports/all"),
            ("POST", "/api/v1/auth/switch-role"),
            ("GET", "/api/v1/competitors"),
            ("GET", "/api/v1/map/ak"),
            ("GET", "/api/v1/blocks/all"),
            ("GET", "/api/v1/anything"),
        ):
            r = self.app.handle(method, path, {},
                                {"authorization": "Bearer " + self.client.token}, b"")
            self.assertEqual(404, r.status, f"{method} {path}")
            self.assertEqual("NOT_FOUND", r.json_body()["error"]["code"])

    def test_no_unpaged_endpoint(self):
        self.login("hq")
        d = self.client.data(self.client.get("/api/v1/stores"))
        self.assertEqual(50, len(d["items"]))
        self.assertEqual(50, d["page_size"])


class TestRedactionMatrix(BaseCase):
    def test_redact_metrics_true_nulls_all_metric_fields(self):
        app = fresh_app(Settings(pbkdf2_iterations=1000, redact_metrics=True,
                                 export_enabled=False))
        from tests.support import ApiClient
        c = ApiClient(app)
        c.login("hq")
        items = c.data(c.get("/api/v1/stores", {"page_size": "5"}))["items"]
        for it in items:
            for k in ("rooms", "occ", "adr", "revpar"):
                self.assertIsNone(it[k], k)
        kpi = c.data(c.get("/api/v1/kpi"))
        self.assertIsNone(kpi["revpar_median"])
        self.assertIsNone(kpi["weighted"])
        detail = c.data(c.get("/api/v1/stores/CANARY_EAST"))
        self.assertIsNone(detail["store"]["rooms"])
        for y in detail["yearly"]:
            self.assertIsNone(y["rooms"])
        r = c.post("/api/v1/exports", {"filters": {}})
        self.assertEqual(403, r.status)
        self.assertEqual("EXPORT_DISABLED", r.json_body()["error"]["code"])

    def test_default_config_does_not_redact(self):
        self.login("hq")
        item = self.client.data(self.client.get("/api/v1/stores", {"page_size": "1"}))["items"][0]
        self.assertIsNotNone(item["rooms"])


if __name__ == "__main__":
    import unittest
    unittest.main()
