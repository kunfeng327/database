# -*- coding: utf-8 -*-
"""线1 老人档案与能力评估 · DAO + 数据库集成测试。

覆盖：档案建册与重号拦截、字段校验、评估等级核定与一年有效期、
评估过期自动暂停计划、复评自动恢复、**事务回滚原子性**、新视图可用性。
针对独立测试库运行：
    MYSQL_DB=elder_care_v1t MYSQL_PORT=3306 python -m pytest tests/test_line1_integration.py -v
"""
import os
import sys
import datetime as dt
from unittest.mock import MagicMock, Mock

import pytest
import pymysql

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/backend")))

import db as dbmod  # noqa: E402
import elder_dao as dao  # noqa: E402
import care_plan_dao  # noqa: E402
import app as appmod  # noqa: E402


TEST_ID_BASE = dt.date.today().strftime("110101%y%m%d")  # 每日变化，避免残留脏数据
_seq = iter(range(100))


def _connect():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **dbmod.DB_CONFIG)


def _new_elder_payload(**override):
    """构造一份合法的建档 payload，测试可按需覆盖字段。"""
    n = next(_seq)
    payload = {
        "name": f"测试老人{n}",
        "id_card": f"{TEST_ID_BASE}{n:05d}X",  # 6位地区+6位日期+5位序号+校验位 = 18 位
        "birth_date": "1940-01-01",
        "gender": "女",
        "address": "幸福社区测试楼1单元101",
        "community_id": 1,
        "guardian_name": f"测试监护人{n}",
        "guardian_phone": "13800000001",
        "special_tag": ["独居", "高龄"],
    }
    payload.update(override)
    return payload


def _cleanup(conn, **ids):
    """按 elder_id 级联清理测试痕迹，保持演示库干净。"""
    with conn.cursor() as cur:
        for elder_id in filter(None, ids.get("elder_ids", [])):
            cur.execute("DELETE FROM care_plan WHERE elder_id=%s", (elder_id,))
            cur.execute("DELETE FROM assessment WHERE elder_id=%s", (elder_id,))
            cur.execute("DELETE FROM elder WHERE elder_id=%s", (elder_id,))
    conn.commit()


def test_01_create_elder_and_duplicate_idcard():
    """建档成功；身份证重号被数据库唯一约束拦截（IntegrityError）。"""
    conn = _connect()
    elder_id = None
    try:
        payload = _new_elder_payload()
        with conn.cursor() as cur:
            created = dao.create_elder(cur, payload)
            elder_id = created["elder_id"]
            assert created["status"] == "正常"
            cur.execute("SELECT name, special_tag FROM elder WHERE elder_id=%s", (elder_id,))
            row = cur.fetchone()
            assert row["name"].startswith("测试老人")
            assert row["special_tag"] == "独居,高龄"
        conn.commit()

        dup = dict(payload, name="重号老人")  # 换名但同身份证
        with pytest.raises(pymysql.err.IntegrityError):
            with conn.cursor() as cur:
                dao.create_elder(cur, dup)
        conn.rollback()
    finally:
        _cleanup(conn, elder_ids=[elder_id])
        conn.close()


def test_02_create_elder_field_validation():
    """DAO 业务校验：身份证/性别/电话/出生日期/标签非法时抛 ElderError，不落库。"""
    conn = _connect()
    try:
        bad_cases = [
            _new_elder_payload(id_card="12345"),                       # 身份证位数
            _new_elder_payload(gender="未知"),                          # 性别
            _new_elder_payload(guardian_phone="12345"),                 # 电话
            _new_elder_payload(birth_date="2099-01-01"),                # 未来出生
            _new_elder_payload(special_tag=["独居", "特级护理"]),        # 标签越界
            _new_elder_payload(community_id=999),                       # 社区不存在
        ]
        for payload in bad_cases:
            with pytest.raises(dao.ElderError):
                with conn.cursor() as cur:
                    dao.create_elder(cur, payload)
        conn.rollback()
    finally:
        conn.close()


def test_03_assessment_level_and_expiry():
    """评估等级按得分核定（演示口径），有效期一年。"""
    conn = _connect()
    elder_id = None
    try:
        with conn.cursor() as cur:
            elder_id = dao.create_elder(cur, _new_elder_payload())["elder_id"]
            for score, level in [(90, "能力完好"), (80, "轻度失能"),
                                 (60, "中度失能"), (30, "重度失能")]:
                res = dao.record_assessment(cur, elder_id, {"score": score}, "测试评估员")
                assert res["ability_level"] == level
            expire = dt.date.fromisoformat(res["expire_date"])
            assert (expire - dt.date.today()).days in (364, 365)
            with pytest.raises(dao.ElderError):
                dao.record_assessment(cur, elder_id, {"score": "abc"}, "测试评估员")
            with pytest.raises(dao.ElderError):
                dao.record_assessment(cur, elder_id, {"score": 101}, "测试评估员")
        conn.commit()
    finally:
        _cleanup(conn, elder_ids=[elder_id])
        conn.close()


