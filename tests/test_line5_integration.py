# -*- coding: utf-8 -*-
"""Line 5 integration test.

Run against an isolated, freshly seeded MySQL instance:
    MYSQL_PORT=3307 python -m unittest tests.test_line5_integration

The test intentionally changes the isolated database state.
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

from app import app  # noqa: E402
from db import DB_CONFIG  # noqa: E402


def db_connection():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)


class Line5IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def login(self, username):
        response = self.client.post(
            "/api/login", json={"username": username, "password": "123456"}
        )
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_line5_end_to_end(self):
        conn = db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM subsidy_claim")
                self.assertGreaterEqual(cur.fetchone()["n"], 20)
                cur.execute("SELECT COUNT(*) AS n FROM quality_inspection")
                self.assertGreaterEqual(cur.fetchone()["n"], 20)
        finally:
            conn.close()

        self.login("jianguan")
        response = self.client.post(
            "/api/subsidy/claims/4/audit", json={"action": "approve"}
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["data"]["audit_status"], "街道已审")

        response = self.client.post(
            "/api/subsidy/claims/4/audit", json={"action": "pass"}
        )
        self.assertEqual(response.get_json()["data"]["audit_status"], "通过")

        response = self.client.post(
            "/api/subsidy/claims/4/audit", json={"action": "pay"}
        )
        self.assertEqual(response.get_json()["data"]["pay_status"], "已拨付")

        response = self.client.post(
            "/api/quality/inspections",
            json={
                "order_id": 1,
                "inspection_method": "电话回访",
                "score": 65,
                "issue_tags": "回访记录不完整",
                "rectification_requirement": "补齐回访记录",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            response.get_json()["data"]["rectification_status"], "待整改"
        )

        response = self.client.post(
            "/api/quality/inspections/random",
            json={"sample_rate": 50, "inspection_method": "上门核查"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertGreater(response.get_json()["data"]["created_count"], 0)

        conn = db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT MAX(inspection_id) AS inspection_id
                         FROM quality_inspection
                        WHERE inspection_status='待抽查'"""
                )
                pending_id = cur.fetchone()["inspection_id"]
        finally:
            conn.close()

        response = self.client.post(
            f"/api/quality/inspections/{pending_id}/result",
            json={
                "inspection_method": "上门核查",
                "score": 91,
                "issue_tags": "",
                "rectification_requirement": "",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            response.get_json()["data"]["rectification_status"], "无需整改"
        )

        conn = db_connection()
        try:
            with conn.cursor() as cur:
                with self.assertRaises(pymysql.err.OperationalError) as blocked:
                    cur.execute(
                        "INSERT INTO dispatch (order_id, caregiver_id) VALUES (8,1)"
                    )
                self.assertEqual(blocked.exception.args[0], 1644)
        finally:
            conn.close()

        response = self.client.post(
            "/api/quality/inspections/9/rectification",
            json={"rectification_result": "监管人员不应代填整改结果"},
        )
        self.assertEqual(response.status_code, 403)

        self.login("hugong")
        response = self.client.post(
            "/api/quality/inspections/9/rectification",
            json={"rectification_result": "已完成服务沟通复训并上传证明"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(
            response.get_json()["data"]["rectification_status"], "已完成"
        )

        conn = db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO dispatch (order_id, caregiver_id) VALUES (8,1)"
                )
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
