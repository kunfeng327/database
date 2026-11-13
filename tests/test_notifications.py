"""通知发送的业务边界、原子性和当日去重（无需数据库驱动）。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
from notification_dao import NotificationDAO
from errors import BizError


class NotificationTests(unittest.TestCase):
    def setup_send(self, assessment=None, recipients=(2, 3), sent=(), status="正常"):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{"name": "测试老人", "status": status}, assessment]
        cur.fetchall.side_effect = [
            [{"user_id": n} for n in recipients],
            [{"recipient_id": n} for n in sent],
        ]
        return NotificationDAO(lambda: conn), conn, cur

    def test_first_assessment_delivered_to_all_bound_recipients(self):
        dao, conn, cur = self.setup_send()
        self.assertEqual(
            dao.send_reminder(23, 1),
            {
                "created_count": 2,
                "existing_count": 0,
                "recipient_count": 2,
            },
        )
        writes = [
            call.args[1]
            for call in cur.execute.call_args_list
            if call.args[0].startswith("INSERT")
        ]
        self.assertEqual([w[0] for w in writes], [2, 3])
        self.assertTrue(all("首次评估" in w[-1] for w in writes))
        conn.commit.assert_called_once()

    def test_duplicate_does_not_resend_but_new_family_can_receive(self):
        dao, conn, cur = self.setup_send(sent=(2,))
        self.assertEqual(dao.send_reminder(23, 1)["created_count"], 1)
        writes = [
            call.args[1]
            for call in cur.execute.call_args_list
            if call.args[0].startswith("INSERT")
        ]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], 3)

    def test_reminder_date_boundaries_and_server_generated_content(self):
        for days, title in [(-1, "评估过期提醒"), (0, "复评提醒"), (30, "复评提醒")]:
            with self.subTest(days=days):
                dao, conn, cur = self.setup_send(
                    {"assessment_id": 7, "expire_date": "2026-11-13", "days_left": days}
                )
                dao.send_reminder(1, 9)
                writes = [
                    call.args[1]
                    for call in cur.execute.call_args_list
                    if call.args[0].startswith("INSERT")
                ]
                self.assertEqual(writes[0][-2], title)
                self.assertIn("2026-11-13", writes[0][-1])

    def test_not_due_archives_and_unbound_families_rejected_without_write(self):
        for kwargs, message in [
            ({"assessment": {"assessment_id": 1, "days_left": 31}}, "无需"),
            ({"recipients": ()}, "绑定"),
            ({"status": "注销"}, "注销"),
            ({"status": "暂停服务"}, "暂停"),
        ]:
            with self.subTest(kwargs=kwargs):
                dao, conn, cur = self.setup_send(**kwargs)
                with self.assertRaisesRegex(BizError, message):
                    dao.send_reminder(1, 1)
                self.assertFalse(
                    any(
                        c.args[0].startswith("INSERT")
                        for c in cur.execute.call_args_list
                    )
                )
                conn.rollback.assert_called_once()
                conn.commit.assert_not_called()

    def test_partial_delivery_failure_rolls_back_all_messages(self):
        dao, conn, cur = self.setup_send()

        def execute(sql, args):
            if sql.startswith("INSERT") and args[0] == 3:
                raise RuntimeError("write failed")

        cur.execute.side_effect = execute
        with self.assertRaises(RuntimeError):
            dao.send_reminder(23, 1)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_marking_inaccessible_message_never_updates(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        with self.assertRaisesRegex(BizError, "无权"):
            NotificationDAO(lambda: conn).mark_read(5, 2)
        self.assertEqual(cur.execute.call_count, 1)
        conn.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
