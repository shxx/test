"""数据导入 / DQ 物化 / region 全量校验 / 合成 fixture。

如实声明（OPEN-15）：《门店网络台账 PRD V1.0》、原型 HTML 与 13 258 行真实底表
均未随工作区提供。本模块提供：
  1) 可用的真实 CSV 导入通道（apply_dq_to_row + import_stores_csv），含 DQ 物化；
  2) validate_region() 上线前全量校验，产出「region 为空或非法 / 为品牌值」清单；
  3) build_synthetic_fixture()：**合成** fixture，仅用于在无真实底表时验证
     域裁决逻辑、派生集合规则、接口契约与 DQ 口径。数字取自任务书转录值，
     不代表真实底表已核对（OPEN-14/15），不得当作 AC-01~05 已通过的证据。
"""
from __future__ import annotations

import csv
import json
import os
import random
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .auth import hash_password
from .db import REGION_DICT_ROWS

GEO_REGIONS = {
    "华东": 2767,
    "华南": 2781,
    "华北": 2335,
    "华西": 3005,
    "山河": 1800,
}
BRAND_BU = {"欢朋": 544, "丽芮": 26}
BRAND_REGION_VALUE = {"欢朋": "欢朋品牌BU", "丽芮": "丽芮品牌"}

# 34 个省级单位；华东 6 个、内蒙古在华北/华西双列（AC-09 / DM-05）
PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆", "香港",
    "澳门", "台湾",
]
REGION_PROVINCES = {
    "华东": ["上海", "江苏", "浙江", "安徽", "福建", "江西"],
    "华南": ["广东", "广西", "海南", "湖北", "湖南", "河南"],
    "华北": ["北京", "天津", "河北", "山西", "山东", "内蒙古"],
    "华西": ["重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃",
             "青海", "宁夏", "新疆", "内蒙古"],
    "山河": ["辽宁", "吉林", "黑龙江", "香港", "澳门", "台湾"],
}
# 品牌 BU 跨 20 余省（AC-04）
HUANPENG_PROVINCES = PROVINCES[:22]

# 直营/加盟：合计 429 / 12 829；华东 160 / 2 607
DIRECT_COUNT = {
    "华东": 160, "华南": 60, "华北": 50, "华西": 60, "山河": 50,
    "欢朋": 40, "丽芮": 9,
}

DQ_BOUNDS = {"rooms": (0, 3000), "occ": (0, 1.2), "adr": (0, 5000), "revpar": (0, 3000)}
BLOCKS = ["核心商圈", "次核心商圈", "新兴板块", "交通枢纽", "文旅板块", "社区板块"]


def _cities_by_province() -> dict[str, list[str]]:
    """365 个全局唯一城市名；前 25 省各 11 个，其余 9 省各 10 个。"""
    out: dict[str, list[str]] = {}
    for i, prov in enumerate(PROVINCES):
        n = 11 if i < 25 else 10
        out[prov] = [f"{prov}{j + 1:02d}市" for j in range(n)]
    return out


CITY_POOL = _cities_by_province()
ALL_CITIES = [c for v in CITY_POOL.values() for c in v]
assert len(PROVINCES) == 34 and len(ALL_CITIES) == 365


def apply_dq_to_row(row: dict[str, Any]) -> dict[str, Any]:
    """DQ-01 导入物化：越界指标置空（不是截断、不是剔除整行）。"""
    out = dict(row)
    for col, (lo, hi) in DQ_BOUNDS.items():
        v = out.get(col)
        if v is None or v == "":
            out[col] = None
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            out[col] = None
            continue
        out[col] = f if (lo < f <= hi) else None
    return out


def compute_dead_flags(conn: Any, years: Iterable[int] = (2024, 2025, 2026)) -> int:
    """DQ-02：连续若干年无经营记录且非在营 -> is_dead=1。"""
    years = list(years)
    ph = ",".join("?" for _ in years)
    cur = conn.execute(
        f"UPDATE stores SET is_dead = 1 WHERE COALESCE(status,'') <> '在营' "
        f"AND NOT EXISTS (SELECT 1 FROM store_yearly y WHERE y.store_id = stores.store_id "
        f"AND y.year IN ({ph}))",
        years,
    )
    conn.commit()
    return cur.rowcount


