# -*- coding: utf-8 -*-
"""线2订单持久层的无数据库单元测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))

from order_dao import OrderError, normalize_channel, parse_appoint_time  # noqa: E402


class OrderDaoUnitTest(unittest.TestCase):
    def test_family_channel_is_forced_to_family_client(self):
        self.assertEqual(normalize_channel("家属", "电话"), "家属端")

    def test_community_channel_is_preserved(self):
        self.assertEqual(normalize_channel("社区管理员", "电话"), "电话")

    def test_appointment_time_format(self):
        self.assertEqual(parse_appoint_time("2026-12-01 09:30").hour, 9)
        with self.assertRaises(OrderError):
            parse_appoint_time("2026/12/01")


if __name__ == "__main__":
    unittest.main()
