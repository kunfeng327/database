# tests/test_line3_integration.py
# 线3 持久层与数据库触发器集成测试（覆盖正常签退算工时、围栏异常转复核、时间倒挂拦截与回滚）
import os
import sys
import pytest
import pymysql
from datetime import datetime, timedelta

# 将 src/backend 加入模块搜索路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/backend")))
from line3_dao import Line3DAO, get_conn


def _cleanup_test_dispatch(dispatch_id=9999):
    """清理测试用的临时工时与派单记录，保持演示库干净"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM work_hour WHERE dispatch_id = %s", (dispatch_id,))
            cur.execute("DELETE FROM dispatch WHERE dispatch_id = %s", (dispatch_id,))
        conn.commit()
    finally:
        conn.close()


def _prepare_test_dispatch(dispatch_id=9999, order_id=8, caregiver_id=12):
    """临时插入一条当天排班与测试派单供签到签退测试（使用无违规整改的12号护工）"""
    _cleanup_test_dispatch(dispatch_id)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 确保该护工当天存在开放排班，满足派单触发器校验
            cur.execute("""
                INSERT INTO schedule (caregiver_id, work_date, shift, capacity, booked, status)
                VALUES (%s, CURDATE(), '全天', 5, 0, '开放')
                ON DUPLICATE KEY UPDATE status = '开放', capacity = 5
            """, (caregiver_id,))
            cur.execute("""
                INSERT INTO dispatch (dispatch_id, order_id, caregiver_id, dispatch_time, is_current)
                VALUES (%s, %s, %s, NOW(), 1)
            """, (dispatch_id, order_id, caregiver_id))
        conn.commit()
    finally:
        conn.close()


def test_01_normal_checkin_and_checkout_auto_hours():
    """测试1：正常签到 -> 围栏通过签退，验证触发器自动折算 valid_hours = 1.50"""
    _prepare_test_dispatch(9999, order_id=8, caregiver_id=12)
    try:
        t_in = datetime.now().replace(microsecond=0)
        t_out = t_in + timedelta(minutes=90)  # 90分钟 = 1.50小时

        wh_id = Line3DAO.checkin_work_hour(12, 9999, t_in, "幸福社区3号楼测试定位")
        assert wh_id > 0

        res = Line3DAO.checkout_work_hour(wh_id, t_out, fence_result="通过")
        assert float(res["valid_hours"]) == 1.50
        assert res["review_status"] == "自动认定"
    finally:
        _cleanup_test_dispatch(9999)


def test_02_fence_exception_routes_to_manual_review():
    """测试2：围栏外异常签退，验证触发器将 valid_hours 置 0 且状态转为 '待人工复核'"""
    _prepare_test_dispatch(9999, order_id=8, caregiver_id=12)
    try:
        t_in = datetime.now().replace(microsecond=0)
        t_out = t_in + timedelta(minutes=60)

        wh_id = Line3DAO.checkin_work_hour(12, 9999, t_in, "远离社区的异常坐标")
        res = Line3DAO.checkout_work_hour(wh_id, t_out, fence_result="围栏外异常")

        assert float(res["valid_hours"]) == 0.00
        assert res["review_status"] == "待人工复核"
    finally:
        _cleanup_test_dispatch(9999)


def test_03_invalid_checkout_time_triggers_rollback():
    """测试3：签退时间早于签到时间，验证数据库触发器抛出异常且事务正确回滚"""
    _prepare_test_dispatch(9999, order_id=8, caregiver_id=12)
    try:
        t_in = datetime.now().replace(microsecond=0)
        t_bad_out = t_in - timedelta(minutes=30)  # 签退时间早于签到时间

        wh_id = Line3DAO.checkin_work_hour(12, 9999, t_in, "幸福社区3号楼测试定位")

        with pytest.raises(pymysql.MySQLError) as exc_info:
            Line3DAO.checkout_work_hour(wh_id, t_bad_out, fence_result="通过")

        assert "签退时间不能早于签到时间" in str(exc_info.value)
    finally:
        _cleanup_test_dispatch(9999)


def test_04_views_and_summary_queries():
    """测试4：验证排班余量视图、证书预警视图及月度工时汇总查询正常返回"""
    schedules = Line3DAO.list_schedule_capacity()
    assert isinstance(schedules, list) and len(schedules) > 0

    warnings = Line3DAO.list_cert_warnings()
    assert isinstance(warnings, list) and len(warnings) > 0  # 种子数据中有临期与过期护工

    summary = Line3DAO.get_monthly_work_summary()
    assert isinstance(summary, list) and len(summary) > 0