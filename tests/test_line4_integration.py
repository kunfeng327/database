# -*- coding: utf-8 -*-
"""Line 4 DAO + 触发器集成测试（健康监测与应急响应）。

针对独立、全新导入的 MySQL 实例运行：
    MYSQL_PORT=3307 python -m unittest tests.test_line4_integration

测试会修改独立测试库的数据。
"""
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
os.environ.setdefault("MYSQL_PORT", "3307")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("MYSQL_PWD", "")
os.environ.setdefault("MYSQL_DB", "elder_care")

import pymysql  # noqa: E402

from db import DB_CONFIG  # noqa: E402
from line4_dao import (  # noqa: E402
    Line4Error,
    bind_device,
    unbind_device,
    record_vital_sign,
    confirm_vital_abnormal,
    create_emergency,
    respond_emergency,
    complete_emergency,
)


def db_connection():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)


class Line4IntegrationTest(unittest.TestCase):
    def test_line4_tables_seeded(self):
        conn = db_connection()
        try:
            with conn.cursor() as cur:
                for table in ("device", "vital_sign", "emergency"):
                    cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                    self.assertGreaterEqual(cur.fetchone()["n"], 20, table)
        finally:
            conn.close()

    def test_vital_sign_auto_flag_trigger(self):
        """超阈值自动标记「待确认」，阈值内标记「正常」（DB 触发器）。"""
        conn = db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO vital_sign
                       (device_id, elder_id, collect_time, metric_type, metric_value, data_source)
                       VALUES (1, 1, NOW(), '收缩压', 200, '自动采集')"""
                )
                conn.commit()
                cur.execute(
                    """SELECT abnormal_flag FROM vital_sign
                        WHERE device_id=1 AND metric_type='收缩压' AND metric_value=200
                        ORDER BY vital_id DESC LIMIT 1"""
                )
                self.assertEqual(cur.fetchone()["abnormal_flag"], "待确认")

                cur.execute(
                    """INSERT INTO vital_sign
                       (device_id, elder_id, collect_time, metric_type, metric_value, data_source)
                       VALUES (1, 1, NOW(), '心率', 75, '自动采集')"""
                )
                conn.commit()
                cur.execute(
                    """SELECT abnormal_flag FROM vital_sign
                        WHERE device_id=1 AND metric_type='心率' AND metric_value=75
                        ORDER BY vital_id DESC LIMIT 1"""
                )
                self.assertEqual(cur.fetchone()["abnormal_flag"], "正常")
        finally:
            conn.close()

    def test_emergency_auto_escalate_trigger(self):
        """超时未响应的应急事件在被响应时自动升级等级（DB 触发器）。"""
        conn = db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO emergency (elder_id, trigger_source, event_level, occur_time, status)
                       VALUES (1, '设备告警', '一般', DATE_SUB(NOW(), INTERVAL 90 MINUTE), '待响应')"""
                )
                event_id = cur.lastrowid
                conn.commit()

                cur.execute(
                    """UPDATE emergency SET responder='社区李干事', arrive_time=NOW()
                        WHERE event_id=%s""",
                    (event_id,),
                )
                conn.commit()
                cur.execute(
                    "SELECT event_level, escalated, status FROM emergency WHERE event_id=%s",
                    (event_id,),
                )
                row = cur.fetchone()
                self.assertEqual(row["event_level"], "紧急")
                self.assertEqual(row["escalated"], 1)
                self.assertEqual(row["status"], "已响应")
        finally:
            conn.close()

    def test_line4_dao_end_to_end(self):
        """设备绑定 → 体征录入/复核 → 事件上报/响应/处置 → 解绑（走 DAO）。"""
        conn = db_connection()
        try:
            with conn.cursor() as cur:
                device = bind_device(
                    cur,
                    {"elder_id": 2, "device_type": "血压计", "install_location": "测试位置"},
                )
                device_id = device["device_id"]
                self.assertEqual(device["status"], "绑定")

                vital = record_vital_sign(
                    cur, {"device_id": 1, "metric_type": "血氧", "metric_value": 88}
                )
                self.assertEqual(vital["abnormal_flag"], "待确认")

                confirmed = confirm_vital_abnormal(cur, vital["vital_id"], "异常")
                self.assertEqual(confirmed["abnormal_flag"], "异常")

                event = create_emergency(
                    cur, {"elder_id": 2, "trigger_source": "家属呼叫", "event_level": "紧急"}
                )
                event_id = event["event_id"]

                responded = respond_emergency(cur, event_id, {"responder": "社区李干事"})
                self.assertEqual(responded["status"], "已响应")

                completed = complete_emergency(cur, event_id, "已安排护工上门，老人无恙")
                self.assertEqual(completed["status"], "已处置")

                unbound = unbind_device(cur, device_id)
                self.assertEqual(unbound["status"], "解绑")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def test_line4_dao_business_rules(self):
        """DAO 业务校验：非法输入抛出 Line4Error。"""
        conn = db_connection()
        try:
            with conn.cursor() as cur:
                with self.assertRaises(Line4Error):
                    bind_device(
                        cur,
                        {"elder_id": 2, "device_type": "未知设备", "install_location": "x"},
                    )
                with self.assertRaises(Line4Error):
                    record_vital_sign(
                        cur, {"device_id": 1, "metric_type": "血氧", "metric_value": "abc"}
                    )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
