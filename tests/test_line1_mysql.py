"""真实 MySQL 8.0.16+/9.x 集成测试（显式开启 LINE1_TEST_MYSQL=1）。

只创建/删除随机命名 elder_care_test_* 临时库，绝不重置 MYSQL_DB 指向的业务库。
账号需具备建测试库/例程/触发器权限；不开启时报告 skipped。
"""

import datetime as dt
import hashlib
import os
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/backend"))
from db import DB_CONFIG
from elder_dao import ElderDAO
from notification_dao import NotificationDAO
from errors import BizError
from demo_family_accounts import create_missing_family_accounts


def run_script(conn, path):
    delimiter = ";"
    pending = ""
    with conn.cursor() as cur:
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            if stripped.startswith(("USE ", "DROP DATABASE ", "CREATE DATABASE ")):
                continue
            if stripped.startswith("DELIMITER "):
                delimiter = stripped.split()[1]
                continue
            pending += line + "\n"
            while delimiter in pending:
                statement, pending = pending.split(delimiter, 1)
                if statement.strip():
                    cur.execute(statement)
        if pending.strip():
            raise AssertionError("SQL未正常结束: " + str(path))
    conn.commit()


@unittest.skipUnless(
    os.environ.get("LINE1_TEST_MYSQL") == "1", "未开启真实 MySQL 集成测试"
)
class MySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pymysql

        cls.pymysql = pymysql
        cls.database = "elder_care_test_" + uuid.uuid4().hex[:12]
        cls.config = {
            **DB_CONFIG,
            "database": cls.database,
            "cursorclass": pymysql.cursors.DictCursor,
        }
        admin = pymysql.connect(
            **{k: v for k, v in cls.config.items() if k != "database"}
        )
        try:
            with admin.cursor() as cur:
                cur.execute(
                    "CREATE DATABASE "
                    + cls.database
                    + " CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
        finally:
            admin.close()
        cls.addClassCleanup(cls.drop_test_database)
        conn = cls.connect()
        try:
            run_script(conn, ROOT / "sql/01_schema.sql")
        finally:
            conn.close()

    @classmethod
    def drop_test_database(cls):
        conn = cls.pymysql.connect(
            **{k: v for k, v in cls.config.items() if k != "database"}
        )
        try:
            with conn.cursor() as cur:
                cur.execute("DROP DATABASE " + cls.database)
        finally:
            conn.close()

    @classmethod
    def connect(cls):
        return cls.pymysql.connect(**cls.config)

    def setUp(self):
        conn = self.connect()
        try:
            for name in ["02_seed.sql", "03_views.sql", "04_procs_triggers.sql"]:
                run_script(conn, ROOT / "sql" / name)
        finally:
            conn.close()
        self.dao = ElderDAO(self.connect)

    def sql(self, sql, args=()):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def test_missing_family_accounts_can_receive_reminders(self):
        existing = self.sql("SELECT * FROM sys_user ORDER BY user_id")
        conn = self.connect()
        try:
            self.assertEqual(len(create_missing_family_accounts(conn)), 22)
            self.assertEqual(create_missing_family_accounts(conn), [])
        finally:
            conn.close()
        self.assertEqual(self.sql("SELECT * FROM sys_user WHERE user_id<=6 ORDER BY user_id"), existing)
        account = self.sql("SELECT * FROM sys_user WHERE username='样例老人9'")[0]
        self.assertEqual(account["elder_id"], 23)
        self.assertEqual(account["password_hash"], hashlib.sha256((account["salt"] + "123456").encode()).hexdigest())
        notifications = NotificationDAO(self.connect)
        self.assertEqual(notifications.send_reminder(23, 1)["created_count"], 1)
        self.assertEqual(self.sql("SELECT recipient_id FROM family_notification WHERE elder_id=23"),
                         [{"recipient_id": account["user_id"]}])

    def test_concurrent_family_account_completion_does_not_duplicate(self):
        barrier = threading.Barrier(2)

        def complete():
            conn = self.connect()
            try:
                barrier.wait(timeout=10)
                return len(create_missing_family_accounts(conn))
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: complete(), range(2))), [0, 22])
        self.assertEqual(self.sql("SELECT COUNT(*) n FROM sys_user WHERE role='家属'"), [{"n": 24}])

    def plan(self, **changes):
        today = dt.date.today()
        data = dict(
            package_name="测试计划",
            frequency="每日一次",
            start_date=str(today),
            end_date=str(today + dt.timedelta(days=30)),
            item_ids=[1, 8],
            caregiver_id=1,
        )
        data.update(changes)
        return data

    def test_startup_upgrades_legacy_schema_and_preserves_archives(self):
        from prepare_database import prepare_database

        before = self.sql("SELECT elder_id,name,id_card FROM elder ORDER BY elder_id")
        self.sql("DROP TABLE care_plan_item")
        self.sql("DROP TABLE family_notification")
        self.sql(
            "ALTER TABLE care_plan DROP CHECK chk_pause_reason, DROP COLUMN pause_reason"
        )
        self.sql(
            "ALTER TABLE care_plan DROP INDEX idx_plan_elder, ADD INDEX idx_plan_elder (elder_id,status)"
        )
        self.sql("ALTER TABLE assessment DROP INDEX idx_assess_latest")
        self.sql("DROP VIEW v_latest_assessment")
        self.sql("DROP PROCEDURE sp_pause_expired_plans_worker")
        conn = self.connect()
        try:
            self.assertTrue(prepare_database(conn)["upgraded"])
            self.assertFalse(prepare_database(conn)["upgraded"])
        finally:
            conn.close()
        self.assertEqual(
            self.sql("SELECT elder_id,name,id_card FROM elder ORDER BY elder_id"),
            before,
        )
        self.assertEqual(self.sql("SELECT DATABASE() AS db")[0]["db"], self.database)
        self.assertEqual(len(self.dao.list_elders()), 24)
        self.assertEqual(NotificationDAO(self.connect).inbox(2)["total"], 0)
        self.assertEqual(
            self.sql("SELECT pause_reason FROM care_plan WHERE plan_id=6")[0][
                "pause_reason"
            ],
            "手动暂停",
        )

    def test_reminder_delivery_persistence_deduplication_and_family_isolation(self):
        dao = NotificationDAO(self.connect)
        self.sql("UPDATE sys_user SET elder_id=23 WHERE user_id=2")
        self.assertEqual(dao.send_reminder(23, 1)["created_count"], 1)
        message = dao.inbox(2)["messages"][0]
        self.assertIn("首次评估", message["title"])
        self.assertEqual(dao.send_reminder(23, 1)["created_count"], 0)
        self.assertEqual(dao.inbox(2)["total"], 1)
        self.assertEqual(dao.inbox(3)["total"], 0)
        with self.assertRaises(BizError):
            dao.mark_read(message["notification_id"], 3)
        dao.mark_read(message["notification_id"], 2)
        read_at = dao.inbox(2)["messages"][0]["read_at"]
        dao.mark_read(message["notification_id"], 2)
        self.assertEqual(dao.inbox(2)["unread_count"], 0)
        self.assertEqual(dao.inbox(2)["messages"][0]["read_at"], read_at)
        self.sql("UPDATE sys_user SET elder_id=24 WHERE user_id=2")
        self.assertEqual(dao.inbox(2)["total"], 0)
        with self.assertRaises(BizError):
            dao.mark_read(message["notification_id"], 2)

    def test_reminder_concurrent_send_delivers_only_once(self):
        self.sql("UPDATE sys_user SET elder_id=23 WHERE user_id=2")
        barrier = threading.Barrier(2)
        def send():
            barrier.wait(timeout=10)
            return NotificationDAO(self.connect).send_reminder(23, 1)["created_count"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: send(), range(2)))
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(NotificationDAO(self.connect).inbox(2)["total"], 1)

    def test_reminder_rechecks_current_assessment_and_disabled_accounts(self):
        dao = NotificationDAO(self.connect)
        with self.assertRaisesRegex(BizError, "绑定"):
            dao.send_reminder(23, 1)
        self.sql("UPDATE sys_user SET elder_id=23,status='停用' WHERE user_id=2")
        with self.assertRaisesRegex(BizError, "绑定"):
            dao.send_reminder(23, 1)
        self.sql("UPDATE sys_user SET status='启用' WHERE user_id=2")
        dao.send_reminder(23, 1)
        self.dao.create_assessment(23, {"score": 80}, "测试评估员")
        with self.assertRaisesRegex(BizError, "无需"):
            dao.send_reminder(23, 1)
        self.sql("UPDATE sys_user SET status='停用' WHERE user_id=2")
        self.assertEqual(dao.inbox(2)["total"], 0)

    def test_seed_counts_and_nonduplicated_views(self):
        for table in ["elder", "assessment", "care_plan", "care_plan_item"]:
            self.assertGreaterEqual(
                self.sql("SELECT COUNT(*) n FROM " + table)[0]["n"], 20
            )
        rows = self.dao.list_elders()
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({r["elder_id"] for r in rows}), 24)
        self.assertEqual(
            sum(
                r["elder_count"]
                for r in self.sql("SELECT * FROM v_community_ability_distribution")
            ),
            22,
        )
        self.assertEqual(
            {
                r["elder_id"]
                for r in self.sql("SELECT * FROM v_living_alone_unassessed")
            },
            {23, 24},
        )

    def test_pagination_search_and_masking(self):
        rows, total = self.dao.list_elders(page=1, page_size=3)
        self.assertEqual((len(rows), total), (3, 24))
        self.assertEqual(self.dao.list_elders(keyword="' OR 1=1 --"), [])
        detail = self.dao.get_elder(1)
        self.assertNotIn("id_card", detail)
        self.assertEqual(detail["id_masked"], "*" * 18)
        self.assertTrue(all(r["id_masked"] == "*" * 18 for r in rows))

    def test_old_partial_identity_view_never_leaks_through_archive_list(self):
        self.sql("""CREATE OR REPLACE VIEW v_elder_assessment_plan AS
            SELECT e.elder_id,e.name,80 AS age,c.community_id,c.name AS community,
            CONCAT(LEFT(e.id_card,6),'********',RIGHT(e.id_card,4)) AS id_masked,
            e.special_tag,e.status AS elder_status,NULL AS ability_level,NULL AS assess_expire,
            NULL AS assess_expired,NULL AS plan_id,NULL AS package_name,NULL AS plan_status
            FROM elder e JOIN community c ON c.community_id=e.community_id""")
        self.assertTrue(all(r["id_masked"] == "*" * 18 for r in self.dao.list_elders()))
        self.assertTrue(all(r["id_masked"] == "*" * 18 for r in self.dao.list_elders(page=1)[0]))

    def test_reassessment_pauses_and_restores_only_automatic_plans(self):
        self.assertGreaterEqual(self.dao.pause_expired()["paused_plans"], 2)
        result = self.dao.create_assessment(10, {"score": 85}, "测试评估员")
        self.assertEqual(result["resumed_plans"], 1)
        self.assertEqual(
            result["expire_date"],
            self.sql("SELECT DATE_ADD(CURDATE(),INTERVAL 1 YEAR) d")[0]["d"],
        )
        self.assertEqual(
            self.dao.create_assessment(7, {"score": 85}, "测试评估员")["resumed_plans"],
            0,
        )
        self.assertEqual(
            self.sql("SELECT status FROM care_plan WHERE plan_id=6")[0]["status"],
            "暂停",
        )

    def test_no_assessment_cannot_create_plan(self):
        with self.assertRaises(BizError):
            self.dao.save_plan(23, self.plan())

    def test_plan_crud_and_item_rollback(self):
        self.dao.create_assessment(23, {"score": 70}, "测试评估员")
        pid = self.dao.save_plan(23, self.plan())["plan_id"]
        with self.assertRaises(BizError):
            self.dao.save_plan(23, self.plan())
        self.dao.save_plan(23, self.plan(item_ids=[2]), pid)
        with self.assertRaises(BizError):
            self.dao.save_plan(23, self.plan(item_ids=[99999]), pid)
        self.assertEqual([r["item_id"] for r in self.dao.plans(23)[0]["items"]], [2])
        self.dao.set_plan_status(23, pid, "暂停")
        self.dao.set_plan_status(23, pid, "生效")
        self.dao.set_plan_status(23, pid, "结束")
        with self.assertRaises(BizError):
            self.dao.set_plan_status(23, pid, "生效")

    def test_plan_and_partial_items_roll_back_on_database_failure(self):
        self.dao.create_assessment(23, {"score": 80}, "测试评估员")
        self.sql(
            """CREATE TRIGGER tr_test_reject_item BEFORE INSERT ON care_plan_item
            FOR EACH ROW BEGIN IF NEW.item_id=8 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='injected item failure';
            END IF; END"""
        )
        try:
            with self.assertRaises(self.pymysql.err.OperationalError):
                self.dao.save_plan(23, self.plan())
            self.assertEqual(self.dao.plans(23), [])
            self.assertEqual(
                self.sql("SELECT COUNT(*) n FROM care_plan_item")[0]["n"], 35
            )
        finally:
            self.sql("DROP TRIGGER tr_test_reject_item")

    def test_concurrent_overlapping_plans_only_one_commits(self):
        self.dao.create_assessment(23, {"score": 80}, "测试评估员")
        barrier = threading.Barrier(2)

        def create():
            barrier.wait(timeout=10)
            try:
                return self.dao.save_plan(23, self.plan())
            except BizError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.dao.plans(23)), 1)

    def test_touching_dates_conflict_but_adjacent_days_allowed(self):
        self.dao.create_assessment(23, {"score": 80}, "测试评估员")
        end = dt.date.today() + dt.timedelta(days=30)
        self.dao.save_plan(23, self.plan())
        with self.assertRaises(BizError):
            self.dao.save_plan(
                23,
                self.plan(
                    start_date=str(end), end_date=str(end + dt.timedelta(days=5))
                ),
            )
        self.dao.save_plan(
            23,
            self.plan(
                start_date=str(end + dt.timedelta(days=1)),
                end_date=str(end + dt.timedelta(days=5)),
            ),
        )
        self.assertEqual(len(self.dao.plans(23)), 2)

    def test_dispatch_trigger_rejects_expired_assessment(self):
        self.sql(
            "UPDATE assessment SET expire_date=DATE_SUB(CURDATE(),INTERVAL 1 DAY) WHERE elder_id=1"
        )
        with self.assertRaises(self.pymysql.err.OperationalError) as caught:
            self.sql("INSERT INTO dispatch (order_id,caregiver_id) VALUES (8,1)")
        self.assertEqual(caught.exception.args[0], 1644)
        self.assertEqual(
            self.sql("SELECT COUNT(*) n FROM dispatch WHERE order_id=8")[0]["n"], 0
        )


if __name__ == "__main__":
    unittest.main()
