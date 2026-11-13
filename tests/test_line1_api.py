"""Flask 接口权限和登录回归；安装 requirements.txt 后运行。"""

import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
AVAILABLE = all(importlib.util.find_spec(name) for name in ("flask", "pymysql"))
if AVAILABLE:
    import app as backend


@unittest.skipUnless(AVAILABLE, "需要安装 Flask 和 PyMySQL")
class APITests(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True, SECRET_KEY="unit-test-secret")
        self.client = backend.app.test_client()
        self.dao = MagicMock()
        self.patcher = patch.object(backend, "elder_dao", return_value=self.dao)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

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

    def test_database_error_does_not_expose_identity(self):
        self.login_as("社区管理员")
        self.dao.create_elders.side_effect = RuntimeError(
            "SQL id_card=110108195001010011"
        )
        response = self.client.post("/api/elders", json={})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("110108", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
