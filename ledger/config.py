"""运行时配置。

全部取值均为 design.md §2.6 / OPEN 项的「设计默认值」，不是业务已确认结论：
- 会话 TTL / 空闲 TTL、分页上限、导出上限、脱敏开关、审计保留期与查询权限
  均为配置位，可通过环境变量覆盖；未预设具体审计天数（OPEN-06）。
- 「内网 / 对外」的判定依据未定义（OPEN-08），此处只预留两个配置位，
  不实现自动切换。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # 存储
    db_path: str = field(default_factory=lambda: os.environ.get("LEDGER_DB_PATH", "ledger.db"))

    # 会话（§2.4.1，运维参数，非需求结论）
    session_ttl_seconds: int = field(default_factory=lambda: _env_int("LEDGER_SESSION_TTL", 8 * 3600))
    idle_ttl_seconds: int = field(default_factory=lambda: _env_int("LEDGER_IDLE_TTL", 2 * 3600))
    token_bytes: int = 32
    pbkdf2_iterations: int = field(default_factory=lambda: _env_int("LEDGER_PBKDF2_ITER", 120_000))

    # 分页（§2.6：默认 50 / 上限 200 / 稳定排序 tiebreaker store_id）
    page_size_default: int = 50
    page_size_max: int = 200

    # 导出（FR-04 / OPEN-11 设计默认值：按数据行计，不含表头/水印行）
    export_row_limit: int = 5000
    export_filename_date_format: str = "%Y%m%d"

    # 脱敏与数据出域（NFR-05 / OPEN-08）：只预留配置位与拦截点
    redact_metrics: bool = field(default_factory=lambda: _env_bool("LEDGER_REDACT_METRICS", False))
    export_enabled: bool = field(default_factory=lambda: _env_bool("LEDGER_EXPORT_ENABLED", True))

    # 审计（OPEN-06）：不预设保留天数；查询权限为运维配置
    audit_retention_days: int | None = field(
        default_factory=lambda: (_env_int("LEDGER_AUDIT_RETENTION_DAYS", 0) or None)
    )
    audit_query_permission: str = field(
        default_factory=lambda: os.environ.get("LEDGER_AUDIT_QUERY_PERMISSION", "admin")
    )

    # 口径元数据（由接口下发；数字均为占位/任务书转录口径，待真实底表核对）
    data_version: str = "2026YTD08"
    as_of_date: str = "2026-08-31"
    ytd_start: str = "2026-01"
    ytd_end: str = "2026-08"
    seasonality_note: str = "与完整年比较需注意季节性"
    competitor_method: str = "province_mapping"
    competitor_approx_note: str = (
        "竞品表无 region 字段，区域视角竞品数按域内省份映射推导，属近似口径；"
        "内蒙古等双列省份在两个大区均会命中，存在固有重复/误差，不可当作精确值消费。"
    )

    # 500 路径是否打印堆栈到 stderr（生产排障用；故障注入测试可关闭以保持输出干净）
    log_tracebacks: bool = field(default_factory=lambda: _env_bool("LEDGER_LOG_TRACEBACKS", True))

    # DQ-01 边界（左开右闭）；越界置空，不是截断、不是剔除整行
    dq_bounds: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "rooms": (0.0, 3000.0),
            "occ": (0.0, 1.2),
            "adr": (0.0, 5000.0),
            "revpar": (0.0, 3000.0),
        }
    )

    # DQ-01 边界别名：store_yearly 同口径
    # 角色展示名 / 域标签（展示用，不作权限依据）
    role_labels: dict[str, str] = field(
        default_factory=lambda: {
            "HQ": "总部",
            "REGION": "大区",
            "BRAND_BU": "品牌BU",
        }
    )

    def domain_label(self, role: str, scope: str | None) -> str:
        if role == "HQ":
            return "全量"
        return scope or "无域"


# 全局默认配置（进程级）；测试通过构造 Settings 覆盖。
settings = Settings()
