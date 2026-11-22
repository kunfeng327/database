# -*- coding: utf-8 -*-
"""社区居家养老智慧服务平台 · 演示后端（Flask + PyMySQL）

安全机制（对应任务书 3.4）：
  - 密码加盐哈希存储（SHA256(盐+密码)，生产环境应换 bcrypt）
  - 连续失败 5 次锁定 10 分钟
  - 会话 30 分钟超时（服务端 session）
  - RBAC：每个接口声明允许的角色，数据按角色过滤（家属只见自家、护工只见自己派单）

启动：python app.py  →  http://127.0.0.1:5000
演示账号（密码均为 123456）：shequ=社区管理员  jiashu/jiashu2=家属
                            hugong=护工  jigou=机构负责人  jianguan=监管人员
"""
import datetime as dt
import decimal
import hashlib
import os
import re
import threading
from functools import wraps
from pathlib import Path

import pymysql
from flask import Flask, jsonify, request, send_file, send_from_directory, session

from db import DB_CONFIG
from care_plan_dao import (
    CarePlanError,
    PACKAGE_NAMES,
    create_care_plan,
    list_care_plans,
    update_care_plan,
)
from elder_dao import (
    ElderError,
    create_elder as dao_create_elder,
    list_community_distribution,
    list_unassessed_solitary,
    record_assessment as dao_record_assessment,
    update_elder as dao_update_elder,
)
from line5_dao import (
    Line5Error,
    claim_orders_for,
    complete_inspection,
    create_manual_inspection,
    sample_completed_orders,
    split_claimable_orders,
    submit_rectification,
    transition_claim,
)
from order_dao import (
    OrderError,
    complete_dispatch as dao_complete_dispatch,
    create_order as dao_create_order,
    dispatch_order as dao_dispatch_order,
    list_orders as dao_list_orders,
    recommend_caregivers,
    reassign_dispatch,
)
from line3_dao import Line3DAO

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "elder-care-demo-key-2026")
app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(minutes=30)  # 会话超时
app.config["SESSION_COOKIE_HTTPONLY"] = True
FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
FRONTEND_DIR = FRONTEND.parent          # 前端资源根目录（css / js 与 index.html 同级）
_expired_plans_checked_on = None
_expired_plans_check_lock = threading.Lock()


# ------------------------------------------------------------------ 工具
def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)


def _pause_expired_plans_once_per_day():
    global _expired_plans_checked_on
    today = dt.date.today()
    if _expired_plans_checked_on == today:
        return
    with _expired_plans_check_lock:
        if _expired_plans_checked_on == today:
            return
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("CALL sp_pause_expired_plans()")
                cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _expired_plans_checked_on = today


@app.before_request
def pause_expired_plans_for_authenticated_api():
    if request.path.startswith("/api/") and session.get("uid"):
        _pause_expired_plans_once_per_day()


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
        if e.args and e.args[0] == 1644:  # 触发器 SIGNAL
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


@app.errorhandler(Line5Error)
def handle_line5(e):
    return jsonify({"ok": False, "msg": str(e)}), 400


@app.errorhandler(OrderError)
def handle_order_error(e):
    return jsonify({"ok": False, "msg": str(e)}), 400


@app.errorhandler(ElderError)
def handle_elder_error(e):
    return jsonify({"ok": False, "msg": str(e)}), 400


@app.errorhandler(CarePlanError)
def handle_care_plan_error(e):
    return jsonify({"ok": False, "msg": str(e)}), 400


@app.errorhandler(Exception)
def handle_500(e):
    if isinstance(e, pymysql.err.IntegrityError) and e.args[0] == 1062:
        return jsonify({"ok": False, "msg": "违反唯一性约束（可能是重复申报/重复排班）"}), 409
    return jsonify({"ok": False, "msg": f"服务器错误：{e}"}), 500


# ------------------------------------------------------------------ 认证与 RBAC
def hash_password(salt, password):
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def login_required(roles=None):
    """接口级权限控制：必须已登录；声明 roles 时校验角色。"""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("uid"):
                return jsonify({"ok": False, "msg": "请先登录"}), 401
            if roles and session.get("role") not in roles:
                return jsonify({"ok": False, "msg":
                                f"无权限：该操作需要「{'、'.join(roles)}」，当前角色为「{session.get('role')}」"}), 403
            return fn(*a, **kw)
        return wrapper
    return deco


