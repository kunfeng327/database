"""用内存数据库验证账号补齐、重复运行及回滚；MySQL锁另由集成测试覆盖。"""

import hashlib
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
from demo_family_accounts import create_missing_family_accounts


class Cursor:
    def __init__(self, conn):
        self.cur = conn.cursor()

    def execute(self, sql, args=()):
        self.cur.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""), args)

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()


class Connection:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def cursor(self):
        cursor = Cursor(self.conn)
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
        self.conn = Connection(self.db)

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


if __name__ == "__main__":
    unittest.main()