def test_04_expired_assessment_pauses_then_reevaluation_resumes():
    """闭环：评估过期 → 计划自动暂停 → 禁止手动启用 → 复评后恢复一条计划。"""
    conn = _connect()
    elder_id = None
    try:
        with conn.cursor() as cur:
            elder_id = dao.create_elder(cur, _new_elder_payload())["elder_id"]
            # 先建有效评估和生效计划，再将评估过期以模拟时间流逝。
            today = dt.date.today()
            last_year = dt.date.today() - dt.timedelta(days=400)
            cur.execute(
                """INSERT INTO assessment (elder_id, scale, score, ability_level, assessor,
                                            assess_date, expire_date)
                   VALUES (%s,'ADL',90,'能力完好','历史评估',%s,%s)""",
                (elder_id, today, today + dt.timedelta(days=365)),
            )
            cur.execute(
                """INSERT INTO care_plan (elder_id, package_name, frequency, start_date, end_date, status)
                   VALUES (%s,'测试服务包','每周1次',CURDATE(),CURDATE()+INTERVAL 90 DAY,'生效')""",
                (elder_id,),
            )
            plan_id = cur.lastrowid
            cur.execute(
                """INSERT INTO care_plan (elder_id, package_name, frequency, start_date, end_date, status)
                   VALUES (%s,'测试服务包2','每周2次',CURDATE(),CURDATE()+INTERVAL 90 DAY,'暂停')""",
                (elder_id,),
            )
            cur.execute(
                "UPDATE assessment SET assess_date=%s, expire_date=%s WHERE elder_id=%s",
                (last_year, last_year + dt.timedelta(days=365), elder_id),
            )
            # 过期自动暂停（与 sp_pause_expired_plans 同规则）
            assert dao.pause_expired_plans(cur)["paused_plans"] >= 1
            cur.execute("SELECT status FROM care_plan WHERE elder_id=%s", (elder_id,))
            assert cur.fetchone()["status"] == "暂停"
            with pytest.raises(care_plan_dao.CarePlanError, match="评估缺失或已过期"):
                care_plan_dao.update_care_plan(cur, plan_id, {"status": "生效"})
            with pytest.raises(pymysql.err.OperationalError) as trigger_error:
                cur.execute(
                    "UPDATE care_plan SET status='生效' WHERE plan_id=%s",
                    (plan_id,),
                )
            assert trigger_error.value.args[0] == 1644

            # 复评 → 计划恢复 + 新评估一年有效
            res = dao.record_assessment(cur, elder_id, {"score": 88}, "测试评估员")
            assert res["ability_level"] == "能力完好"
            assert res["resumed_plans"] == 1
            cur.execute(
                "SELECT status, COUNT(*) AS plan_count FROM care_plan WHERE elder_id=%s GROUP BY status",
                (elder_id,),
            )
            statuses = {row["status"]: row["plan_count"] for row in cur.fetchall()}
            assert statuses == {"生效": 1, "暂停": 1}
        conn.commit()
    finally:
        _cleanup(conn, elder_ids=[elder_id])
        conn.close()


def test_05_transaction_rollback_atomicity():
    """事务回滚用例：同一事务内建档+评估后触发失败并回滚，两类记录都不残留。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            payload_a = _new_elder_payload()
            elder_id = dao.create_elder(cur, payload_a)["elder_id"]
            dao.record_assessment(cur, elder_id, {"score": 66}, "测试评估员")

            # 同一事务内第二条建档撞身份证 → IntegrityError → 整体回滚
            with pytest.raises(pymysql.err.IntegrityError):
                dao.create_elder(cur, dict(payload_a, name="重复二号"))

        conn.rollback()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM elder WHERE elder_id=%s", (elder_id,))
            assert cur.fetchone()["n"] == 0, "回滚后不应残留老人档案"
            cur.execute("SELECT COUNT(*) AS n FROM assessment WHERE elder_id=%s", (elder_id,))
            assert cur.fetchone()["n"] == 0, "回滚后不应残留评估记录"
        conn.commit()
    finally:
        conn.close()


def test_06_new_views_return_data():
    """新视图可用：独居未评估清单（种子含过期/未评估独居老人）与各社区等级分布。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            solitary = dao.list_unassessed_solitary(cur)
            assert len(solitary) > 0
            for row in solitary:
                assert "独居" in (row["special_tag"] or "")
                assert row["assess_state"]  # 从未评估 / 已逾期 N 天
                assert "********" in row["id_masked"]  # 身份证已脱敏

            dist = dao.list_community_distribution(cur)
            assert len(dist) > 0
            for row in dist:
                levels = (row["level_intact"] or 0) + (row["level_mild"] or 0) \
                    + (row["level_moderate"] or 0) + (row["level_severe"] or 0)
                assert levels + (row["unassessed"] or 0) == row["total_elders"]
    finally:
        conn.close()


