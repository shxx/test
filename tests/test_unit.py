"""L1 单元：域谓词、白名单、role_version、筛选签名、DQ、分页、中位数、CSV。"""
from __future__ import annotations

import json
import unittest

from ledger.config import Settings
from ledger.domain import (
    DomainContext, domain_predicate, filter_predicate, normalize_signature,
    parse_filters, parse_paging, parse_sort,
)
from ledger.errors import ApiError
from ledger.etl import apply_dq_to_row, validate_region
from ledger.repository import _median
from ledger.services import ExportService
from tests.support import BaseCase, fresh_app, template_info


class TestDomainPredicate(unittest.TestCase):
    def make(self, role, scope):
        return DomainContext(
            user_id="u", username="u", display_name="u", role=role, scope=scope,
            role_version=1,
            geo_whitelist=frozenset({"华东", "华南", "华北", "华西", "山河"}),
            brand_whitelist=frozenset({"欢朋", "丽芮"}),
        )

    def test_hq_all_true_but_same_constructor(self):
        sql, params = domain_predicate(self.make("HQ", None))
        self.assertEqual("1=1", sql)
        self.assertEqual({}, params)

    def test_region_uses_region_column_by_name(self):
        sql, params = domain_predicate(self.make("REGION", "华东"))
        self.assertIn("region = :d_scope", sql)
        self.assertEqual({"d_scope": "华东"}, params)

    def test_brand_bu_uses_brand_column_not_region_brand_value(self):
        sql, params = domain_predicate(self.make("BRAND_BU", "欢朋"))
        self.assertIn("brand = :d_scope", sql)
        self.assertNotIn("region", sql)
        self.assertEqual({"d_scope": "欢朋"}, params)

    def test_whitelist_by_kind_not_by_ordinal(self):
        conn = fresh_app().conn
        rows = list(conn.execute(
            "SELECT name, kind, ordinal FROM region_dict ORDER BY ordinal"
        ))
        # 索引 0 与 5 是品牌值；按 ordinal 取前五个会错
        self.assertEqual("BRAND_VALUE", rows[0]["kind"])
        self.assertEqual("BRAND_VALUE", rows[5]["kind"])
        geo = [r["name"] for r in rows if r["kind"] == "GEO"]
        self.assertEqual(5, len(geo))
        self.assertEqual(["华东", "华南", "华北", "华西", "山河"], geo)
        self.assertNotIn(rows[0]["name"], geo)

    def test_invalid_role_and_empty_scope_default_deny(self):
        for ctx in (self.make("UNKNOWN", None), self.make("REGION", ""),
                    self.make("REGION", "欢朋品牌BU"), self.make("BRAND_BU", ""),
                    self.make("BRAND_BU", "华东")):
            with self.assertRaises(ApiError) as cm:
                domain_predicate(ctx)
            self.assertEqual("NO_VALID_DOMAIN", cm.exception.code)


class TestFilterAndSignature(unittest.TestCase):
    def setUp(self):
        self.ctx = DomainContext(
            user_id="u", username="u", display_name="u", role="REGION", scope="华东",
            role_version=1, geo_whitelist=frozenset({"华东", "华南"}),
            brand_whitelist=frozenset({"欢朋"}),
        )

    def test_filter_predicate_is_parameterized(self):
        sql, params = filter_predicate({"province": "江苏", "operate_type": "直营"})
        self.assertIn(":f_province", sql)
        self.assertIn(":f_operate_type", sql)
        self.assertNotIn("江苏", sql)
        self.assertEqual({"f_province": "江苏", "f_operate_type": "直营"}, params)

    def test_client_domain_params_ignored(self):
        filters, ignored, _, _ = parse_filters(self.ctx, {
            "province": "江苏", "role": "HQ", "domain": "all", "d_scope": "华南",
            "region_scope": "华南", "brand_scope": "欢朋",
        })
        self.assertEqual({"province": "江苏"}, filters)
        self.assertEqual(5, len(ignored))
        self.assertEqual({"role", "domain", "d_scope", "region_scope", "brand_scope"},
                         set(ignored))

    def test_unknown_field_rejected(self):
        with self.assertRaises(ApiError) as cm:
            parse_filters(self.ctx, {"region = 1 OR 1": "x"})
        self.assertEqual("INVALID_FILTER", cm.exception.code)

    def test_locked_dimension_ignored_for_region_role(self):
        filters, _, locked, notes = parse_filters(self.ctx, {"region": "华南"})
        self.assertEqual({}, filters)
        self.assertEqual(["region"], locked)
        self.assertTrue(any("已锁定" in n for n in notes))

    def test_signature_order_independent(self):
        a = normalize_signature(self.ctx, {"province": "江苏", "operate_type": "直营"}, "V1")
        b = normalize_signature(self.ctx, {"operate_type": "直营", "province": "江苏"}, "V1")
        c = normalize_signature(self.ctx, {"province": "浙江"}, "V1")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(64, len(a))

    def test_sort_and_paging_whitelists(self):
        self.assertEqual(("store_id", "ASC"), parse_sort(None, None))
        self.assertEqual(("rooms_v", "DESC"), parse_sort("rooms", "desc"))
        with self.assertRaises(ApiError):
            parse_sort("store_id; DROP TABLE stores", None)
        with self.assertRaises(ApiError):
            parse_sort(None, "desc; --")
        s = Settings()
        self.assertEqual((1, 50), parse_paging(None, None, s))
        self.assertEqual((3, 200), parse_paging("3", "200", s))
        with self.assertRaises(ApiError):
            parse_paging("1", "201", s)
        with self.assertRaises(ApiError):
            parse_paging("0", "50", s)


