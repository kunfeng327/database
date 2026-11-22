import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
sys.path.insert(0, str(BACKEND))

import app as appmod


def _client(role, elder_id=None):
    client = appmod.app.test_client()
    with client.session_transaction() as user_session:
        user_session.update(uid=1, name="测试用户", role=role)
        if elder_id is not None:
            user_session["elder_id"] = elder_id
    return client


def test_health_api_rejects_roles_without_access():
    client = _client("护工")

    assert client.get("/api/health/devices").status_code == 403
    assert client.get("/api/health/elders").status_code == 403
    assert client.post("/api/health/devices", json={}).status_code == 403
    assert client.post("/api/health/vitals", json={}).status_code == 403
    assert client.post("/api/health/emergencies", json={}).status_code == 403


def test_family_health_reads_are_scoped_to_bound_elder(monkeypatch):
    queries = []
    monkeypatch.setattr(
        appmod,
        "query_all",
        lambda sql, args=(): queries.append((sql, args)) or [],
    )

    class Cursor:
        def execute(self, sql, args=()):
            queries.append((sql, args))

        def fetchall(self):
            return []

    monkeypatch.setattr(appmod, "run_in_transaction", lambda fn: fn(Cursor()))
    client = _client("家属", elder_id=42)

    assert client.get("/api/health/devices").status_code == 200
    assert client.get("/api/health/vitals").status_code == 200
    assert client.get("/api/health/emergencies").status_code == 200
    assert queries
    assert all(args == (42,) for _, args in queries)
    assert "WHERE elder_id=%s" in queries[0][0]
    assert all("elder_id=%s" in sql for sql, _ in queries[1:])
