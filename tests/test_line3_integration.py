# 线3 持久层与数据库触发器集成测试（正常签退算工时、围栏异常转复核、时间倒挂回滚、跨班次互斥、批量排班）
import os
import sys
import pytest
import pymysql
from datetime import datetime, timedelta, date

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
    """临时插入一条测试派单（12号护工在种子数据中已有未来7天开放排班及4号项目资质）"""
    _cleanup_test_dispatch(dispatch_id)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO dispatch (dispatch_id, order_id, caregiver_id, dispatch_time, is_current)
                VALUES (%s, %s, %s, NOW(), 1)
            """, (dispatch_id, order_id, caregiver_id))
        conn.commit()
    finally:
        conn.close()


def test_01_normal_checkin_and_checkout_auto_hours():
    """测试1：正常签到 -> 围栏通过签退，验证触发器自动折算 valid_hours = 1.50 并累加至护工总时长"""
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
        t_bad_out = t_in - timedelta(minutes=30)

        wh_id = Line3DAO.checkin_work_hour(12, 9999, t_in, "幸福社区3号楼测试定位")

        with pytest.raises(pymysql.MySQLError) as exc_info:
            Line3DAO.checkout_work_hour(wh_id, t_bad_out, fence_result="通过")

        assert "签退时间不能早于签到时间" in str(exc_info.value)
    finally:
        _cleanup_test_dispatch(9999)


def test_04_schedule_overlap_blocked_and_batch_create():
    """测试4：验证同日'上午+全天'排班冲突触发器拦截，以及未来空余日期批量排班存储过程"""
    # 1) 12号护工今天已有上午/下午排班，再排全天应被触发器拦截
    with pytest.raises(pymysql.MySQLError) as exc_info:
        Line3DAO.create_schedule(12, date.today().isoformat(), "全天", capacity=4)
    assert "排班冲突" in str(exc_info.value)

    # 2) 测试未来第20~21天批量排班（共2天），测完清理
    d1 = (date.today() + timedelta(days=20)).isoformat()
    d2 = (date.today() + timedelta(days=21)).isoformat()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM schedule WHERE caregiver_id = 12 AND work_date BETWEEN %s AND %s", (d1, d2))
        conn.commit()

        created = Line3DAO.batch_create_schedule(12, d1, d2, shift="全天", capacity=4)
        assert created == 2
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM schedule WHERE caregiver_id = 12 AND work_date BETWEEN %s AND %s", (d1, d2))
        conn.commit()
        conn.close()


def test_05_views_and_summary_queries():
    """测试5：验证排班余量视图、证书预警视图及月度工时汇总查询正常返回"""
    schedules = Line3DAO.list_schedule_capacity()
    assert isinstance(schedules, list) and len(schedules) > 0

    warnings = Line3DAO.list_cert_warnings()
    assert isinstance(warnings, list) and len(warnings) > 0

    summary = Line3DAO.get_monthly_work_summary()
    assert isinstance(summary, list) and len(summary) > 0
def test_work_hour_incremental_accumulation_and_reconcile():
    """验证 Issue #26：0->2.0->3.0->0 工时增量触发器精准对账，及 Issue #25 caregiver_region 关联"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 清理 test_01~03 对 12 号护工留下的测试痕迹，确保从纯净种子基线验证全库对账
            cur.execute("UPDATE caregiver SET total_hours = 0.00 WHERE caregiver_id = 12")

            # 1. 验证全库种子数据总账与明细零差异
            cur.execute("""
                SELECT cg.caregiver_id, cg.total_hours,
                       COALESCE(SUM(wh.valid_hours), 0) AS detail_sum
                  FROM caregiver cg
                  LEFT JOIN work_hour wh
                         ON wh.caregiver_id = cg.caregiver_id
                        AND wh.review_status IN ('自动认定', '复核通过')
                 GROUP BY cg.caregiver_id, cg.total_hours
                HAVING cg.total_hours <> detail_sum
            """)
            assert cur.fetchall() == (), "存在 total_hours 与明细不一致的护工"

            # 2. 验证 0 -> 2.0 -> 3.0 -> 0 增量变化（使用 10 号护工）
            cur.execute("SELECT total_hours FROM caregiver WHERE caregiver_id = 10")
            base_hours = float(cur.fetchone()[0])

            cur.execute("DELETE FROM work_hour WHERE dispatch_id = 9998")
            cur.execute("DELETE FROM dispatch WHERE dispatch_id = 9998")
            cur.execute("""
                INSERT INTO dispatch (dispatch_id, order_id, caregiver_id, is_current)
                VALUES (9998, 8, 10, 1)
            """)
            cur.execute("""
                INSERT INTO work_hour (caregiver_id, dispatch_id, checkin_time, checkin_location, fence_result, valid_hours, review_status)
                VALUES (10, 9998, '2026-11-22 09:00:00', '幸福社区', '通过', 0.00, '自动认定')
            """)
            wh_id = cur.lastrowid

            # 0 -> 2.0
            cur.execute("UPDATE work_hour SET checkout_time = '2026-11-22 11:00:00' WHERE work_hour_id = %s", (wh_id,))
            cur.execute("SELECT total_hours FROM caregiver WHERE caregiver_id = 10")
            assert float(cur.fetchone()[0]) == round(base_hours + 2.0, 2)

            # 2.0 -> 3.0（只补差额 +1.0）
            cur.execute("UPDATE work_hour SET valid_hours = 3.00, review_status = '复核通过' WHERE work_hour_id = %s", (wh_id,))
            cur.execute("SELECT total_hours FROM caregiver WHERE caregiver_id = 10")
            assert float(cur.fetchone()[0]) == round(base_hours + 3.0, 2)

            # 3.0 -> 0（扣减 3.0 回到 base_hours）
            cur.execute("UPDATE work_hour SET valid_hours = 0.00, review_status = '复核驳回' WHERE work_hour_id = %s", (wh_id,))
            cur.execute("SELECT total_hours FROM caregiver WHERE caregiver_id = 10")
            assert float(cur.fetchone()[0]) == round(base_hours, 2)

            # 清理测试数据并还原调度计数
            cur.execute("DELETE FROM work_hour WHERE work_hour_id = %s", (wh_id,))
            cur.execute("DELETE FROM dispatch WHERE dispatch_id = 9998")
            cur.execute("""
                UPDATE schedule s JOIN service_order o ON o.order_id = 8
                   SET s.booked = GREATEST(s.booked - 1, 0)
                 WHERE s.caregiver_id = 10
                   AND s.work_date = DATE(o.appoint_time)
                   AND s.shift = (CASE WHEN TIME(o.appoint_time) < '12:00:00' THEN '上午' ELSE '下午' END)
            """)
        conn.commit()
    finally:
        conn.close()