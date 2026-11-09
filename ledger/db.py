"""数据库：DDL、统一 DQ 视图 v_ledger、连接管理。

design.md §2.3 的 DDL 草案在 SQLite 上的落地：
- BIGSERIAL -> INTEGER PRIMARY KEY AUTOINCREMENT，TIMESTAMP -> TEXT(ISO8601)
- v_ledger 是所有读接口的唯一数据源（DQ-01 越界置空 + DQ-02 死店剔除）
- 竞品表刻意不含 region 字段（DM-06）
- region_dict 带 ordinal，显式复刻「7 值字典索引 0/5 为品牌值」的陷阱，
  域裁决只按 name + kind='GEO' 取（DM-07），绝不用 ordinal 位置。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  user_id       TEXT PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name  TEXT,
  role          TEXT NOT NULL,
  region_scope  TEXT,
  brand_scope   TEXT,
  role_version  INTEGER NOT NULL DEFAULT 1,
  status        TEXT NOT NULL DEFAULT 'ACTIVE',
  is_admin      INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL,
  CHECK ( (role='HQ'       AND region_scope IS NULL     AND brand_scope IS NULL)
       OR (role='REGION'   AND region_scope IS NOT NULL AND brand_scope IS NULL)
       OR (role='BRAND_BU' AND region_scope IS NULL     AND brand_scope IS NOT NULL) )
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash      TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL REFERENCES users(user_id),
  role_snapshot   TEXT NOT NULL,
  domain_snapshot TEXT NOT NULL,
  role_version    INTEGER NOT NULL,
  issued_at       TEXT NOT NULL,
  expires_at      TEXT NOT NULL,
  revoked         INTEGER NOT NULL DEFAULT 0,
  last_seen_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS stores (
  store_id      TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  brand         TEXT,
  region        TEXT,
  province      TEXT,
  city          TEXT,
  block         TEXT,
  lng_gcj02     REAL,
  lat_gcj02     REAL,
  operate_type  TEXT,
  status        TEXT,
  rooms         REAL,
  occ           REAL,
  adr           REAL,
  revpar        REAL,
  is_dead       INTEGER NOT NULL DEFAULT 0,
  data_version  TEXT NOT NULL,
  year          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_stores_region ON stores(region);
CREATE INDEX IF NOT EXISTS idx_stores_brand  ON stores(brand);
CREATE INDEX IF NOT EXISTS idx_stores_prov   ON stores(province, city);
CREATE INDEX IF NOT EXISTS idx_stores_scope  ON stores(is_dead, region, brand, province);

CREATE TABLE IF NOT EXISTS store_yearly (
  store_id              TEXT NOT NULL REFERENCES stores(store_id) ON UPDATE CASCADE,
  year                  INTEGER NOT NULL,
  available_room_nights REAL,
  sold_room_nights      REAL,
  rooms                 REAL,
  occ                   REAL,
  adr                   REAL,
  revpar                REAL,
  PRIMARY KEY (store_id, year)
);

-- 竞品表刻意不含 region 字段（DM-06 / AC-10）
CREATE TABLE IF NOT EXISTS competitors (
  competitor_id TEXT PRIMARY KEY,
  province      TEXT,
  city          TEXT,
  brand         TEXT,
  name          TEXT
);
CREATE INDEX IF NOT EXISTS idx_comp_prov ON competitors(province);

-- 7 值字典；ordinal 复刻原型索引位置，仅用于校验/清单，绝不用于域匹配
CREATE TABLE IF NOT EXISTS region_dict (
  name    TEXT PRIMARY KEY,
  kind    TEXT NOT NULL,       -- 'GEO' | 'BRAND_VALUE'
  ordinal INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type       TEXT NOT NULL,
  actor_user_id    TEXT,
  actor_role       TEXT,
  target_object    TEXT,
  filter_signature TEXT,
  row_count        INTEGER,
  reason_code      TEXT,
  result           TEXT,
  detail_json      TEXT,
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_time_type ON audit_log(created_at, event_type);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# DQ-01 双保险：即使导入物化遗漏，视图层再次置空；DQ-02 死店在此统一剔除。
# 注意 *_v 才是可对外口径；原始 rooms/occ/adr/revpar 不直接暴露（越界值不得外泄）。
VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_ledger AS
SELECT s.*,
       CASE WHEN s.rooms  IS NOT NULL AND s.rooms  > 0 AND s.rooms  <= 3000 THEN s.rooms  END AS rooms_v,
       CASE WHEN s.occ    IS NOT NULL AND s.occ    > 0 AND s.occ    <= 1.2   THEN s.occ    END AS occ_v,
       CASE WHEN s.adr    IS NOT NULL AND s.adr    > 0 AND s.adr    <= 5000  THEN s.adr    END AS adr_v,
       CASE WHEN s.revpar IS NOT NULL AND s.revpar > 0 AND s.revpar <= 3000  THEN s.revpar END AS revpar_v
FROM stores s
WHERE s.is_dead = 0;
"""

# region 字典：索引 0 是品牌名、索引 5 是品牌 BU，其余五个才是地域大区。
# 精确串为任务书转录，待真实底表核对（OPEN-07）。
REGION_DICT_ROWS: list[tuple[str, str, int]] = [
    ("丽芮品牌", "BRAND_VALUE", 0),
    ("华东", "GEO", 1),
    ("华南", "GEO", 2),
    ("华北", "GEO", 3),
    ("华西", "GEO", 4),
    ("欢朋品牌BU", "BRAND_VALUE", 5),
    ("山河", "GEO", 6),
]

GEO_NAMES_BY_KIND_SQL = "SELECT name FROM region_dict WHERE kind='GEO' ORDER BY ordinal"

META_ROWS: list[tuple[str, str]] = [
    ("data_version", "2026YTD08"),
    ("as_of_date", "2026-08-31"),
    ("ytd_start", "2026-01"),
    ("ytd_end", "2026-08"),
    ("seasonality_note", "与完整年比较需注意季节性"),
    ("competitor_method", "province_mapping"),
    ("competitor_approx_note",
     "竞品表无 region 字段，区域视角竞品数按域内省份映射推导，属近似口径；"
     "内蒙古等双列省份在两个大区均会命中，存在固有重复/误差。"),
    ("coord", "GCJ-02"),
]


def connect(db_path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.executescript(VIEW_SQL)
    conn.executemany(
        "INSERT OR IGNORE INTO region_dict(name, kind, ordinal) VALUES (?,?,?)",
        REGION_DICT_ROWS,
    )
    conn.executemany("INSERT OR IGNORE INTO meta(key, value) VALUES (?,?)", META_ROWS)
    conn.commit()


def scalar(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Any:
    row = conn.execute(sql, tuple(params)).fetchone()
    return None if row is None else row[0]


def meta_dict(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
