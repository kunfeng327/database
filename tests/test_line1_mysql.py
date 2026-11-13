"""真实 MySQL 8.0.16+/9.x 集成测试（显式开启 LINE1_TEST_MYSQL=1）。

只创建/删除随机命名 elder_care_test_* 临时库，绝不重置 MYSQL_DB 指向的业务库。
账号需具备建测试库/例程/触发器权限；不开启时报告 skipped。
"""

import datetime as dt
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
from errors import BizError


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
        self.assertEqual(
            self.sql("SELECT pause_reason FROM care_plan WHERE plan_id=6")[0][
                "pause_reason"
            ],
            "手动暂停",
        )

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
        self.assertIn("********", detail["id_masked"])

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
