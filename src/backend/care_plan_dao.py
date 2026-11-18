# -*- coding: utf-8 -*-
"""照护计划持久层：业务校验、查询与状态流转。"""
import datetime as dt


class CarePlanError(Exception):
    """照护计划业务规则错误。"""


STATUSES = ("生效", "暂停", "结束")


def _text(value, name, max_len=50):
    text = str(value or "").strip()
    if not text:
        raise CarePlanError(f"{name}不能为空")
    if len(text) > max_len:
        raise CarePlanError(f"{name}长度不能超过 {max_len} 字")
    return text


def _date(value, name):
    if isinstance(value, dt.date):
        return value
    try:
        return dt.datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise CarePlanError(f"{name}格式应为 YYYY-MM-DD") from None


def _require_elder(cur, elder_id, active_only=True):
    cur.execute("SELECT elder_id, status FROM elder WHERE elder_id=%s", (elder_id,))
    row = cur.fetchone()
    if not row:
        raise CarePlanError("老人档案不存在")
    if active_only and row["status"] != "正常":
        raise CarePlanError("老人档案未处于正常状态，不允许制定照护计划")
    return row


def _optional_caregiver(cur, caregiver_id):
    if caregiver_id in (None, "", 0):
        return None
    caregiver_id = int(caregiver_id)
    cur.execute(
        "SELECT caregiver_id FROM caregiver WHERE caregiver_id=%s",
        (caregiver_id,),
    )
    if not cur.fetchone():
        raise CarePlanError("责任护工不存在")
    return caregiver_id


def list_care_plans(cur, elder_id=None):
    sql = """
        SELECT p.plan_id, p.elder_id, e.name AS elder_name,
               p.package_name, p.frequency, p.start_date, p.end_date,
               p.caregiver_id, c.name AS caregiver_name, p.status
        FROM care_plan p
        JOIN elder e ON e.elder_id=p.elder_id
        LEFT JOIN caregiver c ON c.caregiver_id=p.caregiver_id
    """
    args = ()
    if elder_id is not None:
        sql += " WHERE p.elder_id=%s"
        args = (elder_id,)
    cur.execute(sql + " ORDER BY p.plan_id DESC", args)
    return cur.fetchall()


def get_care_plan(cur, plan_id):
    cur.execute(
        """SELECT plan_id, elder_id, package_name, frequency, start_date,
                  end_date, caregiver_id, status
           FROM care_plan WHERE plan_id=%s""",
        (plan_id,),
    )
    row = cur.fetchone()
    if not row:
        raise CarePlanError("照护计划不存在")
    return row


def create_care_plan(cur, payload):
    elder_id = int(payload.get("elder_id", 0))
    _require_elder(cur, elder_id)
    package_name = _text(payload.get("package_name"), "服务包名称")
    frequency = _text(payload.get("frequency"), "服务频次")
    start_date = _date(payload.get("start_date"), "开始日期")
    end_date = _date(payload.get("end_date"), "结束日期")
    if end_date < start_date:
        raise CarePlanError("结束日期不能早于开始日期")
    caregiver_id = _optional_caregiver(cur, payload.get("caregiver_id"))
    status = payload.get("status", "生效")
    if status not in STATUSES:
        raise CarePlanError("计划状态只能是「生效/暂停/结束」")

    cur.execute(
        """INSERT INTO care_plan
           (elder_id, package_name, frequency, start_date, end_date, caregiver_id, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (elder_id, package_name, frequency, start_date, end_date, caregiver_id, status),
    )
    return {"plan_id": cur.lastrowid, "elder_id": elder_id, "status": status}


def update_care_plan(cur, plan_id, payload):
    row = get_care_plan(cur, plan_id)
    fields, args = [], []

    if "elder_id" in payload:
        elder_id = int(payload["elder_id"])
        _require_elder(cur, elder_id)
        fields.append("elder_id=%s")
        args.append(elder_id)
    if "package_name" in payload:
        fields.append("package_name=%s")
        args.append(_text(payload["package_name"], "服务包名称"))
    if "frequency" in payload:
        fields.append("frequency=%s")
        args.append(_text(payload["frequency"], "服务频次"))
    if "start_date" in payload:
        fields.append("start_date=%s")
        args.append(_date(payload["start_date"], "开始日期"))
    if "end_date" in payload:
        fields.append("end_date=%s")
        args.append(_date(payload["end_date"], "结束日期"))
    if "caregiver_id" in payload:
        caregiver_id = _optional_caregiver(cur, payload["caregiver_id"])
        fields.append("caregiver_id=%s")
        args.append(caregiver_id)
    if "status" in payload:
        status = payload["status"]
        if status not in STATUSES:
            raise CarePlanError("计划状态只能是「生效/暂停/结束」")
        fields.append("status=%s")
        args.append(status)

    start = payload.get("start_date", row["start_date"])
    end = payload.get("end_date", row["end_date"])
    start = _date(start, "开始日期")
    end = _date(end, "结束日期")
    if end < start:
        raise CarePlanError("结束日期不能早于开始日期")
    if not fields:
        raise CarePlanError("没有需要修改的字段")

    args.append(plan_id)
    cur.execute(f"UPDATE care_plan SET {','.join(fields)} WHERE plan_id=%s", tuple(args))
    return {"plan_id": plan_id, "updated": cur.rowcount}
