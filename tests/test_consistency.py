"""L4 一致性：台账 / 计数 / KPI / 导出四处同源（DQ-06），域∩筛选恒等。"""
from __future__ import annotations

from tests.support import BaseCase


class TestFourPlacesConsistency(BaseCase):
    def test_dead_store_absent_in_all_four(self):
        self.login("hq")
        ledger = self.client.data(self.client.get("/api/v1/stores", {"store_id": "DEAD000"}))
        self.assertEqual(0, ledger["total"])
        r = self.client.get("/api/v1/stores/DEAD000")
        self.assertEqual(403, r.status)  # 与域外 id 同语义，防枚举
        kpi = self.client.data(self.client.get("/api/v1/kpi"))
        self.assertEqual(13258, kpi["store_count"])
        exp = self.client.post("/api/v1/exports", {"store_ids": ["DEAD000"]})
        self.assertEqual(403, exp.status)
        self.assertEqual("EXPORT_OUT_OF_DOMAIN", self.client.code(exp))

    def test_dq_nulled_in_ledger_kpi_export(self):
        self.login("hq")
        item = self.client.data(self.client.get("/api/v1/stores", {"store_id": "DQ_ROOMS_HI"}))["items"][0]
        self.assertIsNone(item["rooms"])
        # 有效样本数随 DQ 剔除变化：13258 行中 2 行 revpar 越界/非正
        kpi = self.client.data(self.client.get("/api/v1/kpi"))
        self.assertEqual(13256, kpi["revpar_valid_sample_count"])
        self.assertLess(kpi["revpar_valid_sample_count"], kpi["store_count"])
        exp = self.client.post("/api/v1/exports", {"store_ids": ["DQ_ROOMS_HI"]})
        self.assertEqual(200, exp.status)
        text = exp.body.decode("utf-8-sig")
        lines = [l for l in text.splitlines() if l]
        self.assertIn("DQ_ROOMS_HI", text)
        # rooms 列（表头索引 11）为空
        header = lines[1].split(",") if lines[0].startswith("#") else lines[0].split(",")
        self.assertIn("rooms", header)

    def test_domain_intersect_filters_identity(self):
        self.login("east")
        combos = [
            {}, {"operate_type": "直营"}, {"province": "江苏"},
            {"operate_type": "直营", "province": "江苏"},
            {"city": "上海01市", "operate_type": "加盟"},
        ]
        for f in combos:
            ledger = self.client.data(self.client.get("/api/v1/stores", f))
            kpi = self.client.data(self.client.get("/api/v1/kpi", f))
            self.assertEqual(ledger["total"], kpi["store_count"], f)
            # 所有返回行都在域内且满足筛选
            for it in ledger["items"]:
                self.assertEqual("华东", it["region"])
                for k, v in f.items():
                    self.assertEqual(v, it[k], (k, v))
            # SQL 侧独立复核
            where = " AND ".join(["region=?"] + [f"{k}=?" for k in f])
            args = ["华东"] + list(f.values())
            n = self.app.conn.execute(
                f"SELECT COUNT(*) c FROM v_ledger WHERE {where}", args
            ).fetchone()["c"]
            self.assertEqual(n, ledger["total"], f)

    def test_kpi_filter_effective_sample_count_changes(self):
        self.login("hq")
        full = self.client.data(self.client.get("/api/v1/kpi"))
        filtered = self.client.data(self.client.get("/api/v1/kpi", {"province": "江苏"}))
        self.assertLess(filtered["revpar_valid_sample_count"], full["revpar_valid_sample_count"])
        self.assertEqual(filtered["store_count"], filtered["denominator"])
        self.assertEqual("当前口径", filtered["denominator_scope"])

    def test_weighted_metric_uses_correct_basis(self):
        self.login("hq")
        w = self.client.data(self.client.get("/api/v1/kpi"))["weighted"]
        self.assertEqual({"occ": "可售房晚", "adr": "售出房晚", "revpar": "可售房晚"},
                         w["weight_basis"])
        self.assertIsNotNone(w["occ"])
        self.assertIsNotNone(w["adr"])
        self.assertIsNotNone(w["revpar"])

    def test_derived_sets_are_domain_only(self):
        self.login("east")
        meta = self.client.data(self.client.get("/api/v1/me/domain"))
        self.assertEqual(6, len(meta["provinces"]))
        self.assertNotIn("广东", meta["provinces"])
        # 清单严格来自域内实际有数据的对象
        sql = "SELECT DISTINCT province FROM v_ledger WHERE region='华东' ORDER BY province"
        self.assertEqual([r[0] for r in self.app.conn.execute(sql)], meta["provinces"])


if __name__ == "__main__":
    import unittest
    unittest.main()
