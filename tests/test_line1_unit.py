"""不依赖第三方库的 DAO 单元测试；真实 MySQL 并发/视图见集成测试。

SQLite 只验证参数化 CRUD 和事务原子性，不用于证明 MySQL 语法或锁语义。
"""

import datetime as dt
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
from db import transaction
from elder_dao import ElderDAO, ability_level
from errors import BizError

sqlite3.register_adapter(dt.date, lambda value: value.isoformat())
sqlite3.register_converter("DATE", lambda value: dt.date.fromisoformat(value.decode()))


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

    @property
    def lastrowid(self):
        return self.cursor.lastrowid


class ConnectionAdapter:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.row_factory = sqlite3.Row
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
                """CREATE TABLE community (community_id INTEGER PRIMARY KEY);
                INSERT INTO community VALUES (1),(2);
                CREATE TABLE elder (elder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, id_card TEXT UNIQUE, birth_date DATE, gender TEXT,address TEXT,
                community_id INTEGER REFERENCES community,guardian_name TEXT,guardian_phone TEXT,
                special_tag TEXT,status TEXT DEFAULT '正常');
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


if __name__ == "__main__":
    unittest.main()