def import_stores_csv(conn: Any, csv_path: str) -> dict[str, Any]:
    """从 CSV 导入底表（列名见 README）。真实底表未提供时不会被调用。"""
    required = {"store_id", "name", "brand", "region", "province", "city"}
    count = 0
    nulled = 0
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少列: {sorted(missing)}")
        buf = []
        for raw in reader:
            row = apply_dq_to_row(raw)
            nulled += sum(1 for c in DQ_BOUNDS if raw.get(c) not in (None, "") and row[c] is None)
            buf.append((
                row["store_id"], row["name"], row.get("brand"), row.get("region"),
                row.get("province"), row.get("city"), row.get("block"),
                _num(row.get("lng_gcj02")), _num(row.get("lat_gcj02")),
                row.get("operate_type"), row.get("status"),
                row.get("rooms"), row.get("occ"), row.get("adr"), row.get("revpar"),
                0, row.get("data_version") or "2026YTD08", _num(row.get("year")) or 2026,
            ))
            count += 1
    conn.executemany(
        "INSERT OR REPLACE INTO stores(store_id,name,brand,region,province,city,block,"
        "lng_gcj02,lat_gcj02,operate_type,status,rooms,occ,adr,revpar,is_dead,data_version,year) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", buf,
    )
    conn.commit()
    dead = compute_dead_flags(conn)
    return {"rows": count, "dq_nulled_values": nulled, "dead_flagged": dead}


def validate_region(conn: Any) -> dict[str, Any]:
    """NFR-08 / OPEN-07 / DM-07：上线前一次性全量校验。

    产出「region 为空或非法」清单与「region 为品牌值」清单，由业务确认归属；
    校验未通过不得上线。按 name + kind 判定，绝不按 ordinal 索引位置。
    """
    geo = {name for name, kind, _ in REGION_DICT_ROWS if kind == "GEO"}
    brand_values = {name for name, kind, _ in REGION_DICT_ROWS if kind == "BRAND_VALUE"}
    rows = conn.execute(
        "SELECT store_id, region FROM stores ORDER BY store_id"
    ).fetchall()
    empty_or_illegal: list[dict[str, Any]] = []
    brand_value_rows: list[dict[str, Any]] = []
    counter: dict[str, int] = {}
    for r in rows:
        region = r["region"]
        counter[str(region)] = counter.get(str(region), 0) + 1
        if region is None or not str(region).strip() or str(region) not in geo | brand_values:
            empty_or_illegal.append({"store_id": r["store_id"], "region": region})
        if region in brand_values:
            brand_value_rows.append({"store_id": r["store_id"], "region": region})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(rows),
        "geo_names_by_kind_GEO": sorted(geo),
        "geo_name_count": len(geo),
        "region_value_histogram": dict(sorted(counter.items(), key=lambda x: str(x[0]))),
        "empty_or_illegal": empty_or_illegal,
        "empty_or_illegal_count": len(empty_or_illegal),
        "brand_value_rows": brand_value_rows,
        "brand_value_count": len(brand_value_rows),
        "passed": len(empty_or_illegal) == 0,
        "note": "按名称白名单(kind='GEO')判定，不按索引；品牌值行需业务确认归属，"
                "清单非空不等于校验失败，但空/非法行必须为零方可上线。",
    }


def write_validation_report(report: Mapping[str, Any], out_path: str) -> str:
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return out_path


# ---------------- 合成 fixture（非真实底表） ----------------
# 仅用于本地/测试的合成演示口令，不是任何真实系统凭据；可通过环境变量覆盖。
# 生产部署必须走独立的账号开通流程，不得使用本 fixture 账号。
DEFAULT_PASSWORD = os.environ.get("LEDGER_DEMO_PASSWORD", "Demo@12345")


