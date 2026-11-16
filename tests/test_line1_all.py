"""业务线1（pengkunfeng）全部测试的合并文件。

合并自 test_line1_unit / test_line1_api / test_line1_mysql / test_notifications /
test_startup / test_demo_family_accounts / test_demo_server 七个文件，
避免后续合入其他成员分支后难以辨认本人测试。

分节目录（按依赖条件排列，前五节无需第三方库）：
  §1 DAO 单元测试      —— SQLite 内存库 + mock，验证参数化 CRUD 与事务原子性
  §2 通知单元测试      —— mock 连接，验证发送边界/去重/回滚/越权
  §3 启动检查单元测试  —— mock 连接 + 解析真实 SQL 脚本，验证升级决策
  §4 家属账号补齐测试  —— 内存 SQLite，验证补齐/重名/回滚
  §5 演示服务启动测试  —— mock 服务器工厂，验证端口绑定与浏览器打开顺序
  §6 Flask 接口回归    —— 需安装 Flask 和 PyMySQL，未安装时整节跳过
  §7 MySQL 集成测试    —— 需设置 LINE1_TEST_MYSQL=1，自动创建/清理随机测试库

运行：python -m unittest tests.test_line1_all -v
"""

import datetime as dt
import hashlib
import importlib.util
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/backend"))

from db import DB_CONFIG, transaction
from line1_all import (
    BASE_TABLES,
    SQL_DIR,
    BizError,
    ElderDAO,
    NotificationDAO,
    URL,
    ability_level,
    create_missing_family_accounts,
    database_error_message,
    prepare_database,
    run_demo,
    schema_objects,
    sql_statements,
)

API_AVAILABLE = all(importlib.util.find_spec(name) for name in ("flask", "pymysql"))
if API_AVAILABLE:
    import app as backend

sqlite3.register_adapter(dt.date, lambda value: value.isoformat())
sqlite3.register_converter("DATE", lambda value: dt.date.fromisoformat(value.decode()))


# =====================================================================
# §1 DAO 单元测试（原 test_line1_unit.py）
# SQLite 只验证参数化 CRUD 和事务原子性，不用于证明 MySQL 语法或锁语义。
# =====================================================================


def elder_body(**changes):
    result = dict(
        name="测试老人",
        id_card="110108195001010011",
        birth_date="1950-01-01",
        gender="女",
        address="测试社区1号楼",
        community_id=1,
        guardian_name="测试家属",
        guardian_phone="13800000001",
        special_tag=["独居"],
    )
    result.update(changes)
    return result


class CursorAdapter:
    def __init__(self, conn):
        self.cursor = conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, args=()):
        sql = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        return self.cursor.execute(sql, args)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]

    @property
    def lastrowid(self):
        return self.cursor.lastrowid


class ConnectionAdapter:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("REPEAT", 2, lambda value, count: value * count)
        self.conn.execute("PRAGMA foreign_keys=ON")

    def cursor(self):
        return CursorAdapter(self.conn)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


class DAOTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "line1.db")
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """CREATE TABLE community (community_id INTEGER PRIMARY KEY, name TEXT DEFAULT '测试社区');
                INSERT INTO community (community_id) VALUES (1),(2);
                CREATE TABLE elder (elder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, id_card TEXT UNIQUE, birth_date DATE, gender TEXT,address TEXT,
                community_id INTEGER REFERENCES community,guardian_name TEXT,guardian_phone TEXT,
                special_tag TEXT,status TEXT DEFAULT '正常',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE care_plan (plan_id INTEGER PRIMARY KEY,elder_id INTEGER,
                status TEXT,pause_reason TEXT);"""
            )
        self.dao = ElderDAO(lambda: ConnectionAdapter(self.path))

    def rows(self, table):
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM " + table)]

    def test_create_batch_and_persist(self):
        ids = self.dao.create_elders(
            [elder_body(), elder_body(id_card="110108195001010022")]
        )
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(len(self.rows("elder")), 2)

    def test_archive_queries_hide_every_identity_character_even_with_old_view(self):
        eid = self.dao.create_elders([elder_body()])[0]
        with sqlite3.connect(self.path) as conn:
            conn.executescript("""CREATE VIEW v_elder_assessment_plan AS
                SELECT elder_id,name,76 AS age,community_id,'测试社区' AS community,
                id_card AS id_masked,special_tag,status AS elder_status,
                NULL AS ability_level,NULL AS assess_expire,NULL AS assess_expired,
                NULL AS plan_id,NULL AS package_name,NULL AS plan_status FROM elder;""")
        for row in [self.dao.get_elder(eid), *self.dao.list_elders(), *self.dao.list_elders(page=1)[0]]:
            self.assertEqual(row["id_masked"], "*" * 18)
            self.assertNotIn("id_card", row)
        self.assertEqual(self.rows("elder")[0]["id_card"], elder_body()["id_card"])

    def test_duplicate_second_record_rolls_back_first_insert(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.dao.create_elders([elder_body(), elder_body()])
        self.assertEqual(self.rows("elder"), [])

    def test_invalid_second_community_rolls_back_first_insert(self):
        with self.assertRaisesRegex(BizError, "社区不存在"):
            self.dao.create_elders(
                [
                    elder_body(),
                    elder_body(id_card="110108195001010022", community_id=999),
                ]
            )
        self.assertEqual(self.rows("elder"), [])

    def test_community_migration_preserves_identity(self):
        eid = self.dao.create_elders([elder_body()])[0]
        body = elder_body(community_id=2, name="张'三")
        body.pop("id_card")
        self.dao.update_elder(eid, body)
        rows = self.rows("elder")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            (rows[0]["elder_id"], rows[0]["community_id"], rows[0]["name"]),
            (eid, 2, "张'三"),
        )
        self.assertEqual(rows[0]["id_card"], elder_body()["id_card"])

    def test_identity_is_immutable(self):
        with self.assertRaisesRegex(BizError, "不可修改"):
            self.dao.update_elder(1, elder_body())

    def test_soft_delete_ends_plans_keeps_identity(self):
        eid = self.dao.create_elders([elder_body()])[0]
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO care_plan VALUES (1,?,'生效',NULL)", (eid,))
        self.dao.set_elder_status(eid, "注销")
        self.assertEqual(self.rows("elder")[0]["status"], "注销")
        self.assertEqual(self.rows("care_plan")[0]["status"], "结束")
        with self.assertRaises(BizError):
            self.dao.set_elder_status(eid, "正常")
        with self.assertRaises(sqlite3.IntegrityError):
            self.dao.create_elders([elder_body()])

    def test_pause_and_reopen_does_not_silently_resume_plans(self):
        eid = self.dao.create_elders([elder_body()])[0]
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO care_plan VALUES (1,?,'生效',NULL)", (eid,))
        self.dao.set_elder_status(eid, "暂停服务")
        self.dao.set_elder_status(eid, "正常")
        self.assertEqual(self.rows("care_plan")[0]["status"], "暂停")
        self.assertEqual(self.rows("care_plan")[0]["pause_reason"], "档案暂停")

    def test_multi_table_write_failure_rolls_back_status(self):
        eid = self.dao.create_elders([elder_body()])[0]
        with sqlite3.connect(self.path) as conn:
            conn.execute("DROP TABLE care_plan")
        with self.assertRaises(sqlite3.OperationalError):
            self.dao.set_elder_status(eid, "注销")
        self.assertEqual(self.rows("elder")[0]["status"], "正常")


