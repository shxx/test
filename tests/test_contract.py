"""L2 接口/契约：全部端点、错误码、统一信封、元数据齐全性、分页与稳定排序。"""
from __future__ import annotations

import json

from tests.support import BaseCase, fresh_app


class TestEnvelopeAndAuth(BaseCase):
    def test_healthz_contains_no_business_data(self):
        r = self.client.get("/healthz")
        self.assertEqual(200, r.status)
        self.assertEqual({"status": "ok"}, self.client.data(r))

    def test_login_envelope_fields(self):
        r = self.client.post("/api/v1/auth/login", {"username": "hq", "password": "Demo@12345"})
        self.assertEqual(200, r.status)
        body = r.json_body()
        self.assertEqual({"data", "meta", "error", "trace_id"}, set(body))
        self.assertIsNone(body["error"])
        self.assertIn("data_version", body["meta"])
        d = body["data"]
        self.assertEqual({"token", "token_type", "issued_at", "expires_at", "user"}, set(d))
        self.assertEqual({"user_id", "username", "display_name", "role", "role_label",
                          "role_version", "domain", "is_admin"}, set(d["user"]))
        self.assertEqual({"type", "scope"}, set(d["user"]["domain"]))

    def test_login_bad_password_uniform_401(self):
        a = self.client.post("/api/v1/auth/login", {"username": "hq", "password": "wrong"})
        b = self.client.post("/api/v1/auth/login", {"username": "nobody", "password": "wrong"})
        self.assertEqual(401, a.status)
        self.assertEqual(401, b.status)
        self.assertEqual(self.client.code(a), self.client.code(b))
        self.assertEqual("AUTH_FAILED", self.client.code(a))
        self.assertIsNone(a.json_body()["data"])

    def test_error_envelope(self):
        r = self.client.get("/api/v1/stores")
        self.assertEqual(401, r.status)
        body = r.json_body()
        self.assertEqual({"data", "meta", "error", "trace_id"}, set(body))
        self.assertIsNone(body["data"])
        self.assertEqual("TOKEN_MISSING", body["error"]["code"])
        self.assertIn("message", body["error"])

    def test_token_only_stored_as_hash(self):
        self.login("hq")
        row = self.app.conn.execute("SELECT token_hash FROM sessions LIMIT 1").fetchone()
        self.assertNotEqual(self.client.token, row["token_hash"])
        self.assertEqual(64, len(row["token_hash"]))

    def test_logout_204_and_revokes(self):
        self.login("hq")
        r = self.client.post("/api/v1/auth/logout", {})
        self.assertEqual(204, r.status)
        r2 = self.client.get("/api/v1/stores")
        self.assertEqual(401, r2.status)
        self.assertEqual("SESSION_REVOKED", self.client.code(r2))


class TestDomainMetadata(BaseCase):
    def test_metadata_field_completeness(self):
        self.login("east")
        r = self.client.get("/api/v1/me/domain")
        self.assertEqual(200, r.status)
        d = self.client.data(r)
        for key in ("role", "role_label", "role_version", "domain", "provinces", "cities",
                    "blocks", "dimensions", "default_viewport", "competitor",
                    "data_version", "as_of_date", "ytd", "metric_notes"):
            self.assertIn(key, d, key)
        self.assertIn("locked", d["dimensions"]["region"])
        self.assertIn("coord", d["default_viewport"])
        self.assertIn("is_approximate", d["competitor"])
        self.assertIn("note", d["ytd"])
        self.assertIn("weighting", d["metric_notes"])

    def test_region_locked_metadata(self):
        self.login("east")
        d = self.client.data(self.client.get("/api/v1/me/domain"))
        self.assertTrue(d["dimensions"]["region"]["locked"])
        self.assertEqual("已锁定", d["dimensions"]["region"]["label"])
        self.assertEqual("华东", d["dimensions"]["region"]["fixed_value"])

    def test_bu_region_dimension_not_locked(self):
        self.login("huanpeng")
        d = self.client.data(self.client.get("/api/v1/me/domain"))
        self.assertFalse(d["dimensions"]["region"]["locked"])

    def test_hq_competitor_is_exact(self):
        self.login("hq")
        d = self.client.data(self.client.get("/api/v1/me/domain"))
        self.assertFalse(d["competitor"]["is_approximate"])
        self.assertEqual(47726, d["competitor"]["count"])


