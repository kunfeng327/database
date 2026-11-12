# -*- coding: utf-8 -*-
"""社区居家养老智慧服务平台 · 演示后端（Flask + PyMySQL）

启动：python app.py  →  http://127.0.0.1:5000
数据库：elder_care（由 sql/ 目录脚本初始化）
"""
import datetime as dt
import decimal
from pathlib import Path

import pymysql
from flask import Flask, jsonify, request, send_file

from db import DB_CONFIG

app = Flask(__name__)
FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


# ------------------------------------------------------------------ 工具
def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)


def jsonable(row):
    """把 MySQL 返回的 datetime/Decimal 转成前端友好的字符串/数字。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, dt.datetime):
            out[k] = v.strftime("%Y-%m-%d %H:%M")
        elif isinstance(v, dt.date):
            out[k] = v.strftime("%Y-%m-%d")
        elif isinstance(v, dt.timedelta):
            out[k] = int(v.total_seconds())
        elif isinstance(v, decimal.Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def query_all(sql, args=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            return [jsonable(r) for r in cur.fetchall()]
    finally:
        conn.close()


class BizError(Exception):
    """业务规则不满足（由本文件或数据库触发器 SIGNAL 抛出）。"""


def run_in_transaction(fn):
    """在单个事务里执行 fn(cursor)，返回其结果；BizError/触发器错误都会回滚。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            result = fn(cur)
        conn.commit()
        return result
    except pymysql.err.OperationalError as e:
        conn.rollback()
        # MySQL SIGNAL SQLSTATE '45000' → errno 1644，消息来自触发器
        if e.args and e.args[0] == 1644:
            raise BizError(e.args[1])
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.errorhandler(BizError)
def handle_biz(e):
    return jsonify({"ok": False, "msg": str(e)}), 400


@app.errorhandler(Exception)
def handle_500(e):
    if isinstance(e, pymysql.err.IntegrityError) and e.args[0] == 1062:
        return jsonify({"ok": False, "msg": "违反唯一性约束（可能是重复申报/重复排班）"}), 409
    return jsonify({"ok": False, "msg": f"服务器错误：{e}"}), 500


# ------------------------------------------------------------------ 页面
@app.get("/")
def index():
    return send_file(FRONTEND)


# ------------------------------------------------------------------ 基础数据
@app.get("/api/items")
def items():
    return jsonify({"ok": True, "data": query_all(
        "SELECT * FROM service_item ORDER BY item_id")})


@app.get("/api/schedules")
def schedules():
    return jsonify({"ok": True, "data": query_all(
        "SELECT * FROM v_schedule_capacity ORDER BY work_date, shift, caregiver_name")})


@app.get("/api/pending-orders")
def pending_orders():
    return jsonify({"ok": True, "data": query_all(
        "SELECT * FROM v_pending_dispatch_orders ORDER BY waited_min DESC")})


# ------------------------------------------------------------------ 总览
@app.get("/api/stats")
def stats():
    rows = query_all("""
        SELECT
          (SELECT COUNT(*) FROM elder WHERE status='正常') AS elders_normal,
          (SELECT COUNT(*) FROM service_order WHERE status IN ('待派单','已派单','服务中')) AS orders_active,
          (SELECT COUNT(*) FROM v_pending_dispatch_orders WHERE timeout_flag='超时') AS orders_timeout,
          (SELECT COUNT(*) FROM care_plan p WHERE p.status='生效' AND
             (SELECT MAX(a.expire_date) FROM assessment a WHERE a.elder_id=p.elder_id) < CURDATE()
          ) AS plans_to_pause,
          (SELECT COUNT(*) FROM subsidy_claim WHERE status IN ('待审核','街道已审')) AS claims_in_progress
    """)
    return jsonify({"ok": True, "data": rows[0]})


# ------------------------------------------------------------------ 老人档案（视图 v_elder_assessment_plan）
@app.get("/api/elders")
def elders():
    return jsonify({"ok": True, "data": query_all(
        "SELECT * FROM v_elder_assessment_plan ORDER BY elder_id")})