class ValidationTests(unittest.TestCase):
    def test_score_boundaries(self):
        for score, expected in [
            (0, "重度失能"),
            (49, "重度失能"),
            (50, "中度失能"),
            (74, "中度失能"),
            (75, "轻度失能"),
            (84, "轻度失能"),
            (85, "能力完好"),
            (100, "能力完好"),
        ]:
            with self.subTest(score=score):
                self.assertEqual(ability_level(score), expected)

    def test_invalid_scores(self):
        for score in [True, False, None, 1.5, "85", -1, 101]:
            with self.subTest(score=score), self.assertRaises(BizError):
                ability_level(score)

    def test_invalid_fields_before_connection(self):
        factory = MagicMock()
        dao = ElderDAO(factory)
        for change in [
            dict(name=" "),
            dict(birth_date="2050-01-01"),
            dict(birth_date="1950-02-30"),
            dict(community_id=True),
            dict(gender="未知"),
            dict(guardian_phone="123"),
            dict(special_tag="独居"),
            dict(special_tag=["不存在"]),
            dict(id_card="1" * 18),
        ]:
            with self.subTest(change=change), self.assertRaises(BizError):
                dao.create_elders([elder_body(**change)])
        factory.assert_not_called()

    def test_invalid_scale_and_batch(self):
        dao = ElderDAO(MagicMock())
        with self.assertRaises(BizError):
            dao.create_assessment(1, {"scale": "错误量表", "score": 80}, "评估员")
        for records in [[], None, {}, [elder_body()] * 101]:
            with self.assertRaises(BizError):
                dao.create_elders(records)

    def test_transaction_commit_error_rolls_back_and_closes(self):
        conn = MagicMock()
        conn.commit.side_effect = RuntimeError("commit failed")
        with self.assertRaises(RuntimeError):
            transaction(lambda: conn, lambda cur: 1)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_assessment_failure_after_insert_rolls_back(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{"status": "正常"}, RuntimeError("read failed")]
        with self.assertRaises(RuntimeError):
            ElderDAO(lambda: conn).create_assessment(1, {"score": 85}, "评估员")
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_reassessment_only_resumes_auto_pauses_without_conflicts(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.lastrowid = 42
        expiry = dt.date(2028, 2, 29)
        cur.fetchone.side_effect = [
            {"status": "正常"},
            {"expire_date": expiry},
            None,
            {"plan_id": 99},
        ]
        cur.fetchall.return_value = [
            {
                "plan_id": 10,
                "start_date": dt.date(2027, 1, 1),
                "end_date": dt.date(2027, 2, 1),
            },
            {
                "plan_id": 11,
                "start_date": dt.date(2027, 1, 1),
                "end_date": dt.date(2027, 2, 1),
            },
        ]
        result = ElderDAO(lambda: conn).create_assessment(1, {"score": 85}, "评估员")
        self.assertEqual(
            result,
            {
                "assessment_id": 42,
                "ability_level": "能力完好",
                "expire_date": expiry,
                "resumed_plans": 1,
            },
        )
        sql = " ".join(call.args[0] for call in cur.execute.call_args_list)
        self.assertIn("pause_reason='评估过期'", sql)
        self.assertIn("end_date>=CURDATE()", sql)
        conn.commit.assert_called_once()

    def test_overlap_rejected_before_any_plan_write(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        today = dt.date.today()
        cur.fetchone.side_effect = [
            {"status": "正常"},
            {"today": today, "assess_date": today, "expire_date": today},
            {"plan_id": 1},
        ]
        body = dict(
            package_name="服务包",
            frequency="每周一次",
            start_date=str(today),
            end_date=str(today),
            item_ids=[1],
        )
        with self.assertRaisesRegex(BizError, "已有生效"):
            ElderDAO(lambda: conn).save_plan(1, body)
        self.assertFalse(
            any(
                re.match(r"\s*(INSERT|UPDATE)", c.args[0])
                for c in cur.execute.call_args_list
            )
        )
        conn.rollback.assert_called_once()


# =====================================================================
# §2 通知单元测试（原 test_notifications.py）
# 发送边界、原子性和当日去重，无需数据库驱动。
# =====================================================================


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


# =====================================================================
# §3 启动检查单元测试（原 test_startup.py）
# 不依赖 MySQL 的升级决策/脚本解析测试。
# =====================================================================


class StartupTests(unittest.TestCase):
    def connection(self, legacy=False, partial=False, elders=24, partial_identity=False):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        views = schema_objects((SQL_DIR / "03_views.sql").read_text(encoding="utf-8"))
        objects = schema_objects((SQL_DIR / "04_procs_triggers.sql").read_text(encoding="utf-8"))
        indexes = [
            dict(table_name="care_plan", name="idx_plan_elder", column_name=c)
            for c in (
                ["elder_id", "status"]
                if legacy
                else ["elder_id", "status", "start_date", "end_date"]
            )
        ]
        if not legacy:
            indexes += [
                dict(table_name="assessment", name="idx_assess_latest", column_name=c)
                for c in ["elder_id", "assess_date", "assessment_id"]
            ]
        cur.fetchall.side_effect = [
            [
                {"name": n}
                for n in BASE_TABLES
                | (set() if legacy or partial else views | {"care_plan_item", "family_notification"})
            ],
            [] if legacy else [{"name": "pause_reason"}],
            indexes,
            (
                []
                if legacy or partial
                else [{"name": n} for n in objects if n.startswith("sp_")]
            ),
            (
                []
                if legacy or partial
                else [{"name": n} for n in objects if n.startswith("tr_")]
            ),
            [] if legacy or partial else [{"name": "chk_pause_reason"}],
        ]
        cur.fetchone.side_effect = [{"definition": "SELECT LEFT(e.id_card,6)" if partial_identity else "SELECT REPEAT('*',18)"}, {"n": 6}, {"n": elders}]
        return conn, cur

    def test_upgraded_schema_requires_no_writes(self):
        conn, cur = self.connection()
        self.assertEqual(
            prepare_database(conn), {"upgraded": False, "users": 6, "elders": 24}
        )
        self.assertTrue(
            all(
                c.args[0].lstrip().startswith("SELECT")
                for c in cur.execute.call_args_list
            )
        )
        conn.commit.assert_not_called()

    def test_legacy_schema_gets_upgrade_but_no_seed_or_data_reset(self):
        conn, cur = self.connection(legacy=True)
        result = prepare_database(conn)
        self.assertTrue(result["upgraded"])
        statements = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any("ADD COLUMN pause_reason" in s for s in statements))
        self.assertTrue(any("CREATE TABLE care_plan_item" in s for s in statements))
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS family_notification" in s for s in statements))
        self.assertTrue(
            any(
                s.startswith("CREATE PROCEDURE sp_pause_expired_plans_worker")
                for s in statements
            )
        )
        self.assertTrue(any("v_latest_assessment" in s for s in statements))
        for s in statements:
            self.assertFalse(
                s.upper().startswith(
                    (
                        "DROP DATABASE",
                        "DROP TABLE",
                        "TRUNCATE",
                        "DELETE",
                        "INSERT",
                        "USE ",
                    )
                ),
                s,
            )
        conn.commit.assert_called_once()

    def test_partial_upgrade_does_not_add_existing_column_or_indexes(self):
        conn, cur = self.connection(partial=True)
        self.assertTrue(prepare_database(conn)["upgraded"])
        sql = "\n".join(c.args[0] for c in cur.execute.call_args_list)
        self.assertNotIn("ADD COLUMN pause_reason", sql)
        self.assertNotIn("ADD INDEX", sql)
        self.assertIn("ADD CONSTRAINT chk_pause_reason", sql)
        self.assertIn("CREATE TABLE care_plan_item", sql)

    def test_partial_identity_view_is_replaced_without_resetting_data(self):
        conn, cur = self.connection(partial_identity=True)
        self.assertTrue(prepare_database(conn)["upgraded"])
        statements = [c.args[0] for c in cur.execute.call_args_list]
        view = next(s for s in statements if s.startswith("CREATE OR REPLACE VIEW v_elder_assessment_plan"))
        self.assertIn("REPEAT('*',18) AS id_masked", view)
        self.assertFalse(any(s.startswith(("TRUNCATE", "DELETE", "DROP TABLE")) for s in statements))

    def test_missing_base_tables_rejected_before_ddl(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [{"name": "elder"}]
        with self.assertRaisesRegex(ValueError, "基础表不完整"):
            prepare_database(conn)
        self.assertEqual(cur.execute.call_count, 1)
        conn.commit.assert_not_called()

    def test_empty_archive_is_reported_without_seeding(self):
        conn, cur = self.connection(elders=0)
        self.assertEqual(prepare_database(conn)["elders"], 0)
        self.assertTrue(
            all(
                c.args[0].lstrip().startswith("SELECT")
                for c in cur.execute.call_args_list
            )
        )

    def test_sql_parser_preserves_routines_and_delimiters_in_strings(self):
        script = """-- comment;
SET NAMES utf8mb4;
DELIMITER $$
CREATE PROCEDURE example()
BEGIN
  SELECT 'keep;this$$value', 'it''s ok'; -- trailing comment
END$$
DELIMITER ;
SELECT 1;
"""
        statements = list(sql_statements(script))
        self.assertEqual(len(statements), 3)
        self.assertIn("'keep;this$$value'", statements[1])
        self.assertIn("'it''s ok'", statements[1])
        self.assertTrue(statements[1].endswith("END"))
        self.assertEqual(statements[2], "SELECT 1")

    def test_actual_sql_scripts_have_expected_objects(self):
        source = (SQL_DIR / "04_procs_triggers.sql").read_text(encoding="utf-8")
        statements = list(sql_statements(source))
        self.assertEqual(sum(s.startswith("CREATE PROCEDURE") for s in statements), 2)
        self.assertEqual(sum(s.startswith("CREATE TRIGGER") for s in statements), 3)
        with self.assertRaises(ValueError):
            list(sql_statements("SELECT 'unterminated;"))

    def test_error_messages_are_specific_and_safe(self):
        self.assertIn("升级", database_error_message(1054))
        self.assertIn("升级", database_error_message(1146))
        self.assertIn("初始化", database_error_message(1049))
        self.assertIn("密码", database_error_message(1045))
        self.assertIn("服务已启动", database_error_message(2003))
        self.assertIsNone(database_error_message(99999))


# =====================================================================
# §4 家属账号补齐测试（原 test_demo_family_accounts.py）
# 内存数据库验证账号补齐、重复运行及回滚；MySQL 锁另由 §7 集成测试覆盖。
# =====================================================================


class FamilyCursor:
    def __init__(self, conn):
        self.cur = conn.cursor()

    def execute(self, sql, args=()):
        self.cur.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""), args)

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()


