"""L5 审计：四类事件字段齐全、拒绝留痕、签名可复现、写失败不放行导出。"""
from __future__ import annotations

import json

from tests.support import ApiClient, BaseCase, fresh_app


class TestAuditEvents(BaseCase):
    def audit_rows(self, event_type=None):
        if event_type:
            return [dict(r) for r in self.app.conn.execute(
                "SELECT * FROM audit_log WHERE event_type=? ORDER BY id", (event_type,))]
        return [dict(r) for r in self.app.conn.execute("SELECT * FROM audit_log ORDER BY id")]

    def test_export_success_event(self):
        self.login("hq")
        r = self.client.post("/api/v1/exports", {"filters": {"region": "华东"}, "sort": "store_id"})
        self.assertEqual(200, r.status)
        rows = self.audit_rows("EXPORT_SUCCESS")
        self.assertEqual(1, len(rows))
        a = rows[0]
        self.assertEqual("HQ", a["actor_role"])
        self.assertEqual("u_hq", a["actor_user_id"])
        self.assertEqual(2767, a["row_count"])
        self.assertIsNotNone(a["filter_signature"])
        self.assertIsNotNone(a["created_at"])
        self.assertEqual("SUCCESS", a["result"])
        self.assertEqual(a["filter_signature"], r.headers["X-Filter-Signature"])

    def test_signature_reproducible_regardless_of_key_order(self):
        self.login("hq")
        a = self.client.post("/api/v1/exports", {
            "filters": {"region": "华东", "operate_type": "直营"}})
        b = self.client.post("/api/v1/exports", {
            "filters": {"operate_type": "直营", "region": "华东"}})
        self.assertEqual(200, a.status)
        self.assertEqual(200, b.status)
        self.assertEqual(a.headers["X-Filter-Signature"], b.headers["X-Filter-Signature"])
        sigs = [r["filter_signature"] for r in self.audit_rows("EXPORT_SUCCESS")]
        self.assertEqual(sigs[0], sigs[1])

    def test_overscope_attempt_event_on_detail(self):
        self.login("east")
        r = self.client.get("/api/v1/stores/CANARY_SOUTH")
        self.assertEqual(403, r.status)
        rows = self.audit_rows("OVERSCOPE_ATTEMPT")
        self.assertEqual(1, len(rows))
        self.assertEqual("CANARY_SOUTH", rows[0]["target_object"])
        self.assertEqual("REJECTED", rows[0]["result"])
        self.assertEqual("OUT_OF_DOMAIN", rows[0]["reason_code"])

    def test_export_rejected_limit_and_no_file(self):
        self.login("hq")
        r = self.client.post("/api/v1/exports", {"filters": {}})
        self.assertEqual(422, r.status)
        self.assertEqual("EXPORT_LIMIT_EXCEEDED", self.client.code(r))
        self.assertNoCsvProduced(r)
        rows = self.audit_rows("EXPORT_REJECTED")
        self.assertEqual(1, len(rows))
        self.assertEqual(13258, rows[0]["row_count"])
        self.assertEqual("EXPORT_LIMIT_EXCEEDED", rows[0]["reason_code"])
        self.assertIsNotNone(rows[0]["filter_signature"])

    def test_explicit_empty_selection_does_not_expand_to_full_export(self):
        self.login("hq")
        r = self.client.post("/api/v1/exports", {"store_ids": []})
        self.assertEqual(200, r.status)
        self.assertEqual("0", r.headers["X-Export-Row-Count"])
        self.assertNotIn("CANARY_EAST", r.body.decode("utf-8-sig"))

    def test_large_store_ids_rejection_is_audited(self):
        # 超出上限的显式选行也必须走 COUNT 路径并留痕，不得静默 422
        self.login("hq")
        ids = [r[0] for r in self.app.conn.execute(
            "SELECT store_id FROM v_ledger ORDER BY store_id LIMIT 5100")]
        r = self.client.post("/api/v1/exports", {"store_ids": ids})
        self.assertEqual(422, r.status)
        rows = self.audit_rows("EXPORT_REJECTED")
        self.assertEqual(1, len(rows))
        self.assertEqual("EXPORT_LIMIT_EXCEEDED", rows[0]["reason_code"])

    def test_export_rejected_out_of_domain(self):
        self.login("east")
        r = self.client.post("/api/v1/exports", {"store_ids": ["CANARY_EAST", "CANARY_SOUTH"]})
        self.assertEqual(403, r.status)
        self.assertEqual("EXPORT_OUT_OF_DOMAIN", self.client.code(r))
        self.assertNoCsvProduced(r)
        self.assertEqual(1, len(self.audit_rows("EXPORT_REJECTED")))
        self.assertEqual(1, len(self.audit_rows("OVERSCOPE_ATTEMPT")))
        self.assertEqual(0, len(self.audit_rows("EXPORT_SUCCESS")))

    def test_role_change_event(self):
        self.login("hq")
        admin = ApiClient(self.app)
        admin.login("admin")
        before = admin.data(admin.get("/api/v1/me/domain"))
        r = admin.patch("/api/v1/admin/users/u_east", {"role": "REGION", "scope": "华南"})
        self.assertEqual(200, r.status)
        rows = self.audit_rows("ROLE_CHANGE")
        self.assertEqual(1, len(rows))
        detail = json.loads(rows[0]["detail_json"])
        self.assertEqual("u_admin", detail["operator"])
        self.assertEqual("u_east", detail["target"])
        self.assertEqual("REGION", detail["before"]["role"])
        self.assertEqual("华东", detail["before"]["region_scope"])
        self.assertEqual("华南", detail["after"]["region_scope"])
        self.assertEqual(2, detail["after"]["role_version"])
        self.assertIn("changed_at", detail)

    def test_audit_failure_does_not_release_export(self):
        app = fresh_app()
        app.settings.log_tracebacks = False  # 故意注入的故障，不必打印堆栈
        c = ApiClient(app)
        c.login("hq")
        app.audit.fail_on_write = True
        r = c.post("/api/v1/exports", {"store_ids": ["CANARY_EAST"]})
        self.assertEqual(500, r.status)
        self.assertNoCsvProduced(r)  # 审计写失败不放行导出
        rows = [dict(x) for x in app.conn.execute("SELECT * FROM audit_log")]
        self.assertEqual(0, len(rows), "审计预写失败必须回滚")

    def test_admin_audit_query(self):
        self.login("east")
        self.client.get("/api/v1/stores/CANARY_SOUTH")
        admin = ApiClient(self.app)
        admin.login("admin")
        r = admin.get("/api/v1/admin/audit", {"event_type": "OVERSCOPE_ATTEMPT"})
        self.assertEqual(200, r.status)
        d = admin.data(r)
        self.assertEqual(1, d["total"])
        self.assertEqual("OVERSCOPE_ATTEMPT", d["items"][0]["event_type"])
        bad = admin.get("/api/v1/admin/audit", {"unknown": "x"})
        self.assertEqual(400, bad.status)


if __name__ == "__main__":
    import unittest
    unittest.main()