@app.post("/api/login")
def login():
    body = request.get_json(force=True)
    username, password = body.get("username", ""), body.get("password", "")

    def fn(cur):
        cur.execute("SELECT * FROM sys_user WHERE username=%s", (username,))
        u = cur.fetchone()
        generic_err = BizError("账号或密码错误")
        if not u or u["status"] != "启用":
            raise generic_err
        if u["locked_until"] and u["locked_until"] > dt.datetime.now():
            remain = int((u["locked_until"] - dt.datetime.now()).total_seconds() // 60) + 1
            raise BizError(f"连续失败次数过多，账号已锁定，请约 {remain} 分钟后再试")
        if hash_password(u["salt"], password) != u["password_hash"]:
            fails = u["failed_attempts"] + 1
            if fails >= 5:
                cur.execute("""UPDATE sys_user SET failed_attempts=0,
                               locked_until=NOW()+INTERVAL 10 MINUTE WHERE user_id=%s""", (u["user_id"],))
                raise BizError("密码连续错误 5 次，账号锁定 10 分钟")
            cur.execute("UPDATE sys_user SET failed_attempts=%s WHERE user_id=%s", (fails, u["user_id"]))
            raise generic_err
        cur.execute("""UPDATE sys_user SET failed_attempts=0, locked_until=NULL,
                       last_login=NOW() WHERE user_id=%s""", (u["user_id"],))
        session.permanent = True
        session.update({"uid": u["user_id"], "role": u["role"], "name": u["real_name"],
                        "elder_id": u["elder_id"], "caregiver_id": u["caregiver_id"]})
        return {"real_name": u["real_name"], "role": u["role"]}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True, "data": "已退出"})


@app.get("/api/me")
def me():
    if not session.get("uid"):
        return jsonify({"ok": False, "msg": "未登录"}), 401
    return jsonify({"ok": True, "data": {
        "name": session["name"], "role": session["role"],
        "elder_id": session.get("elder_id"), "caregiver_id": session.get("caregiver_id")}})


# ------------------------------------------------------------------ 页面
@app.get("/")
def index():
    return send_file(FRONTEND)


@app.get("/assets/<path:filename>")
def frontend_assets(filename):
    """前端静态资源：/assets/css/*.css、/assets/js/*.js（与 index.html 同目录）。"""
    return send_from_directory(FRONTEND_DIR, filename)


# ------------------------------------------------------------------ 基础数据
@app.get("/api/items")
@login_required()
def items():
    return jsonify({"ok": True, "data": query_all(
        "SELECT * FROM service_item ORDER BY item_id")})


@app.get("/api/schedules")
@login_required(roles=("社区管理员", "机构负责人", "护工", "监管人员"))
def schedules():
    """护工只能看自己的排班；社区/机构/监管看全部。"""
    sql = "SELECT * FROM v_schedule_capacity"
    args = ()
    if session["role"] == "护工":
        sql += " WHERE caregiver_id=%s"
        args = (session["caregiver_id"],)
    return jsonify({"ok": True, "data": query_all(sql + " ORDER BY work_date, shift, caregiver_name", args)})


@app.get("/api/pending-orders")
@login_required(roles=("社区管理员",))
def pending_orders():
    return jsonify({"ok": True, "data": query_all(
        "SELECT * FROM v_pending_dispatch_orders ORDER BY waited_min DESC")})


# ------------------------------------------------------------------ 总览
@app.get("/api/stats")
@login_required(roles=("社区管理员", "监管人员", "机构负责人"))
def stats():
    rows = query_all("""
        SELECT
          (SELECT COUNT(*) FROM elder WHERE status='正常') AS elders_normal,
          (SELECT COUNT(*) FROM service_order WHERE status IN ('待派单','已派单','服务中')) AS orders_active,
          (SELECT COUNT(*) FROM v_pending_dispatch_orders WHERE timeout_flag='超时') AS orders_timeout,
          (SELECT COUNT(*) FROM care_plan p WHERE p.status='生效' AND
             (SELECT MAX(a.expire_date) FROM assessment a WHERE a.elder_id=p.elder_id) < CURDATE()
          ) AS plans_to_pause,
          (SELECT COUNT(*) FROM subsidy_claim
            WHERE audit_status IN ('待审核','街道已审')) AS claims_in_progress,
          (SELECT COUNT(*) FROM quality_inspection
            WHERE rectification_status IN ('待整改','整改中')) AS open_rectifications
    """)
    return jsonify({"ok": True, "data": rows[0]})