# ------------------------------------------------------------------ 订单
@app.get("/api/orders")
def orders():
    return jsonify({"ok": True, "data": query_all("""
        SELECT o.order_id, e.name AS elder_name, c.name AS community,
               si.name AS item_name, si.type AS item_type, si.subsidizable,
               o.appoint_time, o.channel, o.amount, o.status, o.created_at,
               d.dispatch_id, d.confirmed, cg.name AS caregiver_name
        FROM service_order o
        JOIN elder e ON e.elder_id = o.elder_id
        JOIN community c ON c.community_id = e.community_id
        JOIN service_item si ON si.item_id = o.item_id
        LEFT JOIN dispatch d ON d.order_id = o.order_id AND d.is_current = 1
        LEFT JOIN caregiver cg ON cg.caregiver_id = d.caregiver_id
        ORDER BY o.order_id DESC""")})


@app.post("/api/orders")
def create_order():
    """下单：校验档案状态 + 评估有效期（评估过期不允许下单），金额按项目计价。"""
    body = request.get_json(force=True)
    elder_id, item_id = body["elder_id"], body["item_id"]
    appoint_time, channel = body["appoint_time"], body.get("channel", "社区代下单")
    try:
        dt.datetime.strptime(appoint_time, "%Y-%m-%d %H:%M")
    except ValueError:
        raise BizError("预约时间格式应为 YYYY-MM-DD HH:MM")

    def fn(cur):
        cur.execute("SELECT status, address FROM elder WHERE elder_id=%s", elder_id)
        elder = cur.fetchone()
        if not elder:
            raise BizError("老人档案不存在")
        if elder["status"] != "正常":
            raise BizError(f"档案状态为「{elder['status']}」，不允许下单")

        cur.execute("""SELECT MAX(expire_date) AS exp FROM assessment WHERE elder_id=%s""",
                    elder_id)
        row = cur.fetchone()
        if not row or not row["exp"]:
            raise BizError("该老人尚未做能力评估，请先安排评估")
        if row["exp"] < dt.date.today():
            raise BizError(f"能力评估已于 {row['exp'].strftime('%Y-%m-%d')} 过期，须复评后才可下单")

        cur.execute("""SELECT guide_price, std_hours, unit FROM service_item WHERE item_id=%s""",
                    item_id)
        item = cur.fetchone()
        if not item:
            raise BizError("服务项目不存在")
        amount = round(float(item["guide_price"]) *
                       (float(item["std_hours"]) if item["unit"] == "小时" else 1), 2)

        cur.execute("""INSERT INTO service_order (elder_id, item_id, appoint_time, address, channel, amount)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (elder_id, item_id, appoint_time, elder["address"], channel, amount))
        return {"order_id": cur.lastrowid, "amount": amount}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


# ------------------------------------------------------------------ 派单
@app.get("/api/orders/<int:order_id>/recommend")
def recommend(order_id):
    """推荐护工：在岗 + 证书有效 + 服务区域覆盖老人社区 + 当天该班次有余量。"""
    return jsonify({"ok": True, "data": query_all("""
        SELECT cg.caregiver_id, cg.name, cg.agency, cg.cert_type, cg.rating,
               s.schedule_id, s.shift, s.booked, s.capacity
        FROM service_order o
        JOIN elder e ON e.elder_id = o.elder_id
        JOIN community c ON c.community_id = e.community_id
        JOIN schedule s ON s.work_date = DATE(o.appoint_time)
                      AND s.shift = (CASE WHEN TIME(o.appoint_time) < '12:00:00' THEN '上午' ELSE '下午' END)
                      AND s.status='开放' AND s.booked < s.capacity
        JOIN caregiver cg ON cg.caregiver_id = s.caregiver_id
        WHERE o.order_id = %s
          AND cg.on_duty='在岗' AND cg.cert_expire >= DATE(o.appoint_time)
          AND FIND_IN_SET(c.name, REPLACE(cg.service_regions,' ','')) > 0
        ORDER BY cg.rating DESC, s.booked ASC
        LIMIT 6""", order_id)})


@app.post("/api/orders/<int:order_id>/dispatch")
def dispatch_order(order_id):
    """派单：事务内锁定订单 → 插入派单记录（触发器做容量/资质兜底校验）→ 回写订单状态。"""
    caregiver_id = request.get_json(force=True)["caregiver_id"]

    def fn(cur):
        cur.execute("""SELECT status FROM service_order WHERE order_id=%s FOR UPDATE""",
                    order_id)
        order = cur.fetchone()
        if not order:
            raise BizError("订单不存在")
        if order["status"] != "待派单":
            raise BizError(f"订单当前状态为「{order['status']}」，只有待派单订单可以派单")
        cur.execute("""INSERT INTO dispatch (order_id, caregiver_id) VALUES (%s,%s)""",
                    (order_id, caregiver_id))  # 触发器校验容量/资质，不通过则整体回滚
        dispatch_id = cur.lastrowid  # 须在 INSERT 后立即取，后续语句会覆盖该值
        cur.execute("""UPDATE service_order SET status='已派单' WHERE order_id=%s""", order_id)
        return {"dispatch_id": dispatch_id}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.post("/api/dispatches/<int:dispatch_id>/complete")
def complete_dispatch(dispatch_id):
    """服务完成：回填时间与服务记录、家属确认 → 触发器自动把订单置为已完成。"""
    note = request.get_json(force=True).get("service_note", "")

    def fn(cur):
        cur.execute("""UPDATE dispatch
                          SET arrive_time = COALESCE(arrive_time, NOW() - INTERVAL 90 MINUTE),
                              leave_time  = NOW(),
                              service_note = %s,
                              confirmed   = 1
                        WHERE dispatch_id=%s AND confirmed=0""", (note, dispatch_id))
        if cur.rowcount == 0:
            raise BizError("派单不存在或此前已确认完成")
        return {"dispatch_id": dispatch_id}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.post("/api/dispatches/<int:dispatch_id>/reassign")
def reassign(dispatch_id):
    """改派：保留原派单记录与原因，订单回到待派单，排班余量释放。"""
    reason = request.get_json(force=True).get("reason", "")

    def fn(cur):
        cur.execute("""SELECT order_id FROM dispatch WHERE dispatch_id=%s AND is_current=1""",
                    dispatch_id)
        d = cur.fetchone()
        if not d:
            raise BizError("派单不存在或已不是当前派单")
        cur.execute("""UPDATE dispatch SET is_current=0, reassign_reason=%s
                        WHERE dispatch_id=%s""", (reason or "未注明原因", dispatch_id))
        cur.execute("""UPDATE service_order SET status='待派单'
                        WHERE order_id=%s AND status='已派单'""", d["order_id"])
        # 释放该护工当班接单量（与 tr_dispatch_after_insert 对应）
        cur.execute("""UPDATE schedule s
                          JOIN service_order o ON o.order_id=%s
                           SET s.booked = s.booked - 1
                         WHERE s.caregiver_id = (SELECT caregiver_id FROM dispatch WHERE dispatch_id=%s)
                           AND s.work_date = DATE(o.appoint_time)
                           AND s.shift = (CASE WHEN TIME(o.appoint_time) < '12:00:00' THEN '上午' ELSE '下午' END)""",
                    (d["order_id"], dispatch_id))
        return {"order_id": d["order_id"]}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


# ------------------------------------------------------------------ 补贴
@app.get("/api/subsidy/policies")
def policies():
    return jsonify({"ok": True, "data": query_all("""
        SELECT p.policy_id, p.district, p.target_type, si.name AS item_name,
               p.standard, p.period, p.effective_from, p.effective_to
        FROM subsidy_policy p JOIN service_item si ON si.item_id=p.item_id
        WHERE CURDATE() BETWEEN p.effective_from AND p.effective_to
        ORDER BY p.policy_id""")})


@app.get("/api/subsidy/claims")
def claims():
    return jsonify({"ok": True, "data": query_all(
        "SELECT * FROM v_claim_progress ORDER BY claim_id DESC")})


@app.post("/api/subsidy/claims")
def create_claim():
    """补贴申报：对象类别匹配 + 只统计账期内已完成订单 + 唯一约束防重复申报。"""
    body = request.get_json(force=True)
    elder_id, policy_id, period = body["elder_id"], body["policy_id"], body["claim_period"]

    def fn(cur):
        cur.execute("""SELECT c.district, e.special_tag FROM elder e
                        JOIN community c ON c.community_id = e.community_id
                       WHERE e.elder_id=%s""", elder_id)
        elder = cur.fetchone()
        if not elder:
            raise BizError("老人档案不存在")
        cur.execute("""SELECT p.target_type, p.item_id, p.standard, p.district FROM subsidy_policy p
                        WHERE p.policy_id=%s""", policy_id)
        policy = cur.fetchone()
        if not policy:
            raise BizError("政策不存在或已失效")
        if policy["district"] != elder["district"]:
            raise BizError(f"政策适用区县为「{policy['district']}」，该老人所属区县为「{elder['district']}」")
        tags = elder["special_tag"] or ""
        if policy["target_type"] not in tags.split(","):
            raise BizError(f"该老人标签（{tags or '无'}）不符合政策的对象类别「{policy['target_type']}」")

        cur.execute("""SELECT order_id FROM service_order
                        WHERE elder_id=%s AND item_id=%s AND status='已完成'
                          AND DATE_FORMAT(appoint_time,'%%Y-%%m')=%s ORDER BY order_id""",
                    (elder_id, policy["item_id"], period))
        orders = [r["order_id"] for r in cur.fetchall()]
        if not orders:
            raise BizError("该账期内没有符合条件的已完成订单，缺少记录不予申报")

        amount = round(len(orders) * float(policy["standard"]), 2)
        cur.execute("""INSERT INTO subsidy_claim (elder_id, policy_id, claim_period, order_ids, amount)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (elder_id, policy_id, period, ",".join(map(str, orders)), amount))
        return {"claim_id": cur.lastrowid, "amount": amount, "order_ids": orders}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.post("/api/subsidy/claims/<int:claim_id>/audit")
