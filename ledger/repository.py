"""唯一裁决点（Single Choke Point）。

构造 Repository **必须**传入 DomainContext；类上没有「不带域」的重载，
所有台账/详情/聚合/派生集合/导出查询都经 self.where() 注入参数化域谓词。
任何 handler 都不能绕过此类直连底表（DR-01）。

- 数据源恒为 v_ledger（DQ-01 越界置空 + DQ-02 死店剔除），保证 DQ-06 四处一致
- 域谓词在 SQL WHERE，分页 COUNT/聚合/导出同源（DP-4）
- 派生集合用 SELECT DISTINCT ... WHERE <域谓词>，不建全量字典端点（DM-03）
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from .db import meta_dict
from .domain import (
    DomainContext,
    domain_predicate,
    filter_predicate,
    parse_sort,
    validate_domain,
)

# 对外可见列：指标一律取 DQ 视图列 *_v，原始越界值绝不外泄。
STORE_SELECT = """
SELECT s.store_id, s.name, s.brand, s.region, s.province, s.city, s.block,
       s.lng_gcj02, s.lat_gcj02, s.operate_type, s.status,
       s.rooms_v AS rooms, s.occ_v AS occ, s.adr_v AS adr, s.revpar_v AS revpar,
       s.data_version, s.year
"""

DISTINCT_COLUMNS = frozenset({"province", "city", "block", "brand", "region"})


def _placeholders(prefix: str, values: Sequence[Any], params: dict[str, Any]) -> str:
    names = []
    for i, v in enumerate(values):
        name = f"{prefix}_{i}"
        params[name] = v
        names.append(f":{name}")
    return ", ".join(names) if names else "NULL"


class Repository:
    def __init__(self, conn: Any, ctx: DomainContext, settings: Any):
        if not isinstance(ctx, DomainContext):
            raise TypeError("Repository 必须由服务端 DomainContext 构造")
        validate_domain(ctx)
        self.conn = conn
        self.ctx = ctx
        self.settings = settings
        self._domain_sql, self._domain_params = domain_predicate(ctx, alias="s")

    # ---------- 唯一裁决点 ----------
    def where(self, filters: Mapping[str, str] | None = None, extra: str | None = None) -> tuple[str, dict[str, Any]]:
        """恒含域谓词；筛选只允许 AND 收窄。"""
        f_sql, f_params = filter_predicate(filters or {}, alias="s")
        params: dict[str, Any] = dict(self._domain_params)
        params.update(f_params)
        clause = f"({self._domain_sql}) AND ({f_sql})"
        if extra:
            clause += f" AND ({extra})"
        return clause, params

    def _query(self, sql: str, params: Mapping[str, Any]) -> list[Any]:
        return list(self.conn.execute(sql, dict(params)).fetchall())

    # ---------- 台账 ----------
    def count_stores(self, filters: Mapping[str, str] | None = None) -> int:
        where, params = self.where(filters)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM v_ledger s WHERE {where}", params
        ).fetchone()
        return int(row["c"])

    def list_stores(
        self,
        filters: Mapping[str, str] | None,
        sort: str | None,
        order: str | None,
        page: int,
        page_size: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        where, params = self.where(filters)
        total = self.count_stores(filters)
        sort_col, direction = parse_sort(sort, order)
        # 稳定排序 tiebreaker：store_id
        sql = (
            f"{STORE_SELECT} FROM v_ledger s WHERE {where} "
            f"ORDER BY s.{sort_col} {direction}, s.store_id ASC "
            f"LIMIT :lim OFFSET :off"
        )
        p = dict(params)
        p["lim"] = page_size
        p["off"] = (page - 1) * page_size
        rows = [dict(r) for r in self._query(sql, p)]
        return total, rows

    def get_store(self, store_id: str) -> dict[str, Any] | None:
        """域谓词与 id 同在 WHERE；查不到（不存在 / 域外）统一返回 None，防枚举。"""
        where, params = self.where({"store_id": store_id})
        row = self.conn.execute(
            f"{STORE_SELECT} FROM v_ledger s WHERE {where}", params
        ).fetchone()
        return dict(row) if row else None

    def get_yearly(self, store_id: str) -> list[dict[str, Any]]:
        """逐年经营：EXISTS 内复用同一个域谓词，域外 id 返回空。"""
        exists = (
            "EXISTS (SELECT 1 FROM v_ledger s WHERE s.store_id = y.store_id "
            f"AND ({self._domain_sql}))"
        )
        params = dict(self._domain_params)
        params["sid"] = store_id
        rows = self.conn.execute(
            "SELECT y.store_id, y.year, y.available_room_nights, y.sold_room_nights, "
            "y.rooms, y.occ, y.adr, y.revpar FROM store_yearly y "
            f"WHERE y.store_id = :sid AND {exists} ORDER BY y.year ASC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 派生集合（DM-03） ----------
    def distinct_values(self, column: str, filters: Mapping[str, str] | None = None) -> list[str]:
        if column not in DISTINCT_COLUMNS:
            raise ValueError("非法派生列")
        where, params = self.where(filters)
        rows = self.conn.execute(
            f"SELECT DISTINCT s.{column} AS v FROM v_ledger s "
            f"WHERE {where} AND s.{column} IS NOT NULL AND s.{column} <> '' "
            f"ORDER BY s.{column} ASC",
            params,
        ).fetchall()
        return [str(r["v"]) for r in rows]

    def viewport(self, filters: Mapping[str, str] | None = None) -> dict[str, Any]:
        where, params = self.where(filters)
        row = self.conn.execute(
            "SELECT MIN(s.lng_gcj02) AS min_lng, MIN(s.lat_gcj02) AS min_lat, "
            f"MAX(s.lng_gcj02) AS max_lng, MAX(s.lat_gcj02) AS max_lat "
            f"FROM v_ledger s WHERE {where}",
            params,
        ).fetchone()
        return {
            "min_lng": row["min_lng"],
            "min_lat": row["min_lat"],
            "max_lng": row["max_lng"],
            "max_lat": row["max_lat"],
            "coord": "GCJ-02",
        }

    # ---------- 竞品近似（DM-06 / AC-10） ----------
    def competitor_count(self) -> dict[str, Any]:
        if self.ctx.role == "HQ":
            count = int(self.conn.execute("SELECT COUNT(*) AS c FROM competitors").fetchone()["c"])
            return {
                "count": count,
                "is_approximate": False,
                "method": "exact",
                "note": "总部为全量精确计数",
            }
        provinces = self.distinct_values("province")
        params: dict[str, Any] = {}
        ph = _placeholders("cp", provinces, params)
        sql = f"SELECT COUNT(*) AS c FROM competitors WHERE province IN ({ph})"
        count = int(self.conn.execute(sql, params).fetchone()["c"])
        return {
            "count": count,
            "is_approximate": True,
            "method": "province_mapping",
            "note": self.settings.competitor_approx_note,
            "province_basis": len(provinces),
        }

    # ---------- KPI 聚合（DQ-03~05） ----------
    def kpi(self, filters: Mapping[str, str] | None) -> dict[str, Any]:
        where, params = self.where(filters)
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN s.operate_type='直营' THEN 1 ELSE 0 END) AS direct, "
            "SUM(CASE WHEN s.operate_type='加盟' THEN 1 ELSE 0 END) AS franchise, "
            "COUNT(DISTINCT s.city) AS cities, "
            "COUNT(DISTINCT s.province) AS provinces, "
            "COUNT(s.rooms_v) AS rooms_valid, COUNT(s.occ_v) AS occ_valid, "
            "COUNT(s.adr_v) AS adr_valid, COUNT(s.revpar_v) AS revpar_valid "
            f"FROM v_ledger s WHERE {where}",
            params,
        ).fetchone()
        total = int(row["total"] or 0)
        direct = int(row["direct"] or 0)
        franchise = int(row["franchise"] or 0)

        # DQ-03：中位数剔除非正值与越界值（视图已置空），并显示有效样本数
        rows = self.conn.execute(
            f"SELECT s.revpar_v AS v FROM v_ledger s WHERE {where} "
            "AND s.revpar_v IS NOT NULL AND s.revpar_v > 0 ORDER BY s.revpar_v ASC",
            params,
        ).fetchall()
        vals = [float(r["v"]) for r in rows]
        median = _median(vals)

        # DQ-04 多店加权：OCC/RevPAR 按可售房晚、ADR 按售出房晚；
        # 权重来自 store_yearly（年度口径），指标取 v_ledger 的 DQ 视图列。
        weighted = self._weighted(where, params)

        denominator = total
        return {
            "store_count": total,
            "direct_count": direct,
            "franchise_count": franchise,
            "city_count": int(row["cities"] or 0),
            "province_count": int(row["provinces"] or 0),
            "revpar_median": median,
            "revpar_valid_sample_count": len(vals),
            "weighted": weighted,
            "metric_coverage": {
                "rooms": _ratio(int(row["rooms_valid"] or 0), denominator),
                "occ": _ratio(int(row["occ_valid"] or 0), denominator),
                "adr": _ratio(int(row["adr_valid"] or 0), denominator),
                "revpar": _ratio(int(row["revpar_valid"] or 0), denominator),
            },
            "denominator_scope": "当前口径",
            "denominator": denominator,
        }

    def _weighted(self, where: str, params: Mapping[str, Any]) -> dict[str, Any]:
        year = 2026
        b = {"rooms": 3000.0, "occ": 1.2, "adr": 5000.0, "revpar": 3000.0}

        def safe(col: str, hi: float) -> str:
            return f"CASE WHEN y.{col} > 0 AND y.{col} <= {hi} THEN y.{col} END"

        p = dict(params)
        p["w_year"] = year
        sql = (
            "SELECT "
            "SUM(CASE WHEN s.occ_v IS NOT NULL AND y.available_room_nights > 0 "
            "     THEN s.occ_v * y.available_room_nights END) / "
            "NULLIF(SUM(CASE WHEN s.occ_v IS NOT NULL AND y.available_room_nights > 0 "
            "     THEN y.available_room_nights END), 0) AS occ_w, "
            "SUM(CASE WHEN s.adr_v IS NOT NULL AND y.sold_room_nights > 0 "
            "     THEN s.adr_v * y.sold_room_nights END) / "
            "NULLIF(SUM(CASE WHEN s.adr_v IS NOT NULL AND y.sold_room_nights > 0 "
            "     THEN y.sold_room_nights END), 0) AS adr_w, "
            "SUM(CASE WHEN s.revpar_v IS NOT NULL AND y.available_room_nights > 0 "
            "     THEN s.revpar_v * y.available_room_nights END) / "
            "NULLIF(SUM(CASE WHEN s.revpar_v IS NOT NULL AND y.available_room_nights > 0 "
            "     THEN y.available_room_nights END), 0) AS revpar_w "
            f"FROM v_ledger s JOIN store_yearly y ON y.store_id = s.store_id AND y.year = :w_year "
            f"WHERE {where}"
        )
        r = self.conn.execute(sql, p).fetchone()
        return {
            "occ": r["occ_w"],
            "adr": r["adr_w"],
            "revpar": r["revpar_w"],
            "weight_basis": {"occ": "可售房晚", "adr": "售出房晚", "revpar": "可售房晚"},
            "year": year,
            "dq_bounds_applied": b,
        }

    # ---------- 导出 ----------
    def export_count(
        self, filters: Mapping[str, str] | None, store_ids: Sequence[str] | None
    ) -> int:
        extra, ep = self._store_id_clause(store_ids)
        where, params = self.where(filters, extra)
        params.update(ep)
        return int(
            self.conn.execute(
                f"SELECT COUNT(*) AS c FROM v_ledger s WHERE {where}", params
            ).fetchone()["c"]
        )

    def validate_store_ids(self, store_ids: Sequence[str]) -> list[str]:
        """返回落在域内的 id 子集；调用方据此判断是否有越界（拒绝整单）。"""
        if not store_ids:
            return []
        found: set[str] = set()
        # 分批，避免超长 IN；每批使用独立参数字典，避免残留绑定名
        for start in range(0, len(store_ids), 800):
            chunk = list(store_ids[start : start + 800])
            params: dict[str, Any] = dict(self._domain_params)
            ph = _placeholders("sid", chunk, params)
            sql = (
                f"SELECT s.store_id FROM v_ledger s WHERE ({self._domain_sql}) "
                f"AND s.store_id IN ({ph})"
            )
            found.update(str(r["store_id"]) for r in self.conn.execute(sql, params).fetchall())
        return [sid for sid in store_ids if sid in found]

    def export_rows(
        self,
        filters: Mapping[str, str] | None,
        store_ids: Sequence[str] | None,
        sort: str | None,
        order: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        extra, ep = self._store_id_clause(store_ids)
        where, params = self.where(filters, extra)
        params.update(ep)
        sort_col, direction = parse_sort(sort, order)
        sql = (
            f"{STORE_SELECT} FROM v_ledger s WHERE {where} "
            f"ORDER BY s.{sort_col} {direction}, s.store_id ASC LIMIT :lim"
        )
        p = dict(params)
        p["lim"] = limit
        return [dict(r) for r in self._query(sql, p)]

    def _store_id_clause(self, store_ids: Sequence[str] | None) -> tuple[str | None, dict[str, Any]]:
        # None = 未显式选行（用当前口径全部行）；[] = 显式空选行 -> 空集合，
        # 绝不回退成「导出全部」（防止语义放宽）。
        if store_ids is None:
            return None, {}
        if len(store_ids) == 0:
            return "1=0", {}
        params: dict[str, Any] = {}
        ph = _placeholders("xid", list(store_ids), params)
        return f"s.store_id IN ({ph})", params

    # ---------- 元数据 ----------
    def meta(self) -> dict[str, str]:
        return meta_dict(self.conn)


def _median(sorted_vals: Sequence[float]) -> float | None:
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 6)
