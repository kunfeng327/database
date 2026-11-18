# -*- coding: utf-8 -*-
"""服务下单、派单和改派的持久层。

路由层只负责 HTTP、登录和权限；本模块负责订单业务规则和 SQL，便于单元测试、复用和事务调用。
"""
import datetime as dt


class OrderError(Exception):
    """订单业务规则错误。"""


def normalize_channel(role, channel):
    """家属只能使用家属端渠道，社区管理员默认使用社区代下单。"""
    channel = channel or "社区代下单"
    if role == "家属" and channel != "家属端":
        return "家属端"
    return channel


def parse_appoint_time(value):
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError) as exc:
        raise OrderError("预约时间格式应为 YYYY-MM-DD HH:MM") from exc


def create_order(cur, elder_id, item_id, appoint_time, channel, role):
    """校验老人档案和评估有效期，按服务项目计算金额并创建订单。"""
    parse_appoint_time(appoint_time)
    channel = normalize_channel(role, channel)
    cur.execute("SELECT status, address FROM elder WHERE elder_id=%s", elder_id)
    elder = cur.fetchone()
    if not elder:
        raise OrderError("老人档案不存在")
    if elder["status"] != "正常":
        raise OrderError(f"档案状态为「{elder['status']}」，不允许下单")
    cur.execute("SELECT MAX(expire_date) AS exp FROM assessment WHERE elder_id=%s", elder_id)
    assessment = cur.fetchone()
    if not assessment or not assessment["exp"]:
        raise OrderError("该老人尚未做能力评估，请先安排评估")
    if assessment["exp"] < dt.date.today():
        raise OrderError(f"能力评估已于 {assessment['exp'].strftime('%Y-%m-%d')} 过期，须复评后才可下单")
    cur.execute("SELECT guide_price, std_hours, unit FROM service_item WHERE item_id=%s", item_id)
    item = cur.fetchone()
    if not item:
        raise OrderError("服务项目不存在")
    amount = round(float(item["guide_price"]) * (float(item["std_hours"]) if item["unit"] == "小时" else 1), 2)
    cur.execute(
        """INSERT INTO service_order
           (elder_id, item_id, appoint_time, address, channel, amount)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (elder_id, item_id, appoint_time, elder["address"], channel, amount),
    )
    return {"order_id": cur.lastrowid, "amount": amount}


def list_orders(cur, role, elder_id=None, caregiver_id=None):
    sql = """SELECT o.order_id, e.name AS elder_name, c.name AS community,
                     si.name AS item_name, si.type AS item_type, si.subsidizable,
                     o.appoint_time, o.channel, o.amount, o.status, o.created_at,
                     d.dispatch_id, d.caregiver_id, d.confirmed, cg.name AS caregiver_name,
                     d.arrive_time, d.leave_time, d.service_note
              FROM service_order o
              JOIN elder e ON e.elder_id=o.elder_id
              JOIN community c ON c.community_id=e.community_id
              JOIN service_item si ON si.item_id=o.item_id
              LEFT JOIN dispatch d ON d.order_id=o.order_id AND d.is_current=1
              LEFT JOIN caregiver cg ON cg.caregiver_id=d.caregiver_id"""
    args = ()
    if role == "家属":
        sql += " WHERE o.elder_id=%s"
        args = (elder_id,)
    elif role == "护工":
        sql += " WHERE d.caregiver_id=%s"
        args = (caregiver_id,)
    cur.execute(sql + " ORDER BY o.order_id DESC", args)
    return cur.fetchall()


def recommend_caregivers(cur, order_id):
    cur.execute("""SELECT cg.caregiver_id, cg.name, cg.agency, cg.cert_type, cg.rating,
                         s.schedule_id, s.shift, s.booked, s.capacity
                    FROM service_order o
                    JOIN elder e ON e.elder_id=o.elder_id
                    JOIN community c ON c.community_id=e.community_id
                    JOIN schedule s ON s.work_date=DATE(o.appoint_time)
                     AND s.shift=(CASE WHEN TIME(o.appoint_time)<'12:00:00' THEN '上午' ELSE '下午' END)
                     AND s.status='开放' AND s.booked<s.capacity
                    JOIN caregiver cg ON cg.caregiver_id=s.caregiver_id
                   WHERE o.order_id=%s AND cg.on_duty='在岗'
                     AND cg.cert_expire>=DATE(o.appoint_time)
                     AND FIND_IN_SET(c.name,REPLACE(cg.service_regions,' ',''))>0
                   ORDER BY cg.rating DESC,s.booked ASC LIMIT 6""", order_id)
    return cur.fetchall()


def dispatch_order(cur, order_id, caregiver_id):
    cur.execute("SELECT status FROM service_order WHERE order_id=%s FOR UPDATE", order_id)
    order = cur.fetchone()
    if not order:
        raise OrderError("订单不存在")
    if order["status"] != "待派单":
        raise OrderError(f"订单当前状态为「{order['status']}」，只有待派单订单可以派单")
    cur.execute("INSERT INTO dispatch (order_id, caregiver_id) VALUES (%s,%s)", (order_id, caregiver_id))
    dispatch_id = cur.lastrowid
    cur.execute("UPDATE service_order SET status='已派单' WHERE order_id=%s", order_id)
    return {"dispatch_id": dispatch_id}


def complete_dispatch(cur, dispatch_id, note, role, caregiver_id):
    cur.execute("SELECT caregiver_id FROM dispatch WHERE dispatch_id=%s", dispatch_id)
    dispatch = cur.fetchone()
    if not dispatch:
        raise OrderError("派单不存在")
    if role == "护工" and dispatch["caregiver_id"] != caregiver_id:
        raise OrderError("无权限：该派单不属于当前护工")
    cur.execute("""UPDATE dispatch SET arrive_time=COALESCE(arrive_time,NOW()-INTERVAL 90 MINUTE),
                         leave_time=NOW(), service_note=%s, confirmed=1
                         WHERE dispatch_id=%s AND confirmed=0""", (note, dispatch_id))
    if cur.rowcount == 0:
        raise OrderError("派单不存在或此前已确认完成")
    return {"dispatch_id": dispatch_id}


def reassign_dispatch(cur, dispatch_id, reason):
    cur.execute("SELECT order_id FROM dispatch WHERE dispatch_id=%s AND is_current=1", dispatch_id)
    dispatch = cur.fetchone()
    if not dispatch:
        raise OrderError("派单不存在或已不是当前派单")
    cur.execute("UPDATE dispatch SET is_current=0,reassign_reason=%s WHERE dispatch_id=%s",
                (reason or "未注明原因", dispatch_id))
    cur.execute("UPDATE service_order SET status='待派单' WHERE order_id=%s AND status='已派单'",
                dispatch["order_id"])
    cur.execute("""UPDATE schedule s JOIN service_order o ON o.order_id=%s
                    SET s.booked=s.booked-1
                    WHERE s.caregiver_id=(SELECT caregiver_id FROM dispatch WHERE dispatch_id=%s)
                      AND s.work_date=DATE(o.appoint_time)
                      AND s.shift=(CASE WHEN TIME(o.appoint_time)<'12:00:00' THEN '上午' ELSE '下午' END)""",
                (dispatch["order_id"], dispatch_id))
    return {"order_id": dispatch["order_id"]}


def checkin_dispatch(cur, dispatch_id, checkin_time, location, role, caregiver_id):
    """护工上门签到：写工时记录(work_hour)、回填派单 arrive_time、订单转「服务中」。

    与 line3_dao.checkin_work_hour 的区别：本函数游标注入、可参与路由事务，
    并同步订单状态机（已派单 → 服务中），供页面演示完整闭环。
    """
    cur.execute("""SELECT d.caregiver_id, d.order_id, d.is_current, o.status
                     FROM dispatch d JOIN service_order o ON o.order_id = d.order_id
                    WHERE d.dispatch_id=%s""", (dispatch_id,))
    d = cur.fetchone()
    if not d:
        raise OrderError("派单不存在")
    if d["is_current"] != 1:
        raise OrderError("该派单已不是当前派单（可能已改派）")
    if role == "护工" and d["caregiver_id"] != caregiver_id:
        raise OrderError("无权限：该派单不属于当前护工")
    if d["status"] not in ("已派单", "服务中"):
        raise OrderError(f"订单当前状态为「{d['status']}」，只有已派单订单可以签到")
    cur.execute("SELECT work_hour_id FROM work_hour WHERE dispatch_id=%s", (dispatch_id,))
    if cur.fetchone():
        raise OrderError("该派单已签到过，请直接签退结算工时")

    cur.execute(
        """INSERT INTO work_hour
           (caregiver_id, dispatch_id, checkin_time, checkin_location,
            fence_result, valid_hours, review_status)
           VALUES (%s,%s,%s,%s,'通过',0.00,'自动认定')""",
        (d["caregiver_id"], dispatch_id, checkin_time, location or "上门签到"),
    )
    work_hour_id = cur.lastrowid  # INSERT 后立即保存
    cur.execute("UPDATE dispatch SET arrive_time=%s WHERE dispatch_id=%s",
                (checkin_time, dispatch_id))
    cur.execute("UPDATE service_order SET status='服务中' WHERE order_id=%s AND status='已派单'",
                (d["order_id"],))
    return {"work_hour_id": work_hour_id, "order_id": d["order_id"], "status": "服务中"}


def checkout_dispatch(cur, dispatch_id, checkout_time, fence_result, note, role, caregiver_id):
    """护工离场签退：触发器自动按分钟差结算有效工时（围栏异常转人工复核），
    派单确认完成 → 触发器回写订单「已完成」。"""
    cur.execute("""SELECT d.caregiver_id, d.order_id, d.is_current, d.confirmed, o.status
                     FROM dispatch d JOIN service_order o ON o.order_id = d.order_id
                    WHERE d.dispatch_id=%s""", (dispatch_id,))
    d = cur.fetchone()
    if not d:
        raise OrderError("派单不存在")
    if d["is_current"] != 1:
        raise OrderError("该派单已不是当前派单（可能已改派）")
    if role == "护工" and d["caregiver_id"] != caregiver_id:
        raise OrderError("无权限：该派单不属于当前护工")
    if d["confirmed"] == 1:
        raise OrderError("该派单已确认完成，不能重复签退")
    cur.execute("""SELECT work_hour_id FROM work_hour
                    WHERE dispatch_id=%s AND checkout_time IS NULL""", (dispatch_id,))
    wh = cur.fetchone()
    if not wh:
        raise OrderError("该派单尚未签到，请先签到再签退")

    cur.execute(
        """UPDATE work_hour SET checkout_time=%s, fence_result=%s WHERE work_hour_id=%s""",
        (checkout_time, fence_result, wh["work_hour_id"]),
    )  # tr_work_hour_before_update 自动结算 valid_hours / 复核状态
    cur.execute("SELECT valid_hours, review_status FROM work_hour WHERE work_hour_id=%s",
                (wh["work_hour_id"],))
    settled = cur.fetchone()
    cur.execute("""UPDATE dispatch SET leave_time=%s, service_note=%s, confirmed=1
                    WHERE dispatch_id=%s""", (checkout_time, note or "服务完成", dispatch_id))
    # confirmed 0→1 触发 tr_dispatch_after_confirm：订单「服务中/已派单」→「已完成」
    return {
        "dispatch_id": dispatch_id,
        "valid_hours": float(settled["valid_hours"]),
        "review_status": settled["review_status"],
    }