def audit_claim(claim_id):
    """审核流转：待审核→街道已审→已拨付，或任意状态→已驳回。"""
    action = request.get_json(force=True)["action"]
    flow = {"approve": ("待审核", "街道已审"), "pay": ("街道已审", "已拨付"),
            "reject": (None, "已驳回")}

    def fn(cur):
        cur.execute("SELECT status FROM subsidy_claim WHERE claim_id=%s", claim_id)
        row = cur.fetchone()
        if not row:
            raise BizError("申报不存在")
        if action not in flow:
            raise BizError("action 只能是 approve / pay / reject")
        frm, to = flow[action]
        if frm and row["status"] != frm:
            raise BizError(f"当前状态「{row['status']}」，不能执行 {action}（应从「{frm}」流转）")
        cur.execute("""UPDATE subsidy_claim SET status=%s, reviewer=%s
                        WHERE claim_id=%s""", (to, "街道审核员(演示)", claim_id))
        return {"claim_id": claim_id, "status": to}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


# ------------------------------------------------------------------ 运维（存储过程）
@app.get("/api/maintenance/expired-preview")
def expired_preview():
    return jsonify({"ok": True, "data": query_all("""
        SELECT p.plan_id, e.name AS elder_name, p.package_name, p.status, a.expire_date
        FROM care_plan p
        JOIN elder e ON e.elder_id = p.elder_id
        JOIN (SELECT elder_id, MAX(assessment_id) aid FROM assessment GROUP BY elder_id) x
             ON x.elder_id = p.elder_id
        JOIN assessment a ON a.assessment_id = x.aid
        WHERE p.status='生效' AND a.expire_date < CURDATE()""")})


@app.post("/api/maintenance/pause-expired-plans")
def pause_expired_plans():
    """调用存储过程 sp_pause_expired_plans：评估到期的照护计划自动暂停。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("CALL sp_pause_expired_plans()")
            row = cur.fetchone()
        conn.commit()
        return jsonify({"ok": True, "data": jsonable(row)})
    finally:
        conn.close()


if __name__ == "__main__":
    print("养老服务平台演示后端已启动 → http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