def _num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_synthetic_fixture(conn: Any, settings: Any) -> dict[str, Any]:
    """构造确定性合成数据集，复现任务书转录数字用于逻辑验证。

    注意：这不是真实底表；AC-01~05 的逐角色数字核对仍须在补齐 OPEN-15 后
    用真实数据重做（见 implementation.md「限制」）。
    """
    rng = random.Random(20261109)
    now = datetime.now(timezone.utc).isoformat()

    # ---- users ----
    users = [
        ("u_hq", "hq", "HQ", None, None, "总部用户", 0),
        ("u_east", "east", "REGION", "华东", None, "华东大区", 0),
        ("u_south", "south", "REGION", "华南", None, "华南大区", 0),
        ("u_north", "north", "REGION", "华北", None, "华北大区", 0),
        ("u_west", "west", "REGION", "华西", None, "华西大区", 0),
        ("u_shanhe", "shanhe", "REGION", "山河", None, "山河大区", 0),
        ("u_huanpeng", "huanpeng", "BRAND_BU", None, "欢朋", "欢朋品牌BU", 0),
        ("u_lirui", "lirui", "BRAND_BU", None, "丽芮", "丽芮品牌BU", 0),
        ("u_nodomain", "nodomain", "REGION", "", None, "空数据域账号", 0),
        ("u_admin", "admin", "HQ", None, None, "管理端账号", 1),
    ]
    pw = hash_password(DEFAULT_PASSWORD, settings.pbkdf2_iterations)
    conn.executemany(
        "INSERT OR REPLACE INTO users(user_id,username,password_hash,display_name,role,"
        "region_scope,brand_scope,role_version,status,is_admin,updated_at) "
        "VALUES (?,?,?,?,?,?,?,1,'ACTIVE',?,?)",
        [(u[0], u[1], pw, u[5], u[2], u[3], u[4], u[6], now) for u in users],
    )
    # 无有效角色账号：绕过 CHECK 仅为构造测试用的「脏数据」，验证默认拒绝
    conn.execute("PRAGMA ignore_check_constraints = ON")
    conn.execute(
        "INSERT OR REPLACE INTO users(user_id,username,password_hash,display_name,role,"
        "region_scope,brand_scope,role_version,status,is_admin,updated_at) "
        "VALUES ('u_badrole','badrole',?,'无效角色账号','UNKNOWN',NULL,NULL,1,'ACTIVE',0,?)",
        (pw, now),
    )
    conn.execute("PRAGMA ignore_check_constraints = OFF")

    # ---- stores ----
    stores: list[tuple[Any, ...]] = []
    yearly: list[tuple[Any, ...]] = []
    seq = 0
    prov_counter: dict[str, int] = {}

    def add(region: str, brand: str, province: str, direct: bool, *, city: str | None = None):
        nonlocal seq
        seq += 1
        sid = f"S{seq:06d}"
        pidx = PROVINCES.index(province)
        cities = CITY_POOL[province]
        k = prov_counter.get(province, 0)
        prov_counter[province] = k + 1
        c = city or cities[k % len(cities)]
        lng = 75.0 + pidx * 1.8 + (seq % 17) * 0.001
        lat = 20.0 + pidx * 0.8 + (seq % 13) * 0.001
        rooms = 80 + (seq % 220)
        occ = round(0.45 + (seq % 55) / 100.0, 4)
        adr = 180 + (seq % 420)
        revpar = round(occ * adr, 2)
        status = "在营" if seq % 97 else "非在营"
        stores.append((
            sid, f"门店{seq:06d}", brand, region, province, c,
            f"{province}·{BLOCKS[seq % len(BLOCKS)]}",
            lng, lat, "直营" if direct else "加盟", status,
            rooms, occ, adr, revpar, 0, "2026YTD08", 2026,
        ))
        for year in (2024, 2025, 2026):
            avail = float(rooms * 365)
            sold = round(avail * occ, 2)
            yearly.append((sid, year, avail, sold, float(rooms), occ, float(adr), revpar))
        return sid

    # 地域大区：按 region 行级裁决；内蒙古在华北/华西双列
    for region, count in GEO_REGIONS.items():
        provs = REGION_PROVINCES[region]
        direct_n = DIRECT_COUNT[region]
        for i in range(count):
            prov = provs[i % len(provs)]
            add(region, "其他品牌", prov, i < direct_n)

    # 品牌 BU：brand 字段裁决；region 为字典中的品牌值（不属于任何地域大区）
    for brand, count in BRAND_BU.items():
        for i in range(count):
            provs = HUANPENG_PROVINCES if brand == "欢朋" else PROVINCES[:6]
            prov = provs[i % len(provs)]
            add(BRAND_REGION_VALUE[brand], brand, prov, i < DIRECT_COUNT[brand])

    conn.executemany(
        "INSERT INTO stores(store_id,name,brand,region,province,city,block,lng_gcj02,"
        "lat_gcj02,operate_type,status,rooms,occ,adr,revpar,is_dead,data_version,year) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", stores,
    )
    conn.executemany(
        "INSERT INTO store_yearly(store_id,year,available_room_nights,sold_room_nights,"
        "rooms,occ,adr,revpar) VALUES (?,?,?,?,?,?,?,?)", yearly,
    )

    # ---- canary 哨兵行：改名（不额外增行，保持计数基线） ----
    canaries: dict[str, str] = {}
    groups = [("CANARY_EAST", "华东"), ("CANARY_SOUTH", "华南"),
              ("CANARY_NORTH", "华北"), ("CANARY_WEST", "华西"),
              ("CANARY_SHANHE", "山河"), ("CANARY_HUANPENG", "欢朋品牌BU"),
              ("CANARY_LIRUI", "丽芮品牌")]
    for new_id, region in groups:
        row = conn.execute(
            "SELECT store_id FROM stores WHERE region=? ORDER BY store_id LIMIT 1", (region,)
        ).fetchone()
        if row:
            old = row["store_id"]
            conn.execute("UPDATE stores SET store_id=? WHERE store_id=?", (new_id, old))
            conn.execute("UPDATE store_yearly SET store_id=? WHERE store_id=?", (new_id, old))
            canaries[new_id] = old
    # 内蒙古双列 canary
    for new_id, region in (("CANARY_NM_NORTH", "华北"), ("CANARY_NM_WEST", "华西")):
        row = conn.execute(
            "SELECT store_id FROM stores WHERE province='内蒙古' AND region=? "
            "AND store_id NOT LIKE 'CANARY%' ORDER BY store_id LIMIT 1", (region,)
        ).fetchone()
        if row:
            old = row["store_id"]
            conn.execute("UPDATE stores SET store_id=? WHERE store_id=?", (new_id, old))
            conn.execute("UPDATE store_yearly SET store_id=? WHERE store_id=?", (new_id, old))
            canaries[new_id] = old

    # ---- DQ 探针行：模拟导入物化遗漏，验证 v_ledger 视图层双保险 ----
    probes = {
        "DQ_ROOMS_HI": {"rooms": 3000.1},
        "DQ_OCC_HI": {"occ": 1.21},
        "DQ_ADR_HI": {"adr": 5000.1},
        "DQ_REVPAR_HI": {"revpar": 3000.1},
        "DQ_NONPOSITIVE": {"revpar": -1.0, "occ": 0.0},
        "DQ_BOUNDARY_OK": {"rooms": 3000, "occ": 1.2, "adr": 5000, "revpar": 3000},
    }
    for new_id, patch in probes.items():
        row = conn.execute(
            "SELECT store_id FROM stores WHERE region='华东' AND store_id NOT LIKE 'CANARY%' "
            "AND store_id NOT LIKE 'DQ%' ORDER BY store_id LIMIT 1"
        ).fetchone()
        if row:
            old = row["store_id"]
            conn.execute("UPDATE stores SET store_id=? WHERE store_id=?", (new_id, old))
            conn.execute("UPDATE store_yearly SET store_id=? WHERE store_id=?", (new_id, old))
            sets = ", ".join(f"{k}=?" for k in patch)
            conn.execute(f"UPDATE stores SET {sets} WHERE store_id=?",
                         (*patch.values(), new_id))
            canaries[new_id] = old

    # ---- 死店：不进 v_ledger / 计数 / KPI / 导出 ----
    dead_regions = ["华东", None, "", "未知大区", "丽芮品牌", "欢朋品牌BU", "华南", "华北"]
    dead = []
    for i, region in enumerate(dead_regions):
        dead.append((
            f"DEAD{i:03d}", f"死店{i:03d}", "其他品牌", region,
            "内蒙古" if i % 2 == 0 else "上海", "上海01市",
            "内蒙古·核心商圈", 110.0, 30.0, "加盟", "非在营",
            None, None, None, None, 1, "2026YTD08", 2026,
        ))
    conn.executemany(
        "INSERT INTO stores(store_id,name,brand,region,province,city,block,lng_gcj02,"
        "lat_gcj02,operate_type,status,rooms,occ,adr,revpar,is_dead,data_version,year) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", dead,
    )

    # ---- 竞品：47 726 行，无 region 字段 ----
    comp = []
    for i in range(47726):
        prov = PROVINCES[i % len(PROVINCES)]
        cities = CITY_POOL[prov]
        comp.append((f"C{i:06d}", prov, cities[i % len(cities)],
                     f"竞品品牌{i % 40}", f"竞品{i:06d}"))
    conn.executemany(
        "INSERT INTO competitors(competitor_id,province,city,brand,name) VALUES (?,?,?,?,?)", comp,
    )
    conn.commit()

    return {
        "synthetic": True,
        "stores_total": len(stores),
        "stores_dead": len(dead),
        "stores_live_in_v_ledger": conn.execute("SELECT COUNT(*) c FROM v_ledger").fetchone()["c"],
        "cities": conn.execute("SELECT COUNT(DISTINCT city) c FROM v_ledger").fetchone()["c"],
        "provinces": conn.execute("SELECT COUNT(DISTINCT province) c FROM v_ledger").fetchone()["c"],
        "competitors": len(comp),
        "canaries": canaries,
        "demo_password": DEFAULT_PASSWORD,
    }