# ------------------------------------------------------------------ 老人档案（家属只见自家）
@app.get("/api/elders")
@login_required()
def elders():
    sql = "SELECT * FROM v_elder_assessment_plan"
    args = ()
    if session["role"] == "家属":
        sql += " WHERE elder_id=%s"
        args = (session["elder_id"],)
    return jsonify({"ok": True, "data": query_all(sql + " ORDER BY elder_id", args)})


@app.get("/api/elder-reports/unassessed-solitary")
@login_required(roles=("社区管理员",))
def unassessed_solitary_report():
    rows = run_in_transaction(
        lambda cur: [jsonable(row) for row in list_unassessed_solitary(cur)]
    )
    return jsonify({"ok": True, "data": rows})


@app.get("/api/elder-reports/community-distribution")
@login_required(roles=("社区管理员", "监管人员"))
def community_distribution_report():
    rows = run_in_transaction(
        lambda cur: [jsonable(row) for row in list_community_distribution(cur)]
    )
    return jsonify({"ok": True, "data": rows})


@app.get("/api/communities")
@login_required()
def communities():
    return jsonify({"ok": True, "data": query_all(
        "SELECT community_id, name, district FROM community ORDER BY community_id")})


@app.get("/api/elders/<int:elder_id>/detail")
@login_required()
def elder_detail(elder_id):
    if session["role"] == "家属" and elder_id != session["elder_id"]:
        return jsonify({"ok": False, "msg": "无权限：只能查看自家老人档案"}), 403
    row = query_all(
        """SELECT elder_id, name, id_card, birth_date, gender, address, community_id,
                  guardian_name, guardian_phone, special_tag, status
           FROM elder WHERE elder_id=%s""",
        (elder_id,),
    )
    if not row:
        return jsonify({"ok": False, "msg": "老人档案不存在"}), 404
    return jsonify({"ok": True, "data": row[0]})


@app.post("/api/elders")
@login_required(roles=("社区管理员",))
def elder_create():
    body = request.get_json(force=True)

    def fn(cur):
        return dao_create_elder(cur, body)

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.patch("/api/elders/<int:elder_id>")
@login_required(roles=("社区管理员",))
def elder_update(elder_id):
    body = request.get_json(force=True)

    def fn(cur):
        return dao_update_elder(cur, elder_id, body)

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


# ------------------------------------------------------------------ 照护计划
@app.get("/api/care-plans")
@login_required()
def care_plans():
    elder_id = session["elder_id"] if session["role"] == "家属" else None
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: [jsonable(row) for row in list_care_plans(cur, elder_id)]
    )})


@app.get("/api/care-plans/caregivers")
@login_required(roles=("社区管理员",))
def care_plan_caregivers():
    return jsonify({"ok": True, "data": query_all(
        """SELECT caregiver_id, name, agency
           FROM caregiver WHERE on_duty='在岗'
           ORDER BY name"""
    )})


@app.get("/api/care-plans/packages")
@login_required(roles=("社区管理员",))
def care_plan_packages():
    return jsonify({"ok": True, "data": list(PACKAGE_NAMES)})


@app.post("/api/care-plans")
@login_required(roles=("社区管理员",))
def care_plan_create():
    body = request.get_json(force=True)
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: create_care_plan(cur, body)
    )})


@app.patch("/api/care-plans/<int:plan_id>")
@login_required(roles=("社区管理员",))
def care_plan_update(plan_id):
    body = request.get_json(force=True)
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: update_care_plan(cur, plan_id, body)
    )})


# ------------------------------------------------------------------ 能力评估
@app.get("/api/elders/<int:elder_id>/assessments")
@login_required()
def elder_assessments(elder_id):
    """评估历史：家属只能查自家老人；含过期标志与剩余天数（复评提醒）。"""
    if session["role"] == "家属" and elder_id != session["elder_id"]:
        return jsonify({"ok": False, "msg": "无权限：只能查看自家老人的评估记录"}), 403
    return jsonify({"ok": True, "data": query_all("""
        SELECT a.scale, a.score, a.ability_level, a.assessor, a.assess_date, a.expire_date,
               (a.expire_date < CURDATE()) AS expired,
               DATEDIFF(a.expire_date, CURDATE()) AS days_left
        FROM assessment a WHERE a.elder_id=%s ORDER BY a.assessment_id DESC""", elder_id)})


