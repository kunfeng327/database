# src/backend/line3_dao.py
# 线3（护工与排班）数据库持久层 DAO
import pymysql
import pymysql
from db import DB_CONFIG

def get_conn():
    return pymysql.connect(**DB_CONFIG)


class Line3DAO:
    """护工档案、排班容量与工时签到签退持久层操作"""

    @staticmethod
    def list_schedule_capacity(work_date=None):
        """1. 查询护工未来7天开放排班及剩余接单量（调用视图 v_schedule_capacity）"""
        conn = get_conn()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                if work_date:
                    sql = "SELECT * FROM v_schedule_capacity WHERE work_date = %s ORDER BY remaining DESC"
                    cur.execute(sql, (work_date,))
                else:
                    sql = "SELECT * FROM v_schedule_capacity ORDER BY work_date ASC, remaining DESC"
                    cur.execute(sql)
                return cur.fetchall()
        finally:
            conn.close()

    @staticmethod
    def list_cert_warnings():
        """2. 查询证书已过期或30天内即将到期的护工预警清单（调用视图 v_caregiver_cert_warning）"""
        conn = get_conn()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute("SELECT * FROM v_caregiver_cert_warning")
                return cur.fetchall()
        finally:
            conn.close()

    @staticmethod
    def create_schedule(caregiver_id, work_date, shift, capacity=4):
        """3. 机构负责人新增排班（受唯一约束 uk_sched 保护，事务提交）"""
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                sql = """
                    INSERT INTO schedule (caregiver_id, work_date, shift, capacity, booked, status)
                    VALUES (%s, %s, %s, %s, 0, '开放')
                """
                cur.execute(sql, (caregiver_id, work_date, shift, capacity))
                new_id = cur.lastrowid
            conn.commit()
            return new_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def checkin_work_hour(caregiver_id, dispatch_id, checkin_time, checkin_location):
        """4. 护工上门签到（写入 work_hour 初始记录，同时将派单到达时间与订单状态同步）"""
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # 写入工时签到记录
                sql_wh = """
                    INSERT INTO work_hour (caregiver_id, dispatch_id, checkin_time, checkin_location, fence_result, valid_hours, review_status)
                    VALUES (%s, %s, %s, %s, '通过', 0.00, '自动认定')
                """
                cur.execute(sql_wh, (caregiver_id, dispatch_id, checkin_time, checkin_location))
                wh_id = cur.lastrowid

                # 同步更新派单表上门时间
                cur.execute("UPDATE dispatch SET arrive_time = %s WHERE dispatch_id = %s", (checkin_time, dispatch_id))
            conn.commit()
            return wh_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def checkout_work_hour(work_hour_id, checkout_time, fence_result='通过'):
        """5. 护工离场签退（触发数据库触发器 tr_work_hour_before_update 自动算工时或转人工复核）"""
        conn = get_conn()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                sql = """
                    UPDATE work_hour
                       SET checkout_time = %s,
                           fence_result = %s
                     WHERE work_hour_id = %s
                """
                cur.execute(sql, (checkout_time, fence_result, work_hour_id))

                # 回查触发器计算后的最新结果
                cur.execute("SELECT * FROM work_hour WHERE work_hour_id = %s", (work_hour_id,))
                result = cur.fetchone()
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def get_monthly_work_summary():
        """6. 护工月度有效工时与质量综合汇总（多表聚合查询）"""
        conn = get_conn()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                sql = """
                    SELECT cg.caregiver_id,
                           cg.name AS caregiver_name,
                           cg.agency,
                           COUNT(DISTINCT wh.work_hour_id) AS service_count,
                           COALESCE(SUM(wh.valid_hours), 0) AS total_valid_hours
                    FROM caregiver cg
                    LEFT JOIN work_hour wh
                           ON wh.caregiver_id = cg.caregiver_id
                          AND wh.review_status IN ('自动认定', '复核通过')
                    WHERE cg.on_duty = '在岗'
                    GROUP BY cg.caregiver_id, cg.name, cg.agency
                    ORDER BY total_valid_hours DESC
                """
                cur.execute(sql)
                return cur.fetchall()
        finally:
            conn.close()