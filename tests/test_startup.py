"""启动兼容检查：不依赖MySQL的升级决策/脚本解析测试。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
from db_diagnostics import database_error_message
from prepare_database import (
    BASE_TABLES,
    SQL_DIR,
    prepare_database,
    schema_objects,
    sql_statements,
)


class StartupTests(unittest.TestCase):
    def connection(self, legacy=False, partial=False, elders=24):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        views = schema_objects((SQL_DIR / "03_views.sql").read_text())
        objects = schema_objects((SQL_DIR / "04_procs_triggers.sql").read_text())
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
                | (set() if legacy or partial else views | {"care_plan_item"})
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
        cur.fetchone.side_effect = [{"n": 6}, {"n": elders}]
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
        source = (SQL_DIR / "04_procs_triggers.sql").read_text()
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


if __name__ == "__main__":
    unittest.main()