@app.post("/api/elders/<int:elder_id>/assessments")
@login_required(roles=("社区管理员",))
def create_assessment(elder_id):
    """社区录入能力评估：等级按得分自动核定（演示口径，与种子数据一致：
    ≥85 能力完好 / 75-84 轻度 / 50-74 中度 / <50 重度），结果一年有效；
    无其他生效计划时，复评最多恢复一条暂停计划。"""
    body = request.get_json(force=True)
    scale, score = body.get("scale", "ADL"), body["score"]

    def fn(cur):
        return dao_record_assessment(
            cur, elder_id, {"scale": scale, "score": score}, session["name"])

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


# ------------------------------------------------------------------ 订单
@app.get("/api/orders")
@login_required()
def orders():
    """家属只见自家老人订单；护工只见派给自己的订单；其余角色看全部。"""
    rows = run_in_transaction(lambda cur: dao_list_orders(
        cur, session["role"], session.get("elder_id"), session.get("caregiver_id")))
    return jsonify({"ok": True, "data": [jsonable(r) for r in rows]})


@app.post("/api/orders")
@login_required(roles=("家属", "社区管理员"))
def create_order():
    """下单：校验档案状态 + 评估有效期（评估过期不允许下单），金额按项目计价。
    家属只能为绑定的老人下单。"""
    body = request.get_json(force=True)
    if session["role"] == "家属":
        elder_id = session["elder_id"]
    else:
        elder_id = body["elder_id"]
    item_id = body["item_id"]
    appoint_time, channel = body["appoint_time"], body.get("channel", "社区代下单")
    if session["role"] == "家属" and channel not in ("家属端",):
        channel = "家属端"
    def fn(cur):
        return dao_create_order(cur, elder_id, item_id, appoint_time, channel, session["role"])

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


# ------------------------------------------------------------------ 派单
@app.get("/api/orders/<int:order_id>/recommend")
@login_required(roles=("社区管理员",))
def recommend(order_id):
    """推荐护工：在岗 + 证书有效 + 服务区域覆盖老人社区 + 当天该班次有余量。"""
    rows = run_in_transaction(lambda cur: recommend_caregivers(cur, order_id))
    return jsonify({"ok": True, "data": [jsonable(r) for r in rows]})


@app.post("/api/orders/<int:order_id>/dispatch")
@login_required(roles=("社区管理员",))
def dispatch_order(order_id):
    """派单：事务内锁定订单 → 插入派单记录（触发器做容量/资质兜底校验）→ 回写订单状态。"""
    caregiver_id = request.get_json(force=True)["caregiver_id"]
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: dao_dispatch_order(cur, order_id, caregiver_id))})


@app.post("/api/dispatches/<int:dispatch_id>/complete")
@login_required(roles=("护工", "社区管理员"))
def complete_dispatch(dispatch_id):
    """服务完成：回填时间与服务记录、家属确认 → 触发器自动把订单置为已完成。"""
    note = request.get_json(force=True).get("service_note", "")
    return jsonify({"ok": True, "data": run_in_transaction(lambda cur: dao_complete_dispatch(
        cur, dispatch_id, note, session["role"], session.get("caregiver_id")))})


@app.post("/api/dispatches/<int:dispatch_id>/reassign")
@login_required(roles=("社区管理员",))
def reassign(dispatch_id):
    """改派：保留原派单记录与原因，订单回到待派单，排班余量释放。"""
    reason = request.get_json(force=True).get("reason", "")
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: reassign_dispatch(cur, dispatch_id, reason))})


# ------------------------------------------------------------------ 补贴
@app.get("/api/subsidy/policies")
@login_required(roles=("家属", "社区管理员", "监管人员"))
def policies():
    return jsonify({"ok": True, "data": query_all("""
        SELECT p.policy_id, p.district, p.target_type, si.name AS item_name,
               p.standard, p.period, p.effective_from, p.effective_to
        FROM subsidy_policy p JOIN service_item si ON si.item_id=p.item_id
        WHERE CURDATE() BETWEEN p.effective_from AND p.effective_to
        ORDER BY p.policy_id""")})


