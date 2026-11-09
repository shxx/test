"""验收标准服务端等价判据 T-01 ~ T-11（design.md §5.2）。

前置声明：13 258 等数字来自任务书转录值，本文件在**合成 fixture** 上验证
「域裁决逻辑与派生集合规则正确」，不代表真实底表逐角色核对已完成
（OPEN-14 / OPEN-15 仍开放，见 implementation.md）。
"""
from __future__ import annotations

import csv
import io

from ledger.config import Settings
from tests.support import ApiClient, BaseCase, fresh_app


class TestAC01_HQ(BaseCase):
    def test_t01(self):
        self.login("hq")
        kpi = self.client.data(self.client.get("/api/v1/kpi"))
        meta = self.client.data(self.client.get("/api/v1/me/domain"))
        self.assertEqual(13258, kpi["store_count"])
        self.assertEqual(365, kpi["city_count"])
        self.assertEqual(429, kpi["direct_count"])
        self.assertEqual(12829, kpi["franchise_count"])
        self.assertEqual(34, len(meta["provinces"]))
        self.assertEqual(47726, meta["competitor"]["count"])
        self.assertFalse(meta["competitor"]["is_approximate"])


class TestAC02_East(BaseCase):
    def test_t02(self):
        self.login("east")
        ledger = self.client.data(self.client.get("/api/v1/stores", {"page_size": "200"}))
        meta = self.client.data(self.client.get("/api/v1/me/domain"))
        kpi = self.client.data(self.client.get("/api/v1/kpi"))
        self.assertEqual(2767, ledger["total"])
        self.assertEqual(160, kpi["direct_count"])
        self.assertEqual(2607, kpi["franchise_count"])
        self.assertEqual(6, len(meta["provinces"]))
        self.assertNotIn("广东", meta["provinces"])  # 不含本区无门店的外区省份
        for it in ledger["items"]:
            self.assertEqual("华东", it["region"])
        # 默认视野落华东包围盒而非全国
        self.login("hq")
        national = self.client.data(self.client.get("/api/v1/me/domain"))["default_viewport"]
        self.assertNotEqual(national["min_lng"], meta["default_viewport"]["min_lng"])
        self.assertLess(national["min_lat"], meta["default_viewport"]["min_lat"])
        self.assertEqual("GCJ-02", meta["default_viewport"]["coord"])


class TestAC03_EastDirect(BaseCase):
    def test_t03(self):
        self.login("east")
        d = self.client.data(self.client.get("/api/v1/stores", {"operate_type": "直营"}))
        kpi = self.client.data(self.client.get("/api/v1/kpi", {"operate_type": "直营"}))
        self.assertEqual(160, d["total"])
        self.assertEqual(160, kpi["store_count"])
        self.assertEqual(160, kpi["direct_count"])
        self.assertEqual(0, kpi["franchise_count"])
        seen = set()
        for page in (1, 2):
            r = self.client.data(self.client.get("/api/v1/stores",
                                                 {"operate_type": "直营", "page": str(page),
                                                  "page_size": "100"}))
            for it in r["items"]:
                seen.add(it["store_id"])
                self.assertEqual("华东", it["region"])
                self.assertEqual("直营", it["operate_type"])
        self.assertEqual(160, len(seen))


class TestAC04_Huanpeng(BaseCase):
    def test_t04(self):
        self.login("huanpeng")
        d = self.client.data(self.client.get("/api/v1/stores", {"page_size": "200"}))
        self.assertEqual(544, d["total"])
        for page in range(1, 4):
            r = self.client.data(self.client.get("/api/v1/stores",
                                                 {"page": str(page), "page_size": "200"}))
            for it in r["items"]:
                self.assertEqual("欢朋", it["brand"])
                self.assertEqual("欢朋品牌BU", it["region"])
        meta = self.client.data(self.client.get("/api/v1/me/domain"))
        self.assertGreaterEqual(len(meta["provinces"]), 20)  # 跨 20 余省
        self.assertGreater(len(meta["cities"]), 0)


