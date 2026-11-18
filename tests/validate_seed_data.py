# -*- coding: utf-8 -*-
"""测试数据总装校验脚本：逐表核对行数，要求每表 ≥ 20 条（任务书 4.3）。

用法：
    python tests/validate_seed_data.py            # 连本机 elder_care（走 config_local.py / 环境变量）
    MYSQL_PORT=3307 python tests/validate_seed_data.py
退出码：全部达标返回 0，否则返回 1。
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
sys.path.insert(0, str(BACKEND))

import pymysql  # noqa: E402
from db import DB_CONFIG  # noqa: E402

REQUIRED_MIN = 20

# 需校验的全部业务表（含线4新增的 device / vital_sign / emergency）
TABLES = [
    "community",
    "caregiver",
    "elder",
    "assessment",
    "care_plan",
    "service_item",
    "service_order",
    "dispatch",
    "schedule",
    "subsidy_policy",
    "subsidy_claim",
    "quality_inspection",
    "device",
    "vital_sign",
    "emergency",
    "sys_user",
]


def main():
    conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
    failed = []
    rows = []
    try:
        with conn.cursor() as cur:
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                n = cur.fetchone()["n"]
                ok = n >= REQUIRED_MIN
                rows.append((table, n, ok))
                if not ok:
                    failed.append(table)
    finally:
        conn.close()

    width = max(len(t) for t in TABLES) + 2
    print(f"{'表名':<{width}}{'行数':>6}  状态")
    print("-" * (width + 14))
    for table, n, ok in rows:
        # 不用 emoji：Windows 默认 GBK 控制台会 UnicodeEncodeError
        print(f"{table:<{width}}{n:>6}  {'[OK] 达标' if ok else '[NG] 不足'}")
    print("-" * (width + 14))
    total_ok = len(TABLES) - len(failed)
    print(f"共 {len(TABLES)} 张表，达标 {total_ok} 张，不足 {len(failed)} 张。")

    if failed:
        print(f"不足 {REQUIRED_MIN} 条的表：{', '.join(failed)}")
        sys.exit(1)
    print("全部业务表均 ≥ %d 条测试数据。" % REQUIRED_MIN)
    return 0


if __name__ == "__main__":
    main()
