# -*- coding: utf-8 -*-
"""线2服务下单与派单真实 MySQL 集成测试。

默认连接本地 elder_care；可用 MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PWD/MYSQL_DB 覆盖。
没有可用数据库时整组测试跳过，而不是误报为通过。
"""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path

try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - dependency availability
    pymysql = None
    PYMYSQL_AVAILABLE = False

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
sys.path.insert(0, str(BACKEND))

from db import DB_CONFIG  # noqa: E402
from order_dao import (  # noqa: E402
    complete_dispatch,
    create_order,
    dispatch_order,
    reassign_dispatch,
    recommend_caregivers,
)


@unittest.skipUnless(PYMYSQL_AVAILABLE, "未安装 PyMySQL，跳过线2集成测试")
class Line2IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
            cls.conn.close()
        except Exception as exc:  # pragma: no cover - depends on local environment
            raise unittest.SkipTest(f"未连接到 MySQL，跳过线2集成测试：{exc}")
        cls.created_orders = []

    @classmethod
    def tearDownClass(cls):
        if not cls.created_orders:
            return
        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(cls.created_orders))
                cur.execute(f"DELETE FROM dispatch WHERE order_id IN ({placeholders})", cls.created_orders)
                cur.execute(f"DELETE FROM service_order WHERE order_id IN ({placeholders})", cls.created_orders)
            conn.commit()
        finally:
            conn.close()

    def _new_order(self, channel="家属端"):
        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        try:
            with conn.cursor() as cur:
                appointment = (dt.datetime.now() + dt.timedelta(days=1)).replace(
                    hour=9, minute=30, second=0, microsecond=0
                )
                result = create_order(cur, 1, 1, appointment.strftime("%Y-%m-%d %H:%M"), channel, "社区管理员")
            conn.commit()
            self.created_orders.append(result["order_id"])
            return result["order_id"]
        finally:
            conn.close()

    def _dispatch(self, order_id, caregiver_id=6):
        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        try:
            with conn.cursor() as cur:
                result = dispatch_order(cur, order_id, caregiver_id)
            conn.commit()
            return result["dispatch_id"]
        finally:
            conn.close()

    def test_recommend_only_dispatchable_caregivers(self):
        order_id = self._new_order()
        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        try:
            with conn.cursor() as cur:
                candidates = recommend_caregivers(cur, order_id)
            caregiver_ids = {row["caregiver_id"] for row in candidates}
            self.assertIn(6, caregiver_ids)
            self.assertNotIn(1, caregiver_ids)
            self.assertNotIn(2, caregiver_ids)
        finally:
            conn.close()

    def test_order_dispatch_complete_flow(self):
        order_id = self._new_order()
        dispatch_id = self._dispatch(order_id)

        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        try:
            with conn.cursor() as cur:
                result = complete_dispatch(cur, dispatch_id, "集成测试完成服务", "社区管理员", None)
            conn.commit()
            self.assertEqual(result["dispatch_id"], dispatch_id)
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM service_order WHERE order_id=%s", (order_id,))
                self.assertEqual(cur.fetchone()["status"], "已完成")
        finally:
            conn.close()

    def test_reassign_keeps_history_and_returns_order_to_pending(self):
        order_id = self._new_order("电话")
        dispatch_id = self._dispatch(order_id)

        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        try:
            with conn.cursor() as cur:
                result = reassign_dispatch(cur, dispatch_id, "集成测试改派")
            conn.commit()
            self.assertEqual(result["order_id"], order_id)
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM service_order WHERE order_id=%s", (order_id,))
                self.assertEqual(cur.fetchone()["status"], "待派单")
                cur.execute("SELECT is_current, reassign_reason FROM dispatch WHERE dispatch_id=%s", (dispatch_id,))
                history = cur.fetchone()
                self.assertEqual(history["is_current"], 0)
                self.assertEqual(history["reassign_reason"], "集成测试改派")
        finally:
            conn.close()

    def test_expired_caregiver_is_rejected_by_trigger(self):
        order_id = self._new_order()
        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        try:
            with conn.cursor() as cur:
                with self.assertRaises(pymysql.err.OperationalError) as caught:
                    dispatch_order(cur, order_id, 8)
            conn.rollback()
            self.assertEqual(caught.exception.args[0], 1644)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM dispatch WHERE order_id=%s", (order_id,))
                self.assertEqual(cur.fetchone()["n"], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

