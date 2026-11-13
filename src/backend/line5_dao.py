# -*- coding: utf-8 -*-
"""Line 5 persistence operations: subsidy audit and quality inspection."""
import math
import random


class Line5Error(Exception):
    """A line-5 business rule was not satisfied."""


INSPECTION_METHODS = ("电话回访", "上门核查")


def _require_score(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise Line5Error("抽查评分应为 0-100 的整数")
    return value


def _clean_text(value, field_name, required=False):
    text = str(value or "").strip()
    if required and not text:
        raise Line5Error(f"{field_name}不能为空")
    return text or None


def _target_from_order(cur, order_id):
    cur.execute(
        """SELECT o.status, d.caregiver_id
             FROM service_order o
             LEFT JOIN dispatch d
               ON d.order_id = o.order_id AND d.is_current = 1
            WHERE o.order_id = %s""",
        (order_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line5Error("服务订单不存在")
    if row["status"] != "已完成":
        raise Line5Error("只有已完成订单可以进入质量抽查")
    if not row["caregiver_id"]:
        raise Line5Error("该订单没有当前派单护工，无法关联抽查对象")
    return row["caregiver_id"]


def _ensure_caregiver(cur, caregiver_id):
    cur.execute(
        "SELECT caregiver_id FROM caregiver WHERE caregiver_id=%s",
        (caregiver_id,),
    )
    if not cur.fetchone():
        raise Line5Error("护工档案不存在")


def _rectification_state(score, issue_tags):
    return "待整改" if score < 80 or issue_tags else "无需整改"


def create_manual_inspection(cur, payload, inspector):
    """Create a completed inspection for one order or one caregiver."""
    order_id = payload.get("order_id")
    caregiver_id = payload.get("caregiver_id")
    method = payload.get("inspection_method", "电话回访")
    if method not in INSPECTION_METHODS:
        raise Line5Error("抽查方式只能是「电话回访」或「上门核查」")

    if order_id:
        order_id = int(order_id)
        derived_caregiver_id = _target_from_order(cur, order_id)
        if caregiver_id and int(caregiver_id) != derived_caregiver_id:
            raise Line5Error("抽查护工与订单当前派单护工不一致")
        caregiver_id = derived_caregiver_id
    elif caregiver_id:
        caregiver_id = int(caregiver_id)
        _ensure_caregiver(cur, caregiver_id)
    else:
        raise Line5Error("订单编号和护工编号至少填写一项")

    score = _require_score(payload.get("score"))
    issue_tags = _clean_text(payload.get("issue_tags"), "问题标签")
    requirement = _clean_text(
        payload.get("rectification_requirement"), "整改要求"
    )
    state = _rectification_state(score, issue_tags)
    if state == "待整改" and not requirement:
        raise Line5Error("存在质量问题时必须填写整改要求")

    cur.execute(
        """INSERT INTO quality_inspection
           (order_id, caregiver_id, inspection_method, score, issue_tags,
            rectification_requirement, inspection_status, rectification_status,
            inspector, inspected_at)
           VALUES (%s,%s,%s,%s,%s,%s,'已抽查',%s,%s,NOW())""",
        (
            order_id or None,
            caregiver_id,
            method,
            score,
            issue_tags,
            requirement,
            state,
            inspector,
        ),
    )
    return {
        "inspection_id": cur.lastrowid,
        "score": score,
        "rectification_status": state,
    }


def sample_completed_orders(cur, payload, inspector):
    """Randomly create pending inspections for a percentage of completed orders."""
    rate = payload.get("sample_rate", 10)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        raise Line5Error("抽查比例必须是 1-100 的数字")
    if not 1 <= rate <= 100:
        raise Line5Error("抽查比例必须在 1-100 之间")
    method = payload.get("inspection_method", "电话回访")
    if method not in INSPECTION_METHODS:
        raise Line5Error("抽查方式只能是「电话回访」或「上门核查」")

    cur.execute(
        """SELECT o.order_id, d.caregiver_id
             FROM service_order o
             JOIN dispatch d
               ON d.order_id = o.order_id AND d.is_current = 1
            WHERE o.status = '已完成'
              AND NOT EXISTS (
                    SELECT 1 FROM quality_inspection qi
                     WHERE qi.order_id = o.order_id
                       AND qi.inspection_status = '待抽查'
                  )
            ORDER BY o.order_id"""
    )
    candidates = cur.fetchall()
    if not candidates:
        raise Line5Error("没有可抽查的已完成订单")

    count = max(1, math.ceil(len(candidates) * rate / 100))
    selected = random.sample(candidates, min(count, len(candidates)))
    for row in selected:
        cur.execute(
            """INSERT INTO quality_inspection
               (order_id, caregiver_id, inspection_method, inspection_status,
                inspector, inspected_at)
               VALUES (%s,%s,%s,'待抽查',%s,NOW())""",
            (row["order_id"], row["caregiver_id"], method, inspector),
        )
    return {
        "sample_rate": rate,
        "candidate_count": len(candidates),
        "created_count": len(selected),
        "order_ids": [row["order_id"] for row in selected],
    }


def complete_inspection(cur, inspection_id, payload):
    """Record the result of a pending inspection and open rectification if needed."""
    cur.execute(
        """SELECT inspection_id, inspection_status
             FROM quality_inspection WHERE inspection_id=%s FOR UPDATE""",
        (inspection_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line5Error("抽查记录不存在")
    if row["inspection_status"] != "待抽查":
        raise Line5Error("该抽查记录已录入结果")

    method = payload.get("inspection_method", "电话回访")
    if method not in INSPECTION_METHODS:
        raise Line5Error("抽查方式只能是「电话回访」或「上门核查」")
    score = _require_score(payload.get("score"))
    issue_tags = _clean_text(payload.get("issue_tags"), "问题标签")
    requirement = _clean_text(
        payload.get("rectification_requirement"), "整改要求"
    )
    state = _rectification_state(score, issue_tags)
    if state == "待整改" and not requirement:
        raise Line5Error("存在质量问题时必须填写整改要求")

    cur.execute(
        """UPDATE quality_inspection
              SET inspection_method=%s, score=%s, issue_tags=%s,
                  rectification_requirement=%s, inspection_status='已抽查',
                  rectification_status=%s, inspected_at=NOW()
            WHERE inspection_id=%s""",
        (method, score, issue_tags, requirement, state, inspection_id),
    )
    return {
        "inspection_id": inspection_id,
        "score": score,
        "rectification_status": state,
    }


def submit_rectification(cur, inspection_id, result, role, caregiver_id):
    """Complete an open rectification after the responsible party submits evidence."""
    cur.execute(
        """SELECT caregiver_id, rectification_status
             FROM quality_inspection WHERE inspection_id=%s FOR UPDATE""",
        (inspection_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line5Error("抽查记录不存在")
    if role == "护工" and row["caregiver_id"] != caregiver_id:
        raise Line5Error("无权限：该整改任务不属于当前护工")
    if row["rectification_status"] not in ("待整改", "整改中"):
        raise Line5Error("该抽查记录当前不需要提交整改")

    result = _clean_text(result, "整改结果", required=True)
    cur.execute(
        """UPDATE quality_inspection
              SET rectification_result=%s, rectification_status='已完成',
                  rectified_at=NOW()
            WHERE inspection_id=%s""",
        (result, inspection_id),
    )
    return {"inspection_id": inspection_id, "rectification_status": "已完成"}


def transition_claim(cur, claim_id, action, reviewer):
    """Advance audit and payment as two independent state machines."""
    cur.execute(
        """SELECT audit_status, pay_status
             FROM subsidy_claim WHERE claim_id=%s FOR UPDATE""",
        (claim_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line5Error("补贴申报不存在")

    audit_status, pay_status = row["audit_status"], row["pay_status"]
    if action == "approve":
        if audit_status != "待审核":
            raise Line5Error(f"当前审核状态为「{audit_status}」，不能执行街道审核")
        cur.execute(
            """UPDATE subsidy_claim
                  SET audit_status='街道已审', reviewer=%s, audited_at=NOW()
                WHERE claim_id=%s""",
            (reviewer, claim_id),
        )
    elif action == "pass":
        if audit_status != "街道已审":
            raise Line5Error(f"当前审核状态为「{audit_status}」，不能执行终审通过")
        cur.execute(
            """UPDATE subsidy_claim
                  SET audit_status='通过', reviewer=%s, audited_at=NOW()
                WHERE claim_id=%s""",
            (reviewer, claim_id),
        )
    elif action == "pay":
        if audit_status != "通过":
            raise Line5Error("只有终审通过的申报才能拨付")
        if pay_status == "已拨付":
            raise Line5Error("该申报已经拨付")
        cur.execute(
            """UPDATE subsidy_claim
                  SET pay_status='已拨付', paid_at=NOW()
                WHERE claim_id=%s""",
            (claim_id,),
        )
    elif action == "reject":
        if pay_status == "已拨付":
            raise Line5Error("已拨付申报不能驳回")
        if audit_status in ("通过", "驳回"):
            raise Line5Error(f"当前审核状态为「{audit_status}」，不能驳回")
        cur.execute(
            """UPDATE subsidy_claim
                  SET audit_status='驳回', reviewer=%s, audited_at=NOW()
                WHERE claim_id=%s""",
            (reviewer, claim_id),
        )
    else:
        raise Line5Error("action 只能是 approve / pass / pay / reject")

    cur.execute(
        "SELECT audit_status, pay_status FROM subsidy_claim WHERE claim_id=%s",
        (claim_id,),
    )
    state = cur.fetchone()
    return {
        "claim_id": claim_id,
        "audit_status": state["audit_status"],
        "pay_status": state["pay_status"],
    }