class TestDQ(unittest.TestCase):
    def test_dq_bounds_left_open_right_closed(self):
        cases = [
            ("rooms", 0, None), ("rooms", 3000, 3000), ("rooms", 3000.1, None),
            ("occ", 1.2, 1.2), ("occ", 1.2001, None), ("occ", -0.1, None),
            ("adr", 5000, 5000), ("adr", 5001, None),
            ("revpar", 3000, 3000), ("revpar", 3001, None),
        ]
        for col, value, expected in cases:
            out = apply_dq_to_row({col: value})
            self.assertEqual(expected, out[col], f"{col}={value}")

    def test_dq_does_not_drop_row(self):
        out = apply_dq_to_row({"store_id": "X", "rooms": 99999})
        self.assertEqual("X", out["store_id"])
        self.assertIsNone(out["rooms"])

    def test_v_ledger_double_insurance(self):
        app = fresh_app()
        rows = {r["store_id"]: dict(r) for r in app.conn.execute("SELECT * FROM v_ledger")}
        self.assertIsNone(rows["DQ_ROOMS_HI"]["rooms_v"])
        self.assertIsNone(rows["DQ_OCC_HI"]["occ_v"])
        self.assertIsNone(rows["DQ_ADR_HI"]["adr_v"])
        self.assertIsNone(rows["DQ_REVPAR_HI"]["revpar_v"])
        self.assertIsNone(rows["DQ_NONPOSITIVE"]["revpar_v"])
        self.assertEqual(3000, rows["DQ_BOUNDARY_OK"]["rooms_v"])
        self.assertEqual(1.2, rows["DQ_BOUNDARY_OK"]["occ_v"])

    def test_dead_stores_excluded_from_view(self):
        app = fresh_app()
        n = app.conn.execute("SELECT COUNT(*) c FROM stores WHERE is_dead=1").fetchone()["c"]
        self.assertGreater(n, 0)
        v = app.conn.execute("SELECT COUNT(*) c FROM v_ledger WHERE store_id LIKE 'DEAD%'").fetchone()["c"]
        self.assertEqual(0, v)

    def test_median(self):
        self.assertIsNone(_median([]))
        self.assertEqual(2.0, _median([1, 2, 3]))
        self.assertEqual(2.5, _median([1, 2, 3, 4]))

    def test_validate_region_report(self):
        app = fresh_app()
        rep = validate_region(app.conn)
        self.assertEqual(5, rep["geo_name_count"])
        self.assertEqual(34, len(set(
            r["province"] for r in app.conn.execute("SELECT DISTINCT province FROM v_ledger")
        )))
        self.assertGreater(rep["brand_value_count"], 0)
        self.assertTrue(all("store_id" in x for x in rep["empty_or_illegal"]))


class TestCsvHelpers(unittest.TestCase):
    def test_injection_guard(self):
        self.assertEqual("'=SUM(A1)", ExportService._guard_injection("=SUM(A1)"))
        self.assertEqual("'@x", ExportService._guard_injection("@x"))
        # 以 = + - @ 开头的单元格一律加前导单引号（design.md §2.4.8 CSV 注入防护）
        self.assertEqual("'+123", ExportService._guard_injection("+123"))
        self.assertEqual("'-123", ExportService._guard_injection("-123"))
        self.assertEqual("normal", ExportService._guard_injection("normal"))
        self.assertEqual(123, ExportService._guard_injection(123))

    def test_fixture_baseline_numbers_are_reproduced(self):
        info = template_info()
        self.assertEqual(13258, info["stores_live_in_v_ledger"])
        self.assertEqual(365, info["cities"])
        self.assertEqual(34, info["provinces"])
        self.assertEqual(47726, info["competitors"])


if __name__ == "__main__":
    unittest.main()