@app.get("/api/subsidy/eligible-policies")
@login_required(roles=("社区管理员",))
def eligible_policies():
    """按「老人 + 账期」筛选当前真正可以申报的补贴政策。

    依次校验：区县一致 → 对象类别匹配 → 账期内存在已完成订单 → 订单工时有效 → 本账期未重复申报。
    返回的 policies 只包含区县和类别都符合的政策，并用 claimable/block_reason 标出暂不可申报的原因，
    前端只把 claimable=True 的项放进下拉框。
    """
    elder_id = request.args.get("elder_id", type=int)
    period = (request.args.get("period") or "").strip()
    if not elder_id:
        return jsonify({"ok": False, "msg": "请先选择老人"}), 400
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        return jsonify({"ok": False, "msg": "账期格式应为 YYYY-MM"}), 400

    def fn(cur):
        cur.execute("""SELECT e.elder_id, e.name, e.status, e.special_tag,
                              c.name AS community, c.district
                         FROM elder e
                         JOIN community c ON c.community_id = e.community_id
                        WHERE e.elder_id=%s""", (elder_id,))
        elder = cur.fetchone()
        if not elder:
            raise BizError("老人档案不存在")

        tags = [t.strip() for t in (elder["special_tag"] or "").split(",") if t.strip()]
        cur.execute("""SELECT p.policy_id, p.district, p.target_type, p.item_id,
                              p.standard, si.name AS item_name
                         FROM subsidy_policy p JOIN service_item si ON si.item_id=p.item_id
                        WHERE CURDATE() BETWEEN p.effective_from AND p.effective_to
                        ORDER BY p.policy_id""")
        policies = cur.fetchall()

        cur.execute("""SELECT policy_id FROM subsidy_claim
                        WHERE elder_id=%s AND claim_period=%s""", (elder_id, period))
        claimed_policy_ids = {row["policy_id"] for row in cur.fetchall()}

        candidates, excluded_count = [], 0
        for policy in policies:
            if policy["district"] != elder["district"] or policy["target_type"] not in tags:
                excluded_count += 1
                continue
            rows = claim_orders_for(cur, elder_id, policy["item_id"], period)
            orders, invalid_orders = split_claimable_orders(rows)
            already_claimed = policy["policy_id"] in claimed_policy_ids
            if already_claimed:
                reason = "本账期已申报该项"
            elif not rows:
                reason = "本账期无该项已完成订单"
            elif invalid_orders:
                reason = "订单 " + "、".join(invalid_orders) + " 缺少有效工时记录"
            else:
                reason = None
            candidates.append({
                "policy_id": policy["policy_id"],
                "district": policy["district"],
                "target_type": policy["target_type"],
                "item_name": policy["item_name"],
                "standard": float(policy["standard"]),
                "claimable": reason is None,
                "block_reason": reason,
                "order_count": len(orders),
                "order_ids": orders,
            })

        return {
            "elder": {
                "elder_id": elder["elder_id"],
                "name": elder["name"],
                "community": elder["community"],
                "district": elder["district"],
                "special_tag": elder["special_tag"],
                "status": elder["status"],
            },
            "period": period,
            "policies": candidates,
            "claimable_count": sum(1 for p in candidates if p["claimable"]),
            "excluded_count": excluded_count,
        }

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.get("/api/subsidy/claims")
@login_required(roles=("家属", "社区管理员", "监管人员"))
def claims():
    sql = "SELECT * FROM v_claim_progress"
    args = ()
    if session["role"] == "家属":
        sql += " WHERE elder_id=%s"
        args = (session["elder_id"],)
    return jsonify({"ok": True, "data": query_all(sql + " ORDER BY claim_id DESC", args)})


