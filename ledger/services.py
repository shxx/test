"""应用服务层：审计 / 管理端 / 域元数据 / 台账 / KPI / 导出。"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .domain import DomainContext, normalize_signature, parse_paging, parse_filters, parse_sort
from .errors import ApiError
from .repository import Repository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditService:
    """追加写审计；拒绝类行为同样落库。测试可用 fail_on_write 注入写失败。"""

    def __init__(self, conn: Any, settings: Any):
        self.conn = conn
        self.settings = settings
        self.fail_on_write = False

    def record(
        self,
        event_type: str,
        ctx: DomainContext | None,
        *,
        target_object: str | None = None,
        filter_signature: str | None = None,
        row_count: int | None = None,
        reason_code: str | None = None,
        result: str = "SUCCESS",
        detail: Any = None,
        commit: bool = True,
    ) -> int:
        if self.fail_on_write:
            raise RuntimeError("injected audit write failure")
        cur = self.conn.execute(
            "INSERT INTO audit_log(event_type, actor_user_id, actor_role, target_object, "
            "filter_signature, row_count, reason_code, result, detail_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                event_type,
                ctx.user_id if ctx else None,
                ctx.role if ctx else None,
                target_object,
                filter_signature,
                row_count,
                reason_code,
                result,
                json.dumps(detail, ensure_ascii=False, sort_keys=True) if detail is not None else None,
                _now_iso(),
            ),
        )
        if commit:
            self.conn.commit()
        return int(cur.lastrowid)

    def mark_success(self, audit_id: int, commit: bool = True) -> None:
        self.conn.execute(
            "UPDATE audit_log SET result='SUCCESS' WHERE id = ?", (audit_id,)
        )
        if commit:
            self.conn.commit()

    def query(self, filters: Mapping[str, str], page: int, page_size: int) -> tuple[int, list[dict[str, Any]]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if filters.get("event_type"):
            clauses.append("event_type = :ev")
            params["ev"] = filters["event_type"]
        if filters.get("from"):
            clauses.append("created_at >= :frm")
            params["frm"] = filters["from"]
        if filters.get("to"):
            clauses.append("created_at <= :to")
            params["to"] = filters["to"]
        where = " AND ".join(clauses) if clauses else "1=1"
        total = int(self.conn.execute(f"SELECT COUNT(*) c FROM audit_log WHERE {where}", params).fetchone()["c"])
        p = dict(params)
        p["lim"] = page_size
        p["off"] = (page - 1) * page_size
        rows = self.conn.execute(
            "SELECT * FROM audit_log WHERE " + where +
            " ORDER BY id DESC LIMIT :lim OFFSET :off",
            p,
        ).fetchall()
        return total, [dict(r) for r in rows]


class AdminService:
    """角色变更（AC-08）与受控审计查询（IF-8 / IF-9 / OPEN-16）。"""

    def __init__(self, conn: Any, settings: Any, audit: AuditService):
        self.conn = conn
        self.settings = settings
        self.audit = audit

    @staticmethod
    def require_admin(ctx: DomainContext) -> None:
        if not ctx.is_admin:
            raise ApiError("ADMIN_FORBIDDEN")

    def change_role(
        self, ctx: DomainContext, target_user_id: str, role: str, scope: str | None
    ) -> dict[str, Any]:
        self.require_admin(ctx)
        if role not in ("HQ", "REGION", "BRAND_BU"):
            raise ApiError("INVALID_FILTER", "非法角色")
        if role == "REGION" and (not scope or scope not in ctx.geo_whitelist):
            raise ApiError("INVALID_FILTER", "非法大区域值")
        if role == "BRAND_BU" and (not scope or scope not in ctx.brand_whitelist):
            raise ApiError("INVALID_FILTER", "非法品牌域值")
        if role == "HQ":
            scope = None

        user = self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (target_user_id,)
        ).fetchone()
        if user is None:
            raise ApiError("NOT_FOUND", "用户不存在")

        region_scope = scope if role == "REGION" else None
        brand_scope = scope if role == "BRAND_BU" else None
        old = {
            "role": user["role"],
            "region_scope": user["region_scope"],
            "brand_scope": user["brand_scope"],
            "role_version": int(user["role_version"]),
        }
        # 乐观并发：带旧 role_version 条件
        cur = self.conn.execute(
            "UPDATE users SET role=?, region_scope=?, brand_scope=?, "
            "role_version = role_version + 1, updated_at=? "
            "WHERE user_id=? AND role_version=?",
            (role, region_scope, brand_scope, _now_iso(), target_user_id, old["role_version"]),
        )
        if cur.rowcount != 1:
            self.conn.rollback()
            raise ApiError("INVALID_FILTER", "角色版本并发冲突，请重试")
        # 不主动吊销会话：由每请求 role_version 实时比对产生
        # 401 ROLE_CHANGED_RELOGIN（AC-08 契约码）。会话保留可用于审计排查。
        new_version = old["role_version"] + 1
        self.audit.record(
            "ROLE_CHANGE", ctx,
            target_object=target_user_id,
            result="SUCCESS",
            detail={
                "operator": ctx.user_id,
                "target": target_user_id,
                "changed_at": _now_iso(),
                "before": old,
                "after": {"role": role, "region_scope": region_scope,
                          "brand_scope": brand_scope, "role_version": new_version},
            },
            commit=False,
        )
        self.conn.commit()
        return {"user_id": target_user_id, "role": role, "scope": scope,
                "role_version": new_version}

    def audit_query(
        self, ctx: DomainContext, raw: Mapping[str, Any]
    ) -> dict[str, Any]:
        self.require_admin(ctx)
        if self.settings.audit_query_permission != "admin":
            raise ApiError("ADMIN_FORBIDDEN", "审计查询权限未开放（OPEN-06）")
        allowed = {"event_type", "from", "to", "page", "page_size"}
        filters = {k: str(v) for k, v in raw.items() if k in allowed and v not in (None, "")}
        for k in raw:
            if k not in allowed:
                raise ApiError("INVALID_FILTER", f"未知审计查询字段: {k}")
        page, page_size = parse_paging(raw.get("page"), raw.get("page_size"), self.settings)
        total, rows = self.audit.query(filters, page, page_size)
        return {"total": total, "page": page, "page_size": page_size, "items": rows}


class MetaService:
    """IF-3 域元数据：requirement.md §3.3 握手清单字段级落地。"""

    def __init__(self, repo: Repository, settings: Any):
        self.repo = repo
        self.settings = settings

    def build(self, ctx: DomainContext, filters: Mapping[str, str] | None = None) -> dict[str, Any]:
        meta = self.repo.meta()
        locked_region = ctx.role == "REGION"
        dimensions = {
            "region": {
                "locked": locked_region,
                "label": "已锁定" if locked_region else "可选",
                **({"fixed_value": ctx.scope} if locked_region else {}),
            },
            "brand": {"locked": False, "label": "可选"},
        }
        return {
            **ctx.identity(),
            "provinces": self.repo.distinct_values("province"),
            "cities": self.repo.distinct_values("city"),
            "blocks": self.repo.distinct_values("block"),
            "dimensions": dimensions,
            "default_viewport": self.repo.viewport(),
            "competitor": self.repo.competitor_count(),
            "data_version": meta.get("data_version", self.settings.data_version),
            "as_of_date": meta.get("as_of_date", self.settings.as_of_date),
            "ytd": {
                "start": meta.get("ytd_start", self.settings.ytd_start),
                "end": meta.get("ytd_end", self.settings.ytd_end),
                "note": meta.get("seasonality_note", self.settings.seasonality_note),
            },
            "metric_notes": {
                "revpar_median": "剔除非正值与越界值；有效样本数随 KPI 响应下发",
                "weighting": {"occ": "可售房晚", "adr": "售出房晚", "revpar": "可售房晚"},
                "coverage_denominator": "当前口径",
                "coord": meta.get("coord", "GCJ-02"),
            },
        }


class LedgerService:
    def __init__(self, repo: Repository, settings: Any, audit: AuditService):
        self.repo = repo
        self.settings = settings
        self.audit = audit

    def list_stores(self, ctx: DomainContext, raw: Mapping[str, Any]) -> dict[str, Any]:
        filters, ignored, locked_ignored, notes = parse_filters(
            ctx, raw, allow=("page", "page_size", "sort", "order")
        )
        page, page_size = parse_paging(raw.get("page"), raw.get("page_size"), self.settings)
        sort, order = raw.get("sort"), raw.get("order")
        parse_sort(sort, order)  # 提前校验，未知排序列 400
        total, items = self.repo.list_stores(filters, sort, order, page, page_size)
        return {
            "total": total, "page": page, "page_size": page_size,
            "sort": sort or "store_id", "order": (order or "asc").lower(),
            "items": items,
            "scope": self._scope(ctx, filters, ignored, locked_ignored, notes),
        }

    def detail(self, ctx: DomainContext, store_id: str) -> dict[str, Any]:
        store = self.repo.get_store(store_id)
        if store is None:
            # 「不存在」与「域外」统一 403，不回显任何字段，且留痕（AC-06 / DP-8）
            self.audit.record(
                "OVERSCOPE_ATTEMPT", ctx,
                target_object=store_id, result="REJECTED", reason_code="OUT_OF_DOMAIN",
                detail={"endpoint": "GET /api/v1/stores/{id}", "requested_id": store_id},
            )
            raise ApiError("OUT_OF_DOMAIN")
        return {"store": store, "yearly": self.repo.get_yearly(store_id),
                "scope": self._scope(ctx, {}, (), (), ())}

    def _scope(self, ctx, filters, ignored, locked_ignored, notes) -> dict[str, Any]:
        return {
            "domain": ctx.domain_dict(),
            "filters_applied": dict(filters),
            "filter_signature": normalize_signature(ctx, filters, self.settings.data_version),
            "ignored_client_params": list(ignored),
            "locked_dimension_ignored": list(locked_ignored),
            "notes": list(notes),
        }


class KpiService:
    def __init__(self, repo: Repository, settings: Any):
        self.repo = repo
        self.settings = settings

    def compute(self, ctx: DomainContext, raw: Mapping[str, Any]) -> dict[str, Any]:
        filters, ignored, locked_ignored, notes = parse_filters(
            ctx, raw, allow=("sort", "order")
        )
        parse_sort(raw.get("sort"), raw.get("order"))
        kpi = self.repo.kpi(filters)
        return {
            **kpi,
            "competitor": self.repo.competitor_count(),
            "domain": ctx.domain_dict(),
            "filters_applied": dict(filters),
            "filter_signature": normalize_signature(ctx, filters, self.settings.data_version),
            "ignored_client_params": list(ignored),
            "locked_dimension_ignored": list(locked_ignored),
            "notes": list(notes),
            "data_version": self.settings.data_version,
            "as_of_date": self.settings.as_of_date,
            "ytd": {"start": self.settings.ytd_start, "end": self.settings.ytd_end,
                    "note": self.settings.seasonality_note},
        }


class ExportService:
    """FR-04 / ADR-6：先 COUNT 再决定；审计预写事务；超限/越界不产文件。"""

    CSV_HEADER = [
        "store_id", "name", "brand", "region", "province", "city", "block",
        "lng_gcj02", "lat_gcj02", "operate_type", "status",
        "rooms", "occ", "adr", "revpar", "data_version", "year",
        "__export_role", "__exported_at",
    ]
    METRIC_COLS = frozenset({"rooms", "occ", "adr", "revpar"})

    def __init__(self, repo: Repository, settings: Any, audit: AuditService):
        self.repo = repo
        self.settings = settings
        self.audit = audit

    def run(
        self,
        ctx: DomainContext,
        raw: Mapping[str, Any],
    ) -> tuple[str, bytes, int, str]:
        filters, ignored, locked_ignored, notes = parse_filters(
            ctx, raw.get("filters") or {}, allow=()
        )
        sort, order = raw.get("sort"), raw.get("order")
        parse_sort(sort, order)
        store_ids = raw.get("store_ids")
        if store_ids is not None:
            if not isinstance(store_ids, list) or any(not isinstance(i, str) for i in store_ids):
                raise ApiError("INVALID_FILTER", "store_ids 必须为字符串数组")

        signature = normalize_signature(
            ctx, filters, self.settings.data_version,
            extra={"store_ids": sorted(store_ids)} if store_ids is not None else None,
        )

        if not self.settings.export_enabled:
            self.audit.record(
                "EXPORT_REJECTED", ctx, filter_signature=signature,
                reason_code="EXPORT_DISABLED", result="REJECTED",
                detail={"filters": filters, "notes": list(notes)},
            )
            raise ApiError("EXPORT_DISABLED")

        # ② store_ids 逐个校验：任一越界 -> 拒绝整单，不跳过越界行
        if store_ids is not None:
            in_domain = set(self.repo.validate_store_ids(store_ids))
            outs = [sid for sid in store_ids if sid not in in_domain]
            if outs:
                self.audit.record(
                    "OVERSCOPE_ATTEMPT", ctx,
                    target_object=json.dumps(outs[:10], ensure_ascii=False),
                    filter_signature=signature, reason_code="EXPORT_OUT_OF_DOMAIN",
                    result="REJECTED", detail={"out_of_domain_ids": outs[:10]},
                )
                self.audit.record(
                    "EXPORT_REJECTED", ctx, filter_signature=signature,
                    reason_code="EXPORT_OUT_OF_DOMAIN", result="REJECTED",
                    detail={"filters": filters, "out_of_domain_count": len(outs)},
                )
                raise ApiError("EXPORT_OUT_OF_DOMAIN")

        # ① 与台账同源的 COUNT（数据行，不含表头/水印行）
        c_total = self.repo.export_count(filters, store_ids)

        # ③ 超限拒绝，不产出文件
        if c_total > self.settings.export_row_limit:
            self.audit.record(
                "EXPORT_REJECTED", ctx, filter_signature=signature, row_count=c_total,
                reason_code="EXPORT_LIMIT_EXCEEDED", result="REJECTED",
                detail={"filters": filters, "limit": self.settings.export_row_limit},
            )
            raise ApiError("EXPORT_LIMIT_EXCEEDED")

        # ⑤ 审计预写事务：写失败即回滚、不放行导出（NFR-03）
        try:
            self.repo.conn.execute("BEGIN IMMEDIATE")
            audit_id = self.audit.record(
                "EXPORT_SUCCESS", ctx, filter_signature=signature, row_count=c_total,
                result="PENDING", detail={"filters": filters}, commit=False,
            )
            rows = self.repo.export_rows(filters, store_ids, sort, order, c_total)
            filename, content = self._csv(ctx, rows)
            self.audit.mark_success(audit_id, commit=False)
            self.repo.conn.commit()
        except Exception:
            self.repo.conn.rollback()
            raise
        return filename, content, c_total, signature

    def _csv(self, ctx: DomainContext, rows: Sequence[dict[str, Any]]) -> tuple[str, bytes]:
        exported_at = _now_iso()
        role_label = f"{ctx.label}:{ctx.scope or ctx.label}"
        meta = self.repo.meta()
        domain_name = ctx.scope or "全量"
        date_str = datetime.now(timezone.utc).strftime(self.settings.export_filename_date_format)
        filename = f"门店网络台账_{domain_name}_{date_str}.csv"

        buf = io.StringIO(newline="")
        w = csv.writer(buf, lineterminator="\r\n")
        # 水印：首行注释 + 每行冗余列（防裁剪丢水印）
        w.writerow([f"# 角色:{role_label} 导出时间:{exported_at} "
                    f"数据版本:{meta.get('data_version', self.settings.data_version)}"])
        w.writerow(self.CSV_HEADER)
        for r in rows:
            cells: list[Any] = []
            for col in self.CSV_HEADER:
                if col == "__export_role":
                    cells.append(role_label)
                elif col == "__exported_at":
                    cells.append(exported_at)
                elif col in self.METRIC_COLS and self.settings.redact_metrics:
                    cells.append("")  # NFR-05 脱敏展示版：指标置空
                else:
                    v = r.get(col)
                    cells.append("" if v is None else v)
            w.writerow([self._guard_injection(c) for c in cells])
        # UTF-8 BOM
        return filename, b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")

    @staticmethod
    def _guard_injection(value: Any) -> Any:
        if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
            return "'" + value
        return value