class TestAC05_LockedDimension(BaseCase):
    def test_t05(self):
        self.login("east")
        meta = self.client.data(self.client.get("/api/v1/me/domain"))
        self.assertTrue(meta["dimensions"]["region"]["locked"])
        self.assertEqual("已锁定", meta["dimensions"]["region"]["label"])
        self.assertEqual("华东", meta["dimensions"]["region"]["fixed_value"])
        # 服务端不接受跨区筛选值、结果不放宽
        d = self.client.data(self.client.get("/api/v1/stores", {"region": "华北"}))
        self.assertTrue(d["scope"]["locked_dimension_ignored"])
        self.assertEqual(2767, d["total"])
        # 域外省份不出现在可选清单
        self.assertNotIn("广东", meta["provinces"])


class TestAC06_OutOfDomain(BaseCase):
    def test_t06(self):
        self.login("east")
        for sid in ("CANARY_SOUTH", "CANARY_HUANPENG", "NO_SUCH_ID"):
            r = self.client.get("/api/v1/stores/" + sid)
            self.assertEqual(403, r.status, sid)
            self.assertEqual("OUT_OF_DOMAIN", self.client.code(r), sid)
            self.assertEqual("超出数据域", r.json_body()["error"]["message"])
        rows = list(self.app.conn.execute(
            "SELECT * FROM audit_log WHERE event_type='OVERSCOPE_ATTEMPT'"))
        self.assertEqual(3, len(rows))


class TestAC07_ExportLimit(BaseCase):
    def test_t07(self):
        self.login("hq")
        ids = [r[0] for r in self.app.conn.execute(
            "SELECT store_id FROM v_ledger ORDER BY store_id LIMIT 5000")]
        ok = self.client.post("/api/v1/exports", {"store_ids": ids})
        self.assertEqual(200, ok.status)
        self.assertEqual("5000", ok.headers["X-Export-Row-Count"])
        # 恰好 5 001 行 -> 拒绝（仅总部可达）
        one_more = [r[0] for r in self.app.conn.execute(
            "SELECT store_id FROM v_ledger ORDER BY store_id LIMIT 5001")]
        bad = self.client.post("/api/v1/exports", {"store_ids": one_more})
        self.assertEqual(422, bad.status)
        self.assertEqual("EXPORT_LIMIT_EXCEEDED", self.client.code(bad))
        self.assertNoCsvProduced(bad)  # 无文件产出
        rows = list(self.app.conn.execute(
            "SELECT * FROM audit_log WHERE reason_code='EXPORT_LIMIT_EXCEEDED'"))
        self.assertEqual(1, len(rows))
        self.assertEqual(5001, rows[0]["row_count"])


class TestAC08_RoleChange(BaseCase):
    def test_t08(self):
        old_token = self.login("east")
        admin = ApiClient(self.app)
        admin.login("admin")
        r = admin.patch("/api/v1/admin/users/u_east", {"role": "REGION", "scope": "华南"})
        self.assertEqual(200, r.status)
        # 旧令牌立即失效
        old = self.app.handle("GET", "/api/v1/stores", {},
                              {"authorization": "Bearer " + old_token}, b"")
        self.assertEqual(401, old.status)
        self.assertEqual("ROLE_CHANGED_RELOGIN", old.json_body()["error"]["code"])
        # 新登录按新域
        new = ApiClient(self.app)
        self.assertEqual(200, new.login("east").status)
        d = new.data(new.get("/api/v1/stores", {"page_size": "1"}))
        self.assertEqual(2781, d["total"])
        self.assertEqual("华南", d["items"][0]["region"])
        rows = list(self.app.conn.execute(
            "SELECT * FROM audit_log WHERE event_type='ROLE_CHANGE'"))
        self.assertEqual(1, len(rows))


class TestAC09_InnerMongolia(BaseCase):
    def test_t09(self):
        north = ApiClient(self.app)
        north.login("north")
        west = ApiClient(self.app)
        west.login("west")
        n = north.data(north.get("/api/v1/stores/CANARY_NM_NORTH"))
        w = west.data(west.get("/api/v1/stores/CANARY_NM_WEST"))
        self.assertEqual("内蒙古", n["store"]["province"])
        self.assertEqual("华北", n["store"]["region"])
        self.assertEqual("内蒙古", w["store"]["province"])
        self.assertEqual("华西", w["store"]["region"])
        # 省份清单两个大区都含内蒙古，但省份清单不是权限依据
        nm = north.data(north.get("/api/v1/me/domain"))
        wm = west.data(west.get("/api/v1/me/domain"))
        self.assertIn("内蒙古", nm["provinces"])
        self.assertIn("内蒙古", wm["provinces"])
        self.assertEqual(403, north.get("/api/v1/stores/CANARY_NM_WEST").status)
        self.assertEqual(403, west.get("/api/v1/stores/CANARY_NM_NORTH").status)