@app.post("/api/subsidy/claims")
@login_required(roles=("社区管理员",))
def create_claim():
    """补贴申报：对象类别匹配 + 只统计账期内已完成订单 + 唯一约束防重复申报。"""
    body = request.get_json(force=True)
    elder_id, policy_id, period = body["elder_id"], body["policy_id"], body["claim_period"]

    def fn(cur):
        cur.execute("""SELECT c.district, e.special_tag FROM elder e
                        JOIN community c ON c.community_id = e.community_id
                       WHERE e.elder_id=%s""", (elder_id,))
        elder = cur.fetchone()
        if not elder:
            raise BizError("老人档案不存在")
        cur.execute("""SELECT p.target_type, p.item_id, p.standard, p.district FROM subsidy_policy p
                        WHERE p.policy_id=%s""", (policy_id,))
        policy = cur.fetchone()
        if not policy:
            raise BizError("政策不存在或已失效")
        if policy["district"] != elder["district"]:
            raise BizError(f"政策适用区县为「{policy['district']}」，该老人所属区县为「{elder['district']}」")
        tags = elder["special_tag"] or ""
        if policy["target_type"] not in [t.strip() for t in tags.split(",") if t.strip()]:
            raise BizError(f"该老人标签（{tags or '无'}）不符合政策的对象类别「{policy['target_type']}」")

        rows = claim_orders_for(cur, elder_id, policy["item_id"], period)
        if not rows:
            raise BizError("该账期内没有符合条件的已完成订单，缺少记录不予申报")
        orders, invalid_orders = split_claimable_orders(rows)
        if invalid_orders:
            raise BizError(
                "以下订单缺少有效工时记录，暂不能申报："
                + "、".join(invalid_orders)
            )

        amount = round(len(orders) * float(policy["standard"]), 2)
        cur.execute("""INSERT INTO subsidy_claim (elder_id, policy_id, claim_period, amount)
                       VALUES (%s,%s,%s,%s)""",
                    (elder_id, policy_id, period, amount))
        claim_id = cur.lastrowid
        cur.executemany(
            "INSERT INTO subsidy_claim_order (claim_id, order_id) VALUES (%s, %s)",
            [(claim_id, oid) for oid in orders],
        )
        return {"claim_id": claim_id, "amount": amount, "order_ids": orders}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.post("/api/subsidy/claims/<int:claim_id>/audit")
@login_required(roles=("监管人员",))
def audit_claim(claim_id):
    """审核与拨付分离：待审核→街道已审→通过；通过后方可拨付。"""
    action = request.get_json(force=True)["action"]
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: transition_claim(cur, claim_id, action, session["name"])
    )})


# ------------------------------------------------------------------ 质量监管
@app.get("/api/quality/inspections")
@login_required(roles=("社区管理员", "机构负责人", "监管人员", "护工"))
def quality_inspections():
    """质量抽查列表；护工只能查看与本人相关的抽查和整改任务。"""
    sql = "SELECT * FROM v_quality_inspection_summary"
    args = ()
    if session["role"] == "护工":
        sql += " WHERE caregiver_id=%s"
        args = (session["caregiver_id"],)
    return jsonify({"ok": True, "data": query_all(
        sql + " ORDER BY inspection_id DESC", args
    )})


@app.get("/api/quality/caregivers")
@login_required(roles=("社区管理员", "监管人员"))
def quality_caregivers():
    """Provide caregiver-level targets for manual inspections."""
    return jsonify({"ok": True, "data": query_all(
        """SELECT caregiver_id, caregiver_name, agency, official_rating,
                  inspected_count, inspection_avg_score, open_rectifications
             FROM v_caregiver_quality_score
            ORDER BY open_rectifications DESC, caregiver_name"""
    )})


@app.post("/api/quality/inspections")
@login_required(roles=("监管人员",))
def create_quality_inspection():
    body = request.get_json(force=True)
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: create_manual_inspection(cur, body, session["name"])
    )})


@app.post("/api/quality/inspections/random")
@login_required(roles=("监管人员",))
def random_quality_inspections():
    body = request.get_json(force=True)
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: sample_completed_orders(cur, body, session["name"])
    )})


@app.post("/api/quality/inspections/<int:inspection_id>/result")
@login_required(roles=("监管人员",))
def record_quality_result(inspection_id):
    body = request.get_json(force=True)
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: complete_inspection(cur, inspection_id, body)
    )})


@app.post("/api/quality/inspections/<int:inspection_id>/rectification")
@login_required(roles=("社区管理员", "机构负责人", "护工"))
def record_rectification(inspection_id):
    body = request.get_json(force=True)
    return jsonify({"ok": True, "data": run_in_transaction(
        lambda cur: submit_rectification(
            cur,
            inspection_id,
            body.get("rectification_result", ""),
            session["role"],
            session.get("caregiver_id"),
        )
    )})

# ------------------------------------------------------------------ 线3：护工档案、批量排班与工时签到签退
@app.get("/api/line3/caregivers")
@login_required(roles=("社区管理员", "机构负责人", "监管人员"))
def line3_caregivers():
    """查询护工档案及持有专项资质列表"""
    rows = query_all("""
        SELECT cg.*,
               GROUP_CONCAT(si.name ORDER BY si.item_id SEPARATOR '、') AS qualified_items
          FROM caregiver cg
          LEFT JOIN caregiver_item ci ON ci.caregiver_id = cg.caregiver_id AND ci.cert_verified = 1
          LEFT JOIN service_item si ON si.item_id = ci.item_id
         GROUP BY cg.caregiver_id
         ORDER BY cg.caregiver_id
    """)
    return jsonify({"ok": True, "data": rows})