class TestStoresContract(BaseCase):
    def test_pagination_and_stable_sort(self):
        self.login("hq")
        r = self.client.get("/api/v1/stores", {"page": "1", "page_size": "10", "sort": "store_id"})
        self.assertEqual(200, r.status)
        d = self.client.data(r)
        self.assertEqual(13258, d["total"])
        self.assertEqual(1, d["page"])
        self.assertEqual(10, d["page_size"])
        self.assertEqual(10, len(d["items"]))
        ids = [i["store_id"] for i in d["items"]]
        self.assertEqual(sorted(ids), ids)
        r2 = self.client.get("/api/v1/stores", {"page": "2", "page_size": "10", "sort": "store_id"})
        self.assertNotIn(ids[-1], [i["store_id"] for i in self.client.data(r2)["items"]])

    def test_paging_upper_limit(self):
        self.login("hq")
        r = self.client.get("/api/v1/stores", {"page_size": "201"})
        self.assertEqual(400, r.status)
        self.assertEqual("INVALID_FILTER", self.client.code(r))

    def test_response_uses_dq_view_columns_not_raw(self):
        self.login("hq")
        d = self.client.data(self.client.get("/api/v1/stores", {"store_id": "DQ_ROOMS_HI"}))
        self.assertEqual(1, d["total"])
        self.assertIsNone(d["items"][0]["rooms"])
        self.assertNotIn("rooms_v", d["items"][0])

    def test_scope_signature_and_ignored_params(self):
        self.login("east")
        d = self.client.data(self.client.get("/api/v1/stores", {
            "page": "1", "role": "HQ", "domain": "all", "d_scope": "华南",
        }))
        self.assertEqual(2767, d["total"])
        self.assertIn("role", d["scope"]["ignored_client_params"])
        self.assertIn("d_scope", d["scope"]["ignored_client_params"])
        self.assertEqual(64, len(d["scope"]["filter_signature"]))

    def test_unknown_filter_400(self):
        self.login("hq")
        r = self.client.get("/api/v1/stores", {"1=1": "x"})
        self.assertEqual(400, r.status)
        self.assertEqual("INVALID_FILTER", self.client.code(r))

    def test_method_not_allowed(self):
        self.login("hq")
        r = self.client.post("/api/v1/stores", {})
        self.assertEqual(405, r.status)


class TestErrorCodes(BaseCase):
    def test_out_of_domain_403_no_fields_echoed(self):
        self.login("east")
        r = self.client.get("/api/v1/stores/CANARY_SOUTH")
        self.assertEqual(403, r.status)
        self.assertEqual("OUT_OF_DOMAIN", self.client.code(r))
        self.assertNotIn("CANARY_SOUTH", json.dumps(r.json_body(), ensure_ascii=False))
        self.assertIsNone(r.json_body()["data"])

    def test_novalid_domain_rejects_login(self):
        for name in ("nodomain", "badrole"):
            r = self.client.post("/api/v1/auth/login", {"username": name, "password": "Demo@12345"})
            self.assertEqual(403, r.status, name)
            self.assertEqual("NO_VALID_DOMAIN", self.client.code(r), name)

    def test_no_valid_domain_middleware_path(self):
        token = self.raw_session("u_nodomain")
        r = self.app.handle("GET", "/api/v1/stores", {}, {"authorization": "Bearer " + token}, b"")
        self.assertEqual(403, r.status)
        self.assertEqual("NO_VALID_DOMAIN", r.json_body()["error"]["code"])

    def test_token_expired_and_invalid(self):
        r = self.app.handle("GET", "/api/v1/stores", {}, {"authorization": "Bearer nonexistent"}, b"")
        self.assertEqual("TOKEN_INVALID", r.json_body()["error"]["code"])
        token = self.raw_session("u_hq")
        self.app.conn.execute("UPDATE sessions SET expires_at=?", ("2000-01-01T00:00:00+00:00",))
        self.app.conn.commit()
        r2 = self.app.handle("GET", "/api/v1/stores", {}, {"authorization": "Bearer " + token}, b"")
        self.assertEqual("TOKEN_EXPIRED", r2.json_body()["error"]["code"])

    def test_admin_forbidden(self):
        self.login("hq")
        r = self.client.get("/api/v1/admin/audit")
        self.assertEqual(403, r.status)
        self.assertEqual("ADMIN_FORBIDDEN", self.client.code(r))


class TestKpiContract(BaseCase):
    def test_kpi_fields(self):
        self.login("east")
        r = self.client.get("/api/v1/kpi")
        self.assertEqual(200, r.status)
        d = self.client.data(r)
        for k in ("store_count", "direct_count", "franchise_count", "city_count",
                  "province_count", "revpar_median", "revpar_valid_sample_count",
                  "weighted", "metric_coverage", "denominator_scope", "competitor",
                  "data_version", "as_of_date", "ytd", "filter_signature"):
            self.assertIn(k, d, k)
        self.assertEqual("当前口径", d["denominator_scope"])
        self.assertTrue(d["competitor"]["is_approximate"])

    def test_kpi_no_out_of_domain_aggregate(self):
        self.login("east")
        d = self.client.data(self.client.get("/api/v1/kpi"))
        self.assertEqual(2767, d["store_count"])
        self.assertEqual(160, d["direct_count"])
        self.assertEqual(6, d["province_count"])


if __name__ == "__main__":
    import unittest
    unittest.main()