class TestAC10_CompetitorApprox(BaseCase):
    def test_t10(self):
        # 竞品表确无 region 字段
        cols = [r["name"] for r in self.app.conn.execute("PRAGMA table_info(competitors)")]
        self.assertNotIn("region", cols)
        self.login("east")
        kpi = self.client.data(self.client.get("/api/v1/kpi"))
        c = kpi["competitor"]
        self.assertGreater(c["count"], 0)
        self.assertTrue(c["is_approximate"])
        self.assertEqual("province_mapping", c["method"])
        self.assertIn("近似", c["note"])
        hq = ApiClient(self.app)
        hq.login("hq")
        self.assertFalse(hq.data(hq.get("/api/v1/me/domain"))["competitor"]["is_approximate"])


class TestAC11_MapIndependent(BaseCase):
    def test_t11(self):
        # 不配置任何 AK、无地图依赖：台账 -> 详情 -> KPI -> 导出全链路跑通
        app = fresh_app(Settings(pbkdf2_iterations=1000))
        c = ApiClient(app)
        c.login("east")
        self.assertEqual(200, c.get("/api/v1/stores").status)
        self.assertEqual(200, c.get("/api/v1/stores/CANARY_EAST").status)
        self.assertEqual(200, c.get("/api/v1/kpi").status)
        self.assertEqual(200, c.get("/api/v1/me/domain").status)
        exp = c.post("/api/v1/exports", {"filters": {"province": "江苏"}})
        self.assertEqual(200, exp.status)
        self.assertEqual("GCJ-02", c.data(c.get("/api/v1/me/domain"))["default_viewport"]["coord"])
        # 坐标原样返回，未做 BD-09 转换
        d = c.data(c.get("/api/v1/stores/CANARY_EAST"))["store"]
        raw = app.conn.execute("SELECT lng_gcj02, lat_gcj02 FROM v_ledger WHERE store_id=?",
                               ("CANARY_EAST",)).fetchone()
        self.assertEqual(raw["lng_gcj02"], d["lng_gcj02"])
        self.assertEqual(raw["lat_gcj02"], d["lat_gcj02"])


class TestExportFileContract(BaseCase):
    def test_bom_filename_watermark_rowcount(self):
        self.login("east")
        r = self.client.post("/api/v1/exports", {"filters": {"operate_type": "直营"}})
        self.assertEqual(200, r.status)
        self.assertTrue(r.body.startswith(b"\xef\xbb\xbf"))
        disp = r.headers["Content-Disposition"]
        self.assertIn("filename*=UTF-8''", disp)
        self.assertIn("%E5%8D%8E%E4%B8%9C", disp)  # 「华东」
        self.assertTrue(r.headers["Content-Disposition"].endswith(".csv\"") or ".csv" in disp)
        text = r.body.decode("utf-8-sig")
        self.assertTrue(text.splitlines()[0].startswith("# 角色:"))
        self.assertIn("导出时间:", text.splitlines()[0])
        rows = list(csv.reader(io.StringIO(text)))
        header = rows[1]
        self.assertIn("__export_role", header)
        self.assertIn("__exported_at", header)
        data_rows = rows[2:]
        self.assertEqual(160, len(data_rows))
        self.assertEqual("160", r.headers["X-Export-Row-Count"])
        for row in data_rows:
            self.assertIn("大区:华东", row[header.index("__export_role")])
            self.assertTrue(row[header.index("__exported_at")])

    def test_export_whole_order_rejected_when_any_id_out_of_domain(self):
        self.login("east")
        r = self.client.post("/api/v1/exports",
                             {"store_ids": ["CANARY_EAST", "CANARY_SOUTH"]})
        self.assertEqual(403, r.status)
        self.assertEqual("EXPORT_OUT_OF_DOMAIN", self.client.code(r))
        self.assertNoCsvProduced(r)


if __name__ == "__main__":
    import unittest
    unittest.main()