@app.get("/api/line3/cert-warnings")
@login_required(roles=("社区管理员", "机构负责人", "监管人员"))
def line3_cert_warnings():
    """查询证书已过期或30天内临期预警（视图 v_caregiver_cert_warning）"""
    rows = [jsonable(r) for r in Line3DAO.list_cert_warnings()]
    return jsonify({"ok": True, "data": rows})


@app.post("/api/line3/schedules")
@login_required(roles=("社区管理员", "机构负责人"))
def line3_create_schedule():
    """单条新增排班（触发器拦截同日全天/半天冲突，唯一索引防重复）"""
    body = request.get_json(force=True)
    try:
        new_id = Line3DAO.create_schedule(
            int(body["caregiver_id"]),
            body["work_date"],
            body["shift"],
            int(body.get("capacity", 4)),
        )
        return jsonify({"ok": True, "data": {"schedule_id": new_id}})
    except pymysql.err.OperationalError as e:
        if e.args and e.args[0] == 1644:
            raise BizError(e.args[1])
        raise


@app.post("/api/line3/schedules/batch")
@login_required(roles=("社区管理员", "机构负责人"))
def line3_batch_schedule():
    """调用存储过程 sp_batch_create_schedule 按日期范围批量排班"""
    body = request.get_json(force=True)
    try:
        cnt = Line3DAO.batch_create_schedule(
            int(body["caregiver_id"]),
            body["start_date"],
            body["end_date"],
            body.get("shift", "全天"),
            int(body.get("capacity", 4)),
        )
        return jsonify({"ok": True, "data": {"created_count": cnt}})
    except pymysql.err.OperationalError as e:
        if e.args and e.args[0] == 1644:
            raise BizError(e.args[1])
        raise


@app.get("/api/line3/work-hours")
@login_required(roles=("社区管理员", "机构负责人", "护工", "监管人员"))
def line3_work_hours():
    """查询工时签到签退记录；护工仅看本人记录"""
    sql = """
        SELECT wh.work_hour_id, wh.caregiver_id, cg.name AS caregiver_name, cg.agency,
               wh.dispatch_id, d.order_id, e.name AS elder_name, si.name AS item_name,
               wh.checkin_time, wh.checkout_time, wh.checkin_location,
               wh.fence_result, wh.valid_hours, wh.review_status
          FROM work_hour wh
          JOIN caregiver cg ON cg.caregiver_id = wh.caregiver_id
          JOIN dispatch d ON d.dispatch_id = wh.dispatch_id
          JOIN service_order o ON o.order_id = d.order_id
          JOIN elder e ON e.elder_id = o.elder_id
          JOIN service_item si ON si.item_id = o.item_id
    """
    args = ()
    if session["role"] == "护工":
        sql += " WHERE wh.caregiver_id = %s"
        args = (session["caregiver_id"],)
    return jsonify({"ok": True, "data": query_all(sql + " ORDER BY wh.work_hour_id DESC", args)})


@app.get("/api/line3/pending-checkin")
@login_required(roles=("护工", "社区管理员"))
def line3_pending_checkin():
    """查询当前处于已派单/服务中且尚未签到的派单记录，供前端一键签到"""
    sql = """
        SELECT d.dispatch_id, d.order_id, d.caregiver_id, cg.name AS caregiver_name,
               e.name AS elder_name, e.address, si.name AS item_name, o.appoint_time
          FROM dispatch d
          JOIN caregiver cg ON cg.caregiver_id = d.caregiver_id
          JOIN service_order o ON o.order_id = d.order_id
          JOIN elder e ON e.elder_id = o.elder_id
          JOIN service_item si ON si.item_id = o.item_id
          LEFT JOIN work_hour wh ON wh.dispatch_id = d.dispatch_id
         WHERE d.is_current = 1
           AND o.status IN ('已派单', '服务中')
           AND wh.work_hour_id IS NULL
    """
    args = ()
    if session["role"] == "护工":
        sql += " AND d.caregiver_id = %s"
        args = (session["caregiver_id"],)
    return jsonify({"ok": True, "data": query_all(sql + " ORDER BY d.dispatch_id DESC", args)})