def test_07_care_plan_dao_crud():
    """照护计划：建档后可创建、修改状态、查询列表并校验日期。"""
    conn = _connect()
    elder_id = None
    plan_id = None
    try:
        with conn.cursor() as cur:
            elder_id = dao.create_elder(cur, _new_elder_payload())["elder_id"]
            dao.record_assessment(cur, elder_id, {"score": 90}, "测试评估员")
            created = care_plan_dao.create_care_plan(cur, {
                "elder_id": elder_id,
                "package_name": "助洁关怀包",
                "frequency": "每周3次",
                "start_date": "2026-11-18",
                "end_date": "2027-02-18",
                "caregiver_id": 1,
                "status": "生效",
            })
            plan_id = created["plan_id"]
            with pytest.raises(care_plan_dao.CarePlanError, match="已有生效的照护计划"):
                care_plan_dao.create_care_plan(cur, {
                    "elder_id": elder_id,
                    "package_name": "失能照护包",
                    "frequency": "每周1次",
                    "start_date": "2026-11-18",
                    "end_date": "2027-02-18",
                    "status": "生效",
                })
            result = care_plan_dao.update_care_plan(cur, plan_id, {
                "frequency": "每周2次",
                "status": "暂停",
            })
            assert result["updated"] == 1
            second = care_plan_dao.create_care_plan(cur, {
                "elder_id": elder_id,
                "package_name": "失能照护包",
                "frequency": "每周1次",
                "start_date": "2026-11-18",
                "end_date": "2027-02-18",
                "status": "生效",
            })
            with pytest.raises(care_plan_dao.CarePlanError, match="已有生效的照护计划"):
                care_plan_dao.update_care_plan(cur, plan_id, {"status": "生效"})
            plans = care_plan_dao.list_care_plans(cur, elder_id)
            assert len(plans) == 2
            assert {plan["plan_id"]: plan["status"] for plan in plans} == {
                plan_id: "暂停",
                second["plan_id"]: "生效",
            }

            with pytest.raises(care_plan_dao.CarePlanError):
                care_plan_dao.create_care_plan(cur, {
                    "elder_id": elder_id,
                    "package_name": "自定义服务包",
                    "frequency": "每周1次",
                    "start_date": "2026-11-01",
                    "end_date": "2026-12-01",
                })
            with pytest.raises(care_plan_dao.CarePlanError, match="结束日期不能早于开始日期"):
                care_plan_dao.create_care_plan(cur, {
                    "elder_id": elder_id,
                    "package_name": "助洁关怀包",
                    "frequency": "每周1次",
                    "start_date": "2026-12-01",
                    "end_date": "2026-11-01",
                })
        conn.commit()
    finally:
        with conn.cursor() as cur:
            if plan_id:
                cur.execute("DELETE FROM care_plan WHERE plan_id=%s", (plan_id,))
        _cleanup(conn, elder_ids=[elder_id])
        conn.commit()
        conn.close()


def test_expired_plans_pause_once_for_authenticated_api_requests(monkeypatch):
    """登录后的首个 API 请求触发暂停过程，同日后续请求不重复执行。"""
    monkeypatch.setattr(appmod, "_expired_plans_checked_on", None)
    conn = Mock()
    cursor = Mock()
    conn.cursor.return_value = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = {"paused_plans": 1}
    monkeypatch.setattr(appmod, "get_conn", lambda: conn)

    client = appmod.app.test_client()
    assert client.get("/api/me").status_code == 401
    conn.cursor.assert_not_called()

    with client.session_transaction() as user_session:
        user_session.update(uid=1, name="测试管理员", role="社区管理员")

    assert client.get("/api/me").status_code == 200
    assert client.get("/api/me").status_code == 200
    cursor.execute.assert_called_once_with("CALL sp_pause_expired_plans()")
    conn.commit.assert_called_once()
    conn.close.assert_called_once()