class FamilyConnection:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def cursor(self):
        cursor = FamilyCursor(self.conn)
        try:
            yield cursor
        finally:
            cursor.cur.close()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()


class DemoFamilyAccountTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE elder (elder_id INTEGER PRIMARY KEY, name TEXT, guardian_name TEXT);
            CREATE TABLE sys_user (
                user_id INTEGER PRIMARY KEY, username TEXT UNIQUE CHECK(length(username)<=30),
                password_hash TEXT, salt TEXT CHECK(length(salt)=16), real_name TEXT,
                role TEXT, elder_id INTEGER REFERENCES elder(elder_id), status TEXT
            );
        """)
        self.conn = FamilyConnection(self.db)

    def elders(self, names):
        self.db.executemany("INSERT INTO elder VALUES (?,?,?)", [
            (i, name, "监护人") for i, name in enumerate(names, 1)
        ])
        self.db.commit()

    def existing_user(self, username, elder_id=None, status="启用"):
        self.db.execute("INSERT INTO sys_user VALUES (NULL,?,?,?,?,?,?,?)",
                        (username, "existing-hash", "0123456789abcdef", "已有用户",
                         "家属" if elder_id else "社区管理员", elder_id, status))
        self.db.commit()

    def users(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM sys_user ORDER BY user_id")]

    def test_fill_missing_accounts_preserves_existing_and_disabled_accounts(self):
        self.elders(["陈桂香", "王守义", "李淑珍", "吴桂芳"])
        self.existing_user("jiashu", 1)
        self.existing_user("jiashu2", 3, "停用")
        existing = self.users()
        created = create_missing_family_accounts(self.conn)
        self.assertEqual([(a["elder_id"], a["username"]) for a in created], [(2, "王守义"), (4, "吴桂芳")])
        users = self.users()
        self.assertEqual(users[:2], existing)
        self.assertNotEqual(users[2]["salt"], users[3]["salt"])
        for row in users[2:]:
            self.assertEqual((row["role"], row["status"]), ("家属", "启用"))
            self.assertEqual(row["password_hash"], hashlib.sha256((row["salt"] + "123456").encode()).hexdigest())
        self.assertEqual(create_missing_family_accounts(self.conn), [])
        self.assertEqual(self.users(), users)

    def test_duplicate_names_and_occupied_suffixes_never_rebind_accounts(self):
        long_name = "陈" * 30
        self.elders(["王守义", "王守义", long_name, long_name])
        self.existing_user("王守义")
        self.existing_user("王守义_1")
        existing = self.users()
        created = create_missing_family_accounts(self.conn)
        self.assertEqual([a["username"] for a in created], ["王守义_1_2", "王守义_2", long_name, "陈" * 28 + "_4"])
        self.assertEqual(self.users()[:2], existing)

    def test_names_are_parameterized(self):
        name = "王'守义"
        self.elders([name])
        create_missing_family_accounts(self.conn)
        self.assertEqual(self.users()[0]["username"], name)

    def test_write_failure_rolls_back_entire_batch_and_can_retry(self):
        self.elders(["王守义", "吴桂芳"])
        self.existing_user("shequ")
        existing = self.users()
        self.db.executescript("""CREATE TRIGGER reject_second BEFORE INSERT ON sys_user
            WHEN NEW.elder_id=2 BEGIN SELECT RAISE(ABORT,'injected failure'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            create_missing_family_accounts(self.conn)
        self.assertEqual(self.users(), existing)
        self.db.execute("DROP TRIGGER reject_second")
        self.assertEqual(len(create_missing_family_accounts(self.conn)), 2)

    def test_empty_archive_creates_no_accounts(self):
        self.assertEqual(create_missing_family_accounts(self.conn), [])
        self.assertEqual(self.users(), [])


# =====================================================================
# §5 演示服务启动测试（原 test_demo_server.py）
# 先绑定端口再打开浏览器；不依赖 Flask/MySQL。
# =====================================================================


class DemoServerTests(unittest.TestCase):
    def test_occupied_port_never_opens_browser(self):
        for error in (OSError("address in use"), SystemExit(1)):
            with (
                self.subTest(error=type(error)),
                patch("line1_all.threading.Timer") as timer,
                patch("builtins.print"),
            ):
                factory = MagicMock(side_effect=error)
                self.assertEqual(
                    run_demo(object(), open_browser=True, server_factory=factory), 1
                )
                timer.assert_not_called()

    def test_browser_scheduled_only_after_successful_bind(self):
        server = MagicMock()
        app = object()
        events = []

        def bind(*args, **kwargs):
            events.append("bind")
            return server

        with patch("line1_all.threading.Timer") as timer, patch("builtins.print"):
            timer.return_value.start.side_effect = lambda: events.append("browser")
            server.serve_forever.side_effect = lambda: events.append("serve")
            self.assertEqual(run_demo(app, open_browser=True, server_factory=bind), 0)
            self.assertEqual(events, ["bind", "browser", "serve"])
            self.assertEqual(timer.call_args.kwargs["args"], (URL,))
            timer.return_value.cancel.assert_called_once()
            server.server_close.assert_called_once()

    def test_manual_start_and_interrupt_close_server_without_browser(self):
        server = MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch("line1_all.threading.Timer") as timer, patch("builtins.print"):
            self.assertEqual(
                run_demo(object(), server_factory=MagicMock(return_value=server)), 0
            )
            timer.assert_not_called()
            server.server_close.assert_called_once()


# =====================================================================
# §6 Flask 接口回归（原 test_line1_api.py）
# 需要安装 Flask 和 PyMySQL；未安装时整节跳过。
# =====================================================================


@unittest.skipUnless(API_AVAILABLE, "需要安装 Flask 和 PyMySQL")
class APITests(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True, SECRET_KEY="unit-test-secret")
        self.client = backend.app.test_client()
        self.dao = MagicMock()
        self.patcher = patch.object(backend, "elder_dao", return_value=self.dao)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.notifications = MagicMock()
        notification_patcher = patch.object(backend, "notification_dao", return_value=self.notifications)
        notification_patcher.start()
        self.addCleanup(notification_patcher.stop)

    def login_as(self, role, elder_id=1):
        with self.client.session_transaction() as session:
            session.update(uid=1, name="测试人员", role=role, elder_id=elder_id)

    def test_unauthenticated_requests_rejected(self):
        for path in [
            "/api/elders",
            "/api/elders/1",
            "/api/elders/1/assessments",
            "/api/elders/1/plans",
        ]:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.dao.list_elders.assert_not_called()

    def test_family_cannot_read_other_elder(self):
        self.login_as("家属")
        for suffix in ["", "/assessments", "/plans"]:
            self.assertEqual(self.client.get("/api/elders/2" + suffix).status_code, 403)
        self.dao.get_elder.assert_not_called()

    def test_unbound_family_fails_closed(self):
        self.login_as("家属", elder_id=None)
        self.assertEqual(self.client.get("/api/elders").status_code, 403)
        self.dao.list_elders.assert_not_called()

    def test_family_list_is_always_scoped(self):
        self.login_as("家属")
        self.dao.list_elders.return_value = []
        self.assertEqual(self.client.get("/api/elders?elder_id=2").status_code, 200)
        self.assertEqual(self.dao.list_elders.call_args.kwargs["elder_id"], 1)

    def test_all_non_admin_roles_cannot_write(self):
        for role in ["家属", "监管人员", "护工", "机构负责人"]:
            self.login_as(role)
            for method, path in [
                ("post", "/api/elders"),
                ("put", "/api/elders/1"),
                ("delete", "/api/elders/1"),
                ("post", "/api/elders/batch"),
                ("patch", "/api/elders/1/status"),
                ("post", "/api/elders/1/assessments"),
                ("post", "/api/elders/1/plans"),
                ("put", "/api/elders/1/plans/1"),
                ("patch", "/api/elders/1/plans/1/status"),
            ]:
                with self.subTest(role=role, path=path):
                    self.assertEqual(
                        getattr(self.client, method)(path, json={}).status_code, 403
                    )
        self.assertEqual(self.dao.method_calls, [])

    def test_workers_and_agencies_cannot_read_archives(self):
        for role in ["护工", "机构负责人"]:
            self.login_as(role)
            self.assertEqual(self.client.get("/api/elders").status_code, 403)
            self.assertEqual(
                self.client.get("/api/elders/1/assessments").status_code, 403
            )

    def test_regulator_contact_is_masked(self):
        self.login_as("监管人员")
        self.dao.get_elder.return_value = {
            "elder_id": 1,
            "guardian_phone": "13800000001",
            "address": "家庭详细地址",
            "id_masked": "110108********0011",
        }
        row = self.client.get("/api/elders/1").get_json()["data"]
        self.assertEqual(row["guardian_phone"], "138****0001")
        self.assertNotIn("address", row)

    def test_invalid_json_and_pagination_are_client_errors(self):
        self.login_as("社区管理员")
        for body in [[], None, "bad"]:
            self.assertEqual(
                self.client.post("/api/elders", json=body).status_code in (400, 415),
                True,
            )
        for query in [
            "page=0",
            "page=-1",
            "page_size=101",
            "community_id=x",
            "status=invalid",
        ]:
            self.assertEqual(self.client.get("/api/elders?" + query).status_code, 400)

    def test_login_failure_counter_is_committed_and_fifth_attempt_locks(self):
        with self.client.session_transaction() as session:
            session.clear()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        user = dict(
            user_id=9,
            status="启用",
            salt="salt",
            password_hash=backend.hash_password("salt", "right"),
            locked_until=None,
            failed_attempts=0,
        )
        with patch.object(backend, "get_conn", return_value=conn):
            for i in range(5):
                cur.fetchone.return_value = {**user, "failed_attempts": i}
                response = self.client.post(
                    "/api/login", json={"username": "demo", "password": "wrong"}
                )
                self.assertEqual(response.status_code, 400)
            self.assertIn("锁定", response.get_json()["msg"])
            self.assertEqual(conn.commit.call_count, 5)
            conn.rollback.assert_not_called()
            cur.fetchone.return_value = {
                **user,
                "locked_until": dt.datetime.now() + dt.timedelta(minutes=10),
            }
            response = self.client.post(
                "/api/login", json={"username": "demo", "password": "right"}
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_missing_database_objects_return_actionable_service_error(self):
        self.login_as("社区管理员")
        for code, expected in [
            (1146, "升级"),
            (1054, "升级"),
            (1049, "初始化"),
            (2003, "MySQL"),
        ]:
            self.dao.list_elders.side_effect = backend.pymysql.err.OperationalError(
                code, "private SQL and credentials"
            )
            response = self.client.get("/api/elders")
            self.assertEqual(response.status_code, 503)
            self.assertIn(expected, response.get_json()["msg"])
            self.assertNotIn("private", response.get_data(as_text=True))

    def test_database_error_does_not_expose_identity(self):
        self.login_as("社区管理员")
        self.dao.create_elders.side_effect = RuntimeError(
            "SQL id_card=110108195001010011"
        )
        response = self.client.post("/api/elders", json={})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("110108", response.get_data(as_text=True))

    def test_notification_roles_and_authentication(self):
        paths = [("post", "/api/elders/1/reminders", "社区管理员"),
                 ("get", "/api/notifications", "家属"),
                 ("patch", "/api/notifications/1/read", "家属")]
        for method, path, allowed_role in paths:
            with self.client.session_transaction() as session:
                session.clear()
            self.assertEqual(getattr(self.client, method)(path).status_code, 401)
            for role in ["家属", "社区管理员", "监管人员", "护工", "机构负责人"]:
                if role == allowed_role:
                    continue
                self.login_as(role)
                self.assertEqual(getattr(self.client, method)(path).status_code, 403)
        self.assertEqual(self.notifications.method_calls, [])

    def test_notification_scope_comes_from_session_not_request(self):
        self.login_as("家属")
        self.notifications.inbox.return_value = {"messages": [], "total": 0, "unread_count": 0}
        self.notifications.mark_read.return_value = {"notification_id": 5}
        response = self.client.get("/api/notifications?recipient_id=999&elder_id=999&page=2")
        self.assertEqual(response.status_code, 200)
        self.notifications.inbox.assert_called_once_with(1, page=2)
        self.assertEqual(self.client.patch("/api/notifications/5/read", json={"user_id": 999}).status_code, 200)
        self.notifications.mark_read.assert_called_once_with(5, 1)
        for page in ["0", "-1", "x", "1000001"]:
            self.assertEqual(self.client.get("/api/notifications?page="+page).status_code, 400)

    def test_notification_sender_is_authenticated_admin(self):
        self.login_as("社区管理员")
        self.notifications.send_reminder.return_value = {"created_count": 1}
        response = self.client.post("/api/elders/23/reminders", json={"sender_id": 999, "recipient_id": 88})
        self.assertEqual(response.status_code, 200)
        self.notifications.send_reminder.assert_called_once_with(23, 1)


# =====================================================================
# §7 MySQL 集成测试（原 test_line1_mysql.py）
# 真实 MySQL 8.0.16+/9.x（显式开启 LINE1_TEST_MYSQL=1）。
# 只创建/删除随机命名 elder_care_test_* 临时库，绝不重置 MYSQL_DB 指向的业务库。
# 账号需具备建测试库/例程/触发器权限；不开启时报告 skipped。
# =====================================================================


def run_script(conn, path):
    delimiter = ";"
    pending = ""
    with conn.cursor() as cur:
        for line in path.read_text(encoding="utf-8").splitlines():
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
        from line1_all import prepare_database

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