@app.post("/api/line3/work-hours/checkin")
@login_required(roles=("护工", "社区管理员"))
def line3_checkin():
    """护工上门签到"""
    body = request.get_json(force=True)
    dispatch_id = int(body["dispatch_id"])
    checkin_time = body["checkin_time"]
    location = body.get("checkin_location", "").strip() or "老人居住地址现场定位"
    rows = query_all("SELECT caregiver_id FROM dispatch WHERE dispatch_id=%s AND is_current=1", (dispatch_id,))
    if not rows:
        raise BizError("有效派单记录不存在")
    cg_id = rows[0]["caregiver_id"]
    if session["role"] == "护工" and cg_id != session["caregiver_id"]:
        raise BizError("无权限为其他护工签到")
    try:
        wh_id = Line3DAO.checkin_work_hour(cg_id, dispatch_id, checkin_time, location)
        return jsonify({"ok": True, "data": {"work_hour_id": wh_id}})
    except pymysql.err.OperationalError as e:
        if e.args and e.args[0] == 1644:
            raise BizError(e.args[1])
        raise


@app.post("/api/line3/work-hours/<int:wh_id>/checkout")
@login_required(roles=("护工", "社区管理员"))
def line3_checkout(wh_id):
    """护工离场签退（触发器自动计算 valid_hours 并累加 caregiver.total_hours，围栏异常转待复核）"""
    body = request.get_json(force=True)
    checkout_time = body["checkout_time"]
    fence_result = body.get("fence_result", "通过")
    try:
        res = Line3DAO.checkout_work_hour(wh_id, checkout_time, fence_result)
        if not res:
            raise BizError("工时记录不存在")
        return jsonify({"ok": True, "data": jsonable(res)})
    except pymysql.err.OperationalError as e:
        if e.args and e.args[0] == 1644:
            raise BizError(e.args[1])
        raise


@app.post("/api/line3/work-hours/<int:wh_id>/review")
@login_required(roles=("社区管理员", "机构负责人", "监管人员"))
def line3_review_work_hour(wh_id):
    """管理员/机构对围栏外异常工时进行人工复核"""
    body = request.get_json(force=True)
    decision = body.get("decision")  # '复核通过' 或 '复核驳回'
    if decision not in ("复核通过", "复核驳回"):
        raise BizError("复核结论非法")

    def fn(cur):
        cur.execute("SELECT * FROM work_hour WHERE work_hour_id=%s", (wh_id,))
        wh = cur.fetchone()
        if not wh:
            raise BizError("工时记录不存在")
        if not wh["checkout_time"]:
            raise BizError("该记录尚未签退，无法复核")
        if decision == "复核通过":
            cur.execute("""
                UPDATE work_hour
                   SET review_status = '复核通过',
                       valid_hours = ROUND(TIMESTAMPDIFF(MINUTE, checkin_time, checkout_time) / 60.0, 2)
                 WHERE work_hour_id = %s
            """, (wh_id,))
            cur.execute("""
                UPDATE caregiver
                   SET total_hours = total_hours + (SELECT valid_hours FROM work_hour WHERE work_hour_id = %s)
                 WHERE caregiver_id = %s
            """, (wh_id, wh["caregiver_id"]))
        else:
            cur.execute("UPDATE work_hour SET review_status = '复核驳回', valid_hours = 0.00 WHERE work_hour_id = %s", (wh_id,))
        return {"work_hour_id": wh_id, "review_status": decision}

    return jsonify({"ok": True, "data": run_in_transaction(fn)})


@app.get("/api/line3/summary")
@login_required(roles=("社区管理员", "机构负责人", "护工", "监管人员"))
def line3_summary():
    """护工月度有效工时与服务单量综合汇总"""
    rows = [jsonable(r) for r in Line3DAO.get_monthly_work_summary()]
    return jsonify({"ok": True, "data": rows})

# ------------------------------------------------------------------ 运维（存储过程）
@app.get("/api/maintenance/expired-preview")
@login_required(roles=("社区管理员",))
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
@login_required(roles=("社区管理员",))
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
    print("演示账号（密码均为 123456）：shequ / jiashu / jiashu2 / hugong / jigou / jianguan")
    app.run(host="127.0.0.1", port=5000, debug=False)
