#!/usr/bin/env python3
"""门店网络台账后端 · 本地管理与验证入口（stdlib only）。

用法：
  python3 manage.py migrate                    # 建库建表 + 视图 + 字典/meta
  python3 manage.py seed                      # 载入合成 fixture（非真实底表）
  python3 manage.py validate-region [--out]   # region 全量校验清单
  python3 manage.py import-ledger <csv>       # 导入真实底表 CSV（含 DQ 物化）
  python3 manage.py test [-v]                 # 运行 unittest 测试（L1~L5）
  python3 manage.py serve [--port N]          # 启动本地 HTTP 服务
  python3 manage.py report                    # 打印合成 fixture 的数字自检
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger.app import App  # noqa: E402
from ledger.config import Settings  # noqa: E402
from ledger.db import connect, init_schema  # noqa: E402
from ledger.etl import (  # noqa: E402
    build_synthetic_fixture, import_stores_csv, validate_region, write_validation_report,
)


def _app(settings: Settings) -> App:
    conn = connect(settings.db_path)
    return App(conn, settings)


def cmd_migrate(args, settings):
    conn = connect(settings.db_path)
    init_schema(conn)
    conn.close()
    print(json.dumps({"ok": True, "db": settings.db_path}, ensure_ascii=False))


def cmd_seed(args, settings):
    conn = connect(settings.db_path)
    init_schema(conn)
    info = build_synthetic_fixture(conn, settings)
    conn.close()
    print(json.dumps(info, ensure_ascii=False, indent=2))


def cmd_validate_region(args, settings):
    conn = connect(settings.db_path)
    report = validate_region(conn)
    conn.close()
    out = args.out or "region_validation_report.json"
    write_validation_report(report, out)
    print(json.dumps({
        "report": out,
        "total_rows": report["total_rows"],
        "geo_name_count": report["geo_name_count"],
        "empty_or_illegal_count": report["empty_or_illegal_count"],
        "brand_value_count": report["brand_value_count"],
        "passed": report["passed"],
    }, ensure_ascii=False, indent=2))


def cmd_import(args, settings):
    conn = connect(settings.db_path)
    init_schema(conn)
    result = import_stores_csv(conn, args.csv)
    conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_test(args, settings):
    os.environ["LEDGER_DB_PATH"] = ":memory:"
    suite = unittest.TestLoader().discover("tests", top_level_dir=os.path.dirname(os.path.abspath(__file__)))
    result = unittest.TextTestRunner(verbosity=2 if args.v else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_serve(args, settings):
    from ledger.server import serve
    conn = connect(settings.db_path)
    init_schema(conn)
    if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        build_synthetic_fixture(conn, settings)
    print(f"serving on http://{args.host}:{args.port} (db={settings.db_path})", flush=True)
    serve(App(conn, settings), args.host, args.port)
    return 0


def cmd_report(args, settings):
    conn = connect(":memory:")
    init_schema(conn)
    info = build_synthetic_fixture(conn, settings)
    out = {
        "synthetic": True,
        "stores_live": info["stores_live_in_v_ledger"],
        "cities": info["cities"],
        "provinces": info["provinces"],
        "competitors": info["competitors"],
        "direct": conn.execute("SELECT COUNT(*) c FROM v_ledger WHERE operate_type='直营'").fetchone()["c"],
        "franchise": conn.execute("SELECT COUNT(*) c FROM v_ledger WHERE operate_type='加盟'").fetchone()["c"],
        "east": conn.execute("SELECT COUNT(*) c FROM v_ledger WHERE region='华东'").fetchone()["c"],
        "east_direct": conn.execute("SELECT COUNT(*) c FROM v_ledger WHERE region='华东' AND operate_type='直营'").fetchone()["c"],
        "huanpeng": conn.execute("SELECT COUNT(*) c FROM v_ledger WHERE brand='欢朋'").fetchone()["c"],
        "region_validation": {
            k: validate_region(conn)[k] for k in
            ("total_rows", "empty_or_illegal_count", "brand_value_count", "passed")
        },
    }
    conn.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(description="门店网络台账后端（第一期）")
    p.add_argument("--db", default=os.environ.get("LEDGER_DB_PATH", "ledger.db"))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate")
    sub.add_parser("seed")
    vr = sub.add_parser("validate-region")
    vr.add_argument("--out", default=None)
    imp = sub.add_parser("import-ledger")
    imp.add_argument("csv")
    t = sub.add_parser("test")
    t.add_argument("-v", action="store_true")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8080)
    sub.add_parser("report")

    args = p.parse_args()
    settings = Settings(db_path=args.db)
    handlers = {
        "migrate": cmd_migrate, "seed": cmd_seed, "validate-region": cmd_validate_region,
        "import-ledger": cmd_import, "test": cmd_test, "serve": cmd_serve,
        "report": cmd_report,
    }
    rc = handlers[args.cmd](args, settings)
    return int(rc or 0)


if __name__ == "__main__":
    raise SystemExit(main())
