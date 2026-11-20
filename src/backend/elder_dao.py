# -*- coding: utf-8 -*-
"""线1 持久层：老人档案与能力评估。

职责边界（对应任务书 3.3 持久层抽离要求）：
- 路由层只负责 HTTP、登录与权限；
- 本模块负责档案/评估的业务规则校验与 SQL，供路由层在事务中调用；
- 评估等级按得分核定（演示口径，与种子数据一致）：
  ≥85 能力完好 / 75-84 轻度失能 / 50-74 中度失能 / <50 重度失能；
- 评估结果一年有效；录入新评估后，该老人因评估过期被暂停的照护计划自动恢复。
"""
import datetime as dt
import re


class ElderError(Exception):
    """线1 业务规则错误。"""


GENDERS = ("男", "女")
SCALES = ("ADL", "简易智能状态")
SPECIAL_TAGS = ("独居", "失能", "低保", "高龄")
ID_CARD_RE = re.compile(r"^\d{17}[\dX]$")  # 18 位：前 17 位数字 + 校验位(数字或 X)
PHONE_RE = re.compile(r"^1\d{10}$")


def level_of_score(score):
    """ADL 得分 → 能力等级（项目演示口径）。"""
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        raise ElderError("评估得分应为 0-100 的整数")
    if score >= 85:
        return "能力完好"
    if score >= 75:
        return "轻度失能"
    if score >= 50:
        return "中度失能"
    return "重度失能"


def _clean_text(value, field_name, required=True, max_len=30):
    text = str(value or "").strip()
    if required and not text:
        raise ElderError(f"{field_name}不能为空")
    if len(text) > max_len:
        raise ElderError(f"{field_name}长度不能超过 {max_len} 字")
    return text


def _parse_date(value, field_name):
    if isinstance(value, dt.date):
        return value
    try:
        return dt.datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ElderError(f"{field_name}格式应为 YYYY-MM-DD") from None


def _parse_birth_date(value):
    birth = _parse_date(value, "出生日期")
    if birth >= dt.date.today():
        raise ElderError("出生日期不能晚于当天")
    if birth.year < 1900:
        raise ElderError("出生日期不合理")
    return birth


def _validate_id_card(value):
    id_card = str(value or "").strip().upper()
    if not ID_CARD_RE.match(id_card):
        raise ElderError("身份证号应为 18 位（前 17 位数字，末位数字或 X）")
    return id_card


def _validate_tags(tags):
    """special_tag 允许传集合/列表/逗号串，最终转 SET 存储的逗号串。"""
    if tags is None:
        return None
    if isinstance(tags, str):
        items = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        items = [str(t).strip() for t in tags]
    bad = [t for t in items if t not in SPECIAL_TAGS]
    if bad:
        raise ElderError(f"特殊标签只能是 {'/'.join(SPECIAL_TAGS)}，非法值：{','.join(bad)}")
    return ",".join(dict.fromkeys(items)) or None  # 去重保序


def _require_elder(cur, elder_id, active_only=False, for_update=False):
    sql = "SELECT elder_id, name, status FROM elder WHERE elder_id=%s"
    if for_update:
        sql += " FOR UPDATE"
    cur.execute(sql, (elder_id,))
    row = cur.fetchone()
    if not row:
        raise ElderError("老人档案不存在")
    if active_only and row["status"] != "正常":
        raise ElderError(f"档案状态为「{row['status']}」，不允许该操作")
    return row


def _require_community(cur, community_id):
    cur.execute("SELECT community_id, name FROM community WHERE community_id=%s", (community_id,))
    row = cur.fetchone()
    if not row:
        raise ElderError("所属社区不存在")
    return row


# ------------------------------------------------------------------ 档案
def create_elder(cur, payload):
    """新建老人档案。必填：姓名/身份证/出生日期/性别/地址/社区/监护人姓名与电话。"""
    name = _clean_text(payload.get("name"), "姓名")
    id_card = _validate_id_card(payload.get("id_card"))
    birth_date = _parse_birth_date(payload.get("birth_date"))
    gender = payload.get("gender")
    if gender not in GENDERS:
        raise ElderError("性别只能是「男」或「女」")
    address = _clean_text(payload.get("address"), "居住地址", max_len=100)
    community_id = int(payload.get("community_id", 0))
    _require_community(cur, community_id)
    guardian_name = _clean_text(payload.get("guardian_name"), "监护人姓名")
    guardian_phone = str(payload.get("guardian_phone") or "").strip()
    if not PHONE_RE.match(guardian_phone):
        raise ElderError("监护人电话应为 1 开头的 11 位手机号")
    tags = _validate_tags(payload.get("special_tag"))
    status = payload.get("status", "正常")
    if status not in ("正常", "暂停服务", "注销"):
        raise ElderError("档案状态非法")

    cur.execute(
        """INSERT INTO elder
           (name, id_card, birth_date, gender, address, community_id,
            guardian_name, guardian_phone, special_tag, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (name, id_card, birth_date, gender, address, community_id,
         guardian_name, guardian_phone, tags, status),
    )
    elder_id = cur.lastrowid  # INSERT 后立即保存，后续语句会使 lastrowid 失效
    return {"elder_id": elder_id, "name": name, "status": status}


def update_elder(cur, elder_id, payload):
    """档案信息修改与状态流转。
    状态规则：正常↔暂停服务 可双向；注销为终态，注销后不允许再修改。"""
    row = _require_elder(cur, elder_id)
    if row["status"] == "注销":
        raise ElderError("档案已注销，不允许修改")

    fields, args = [], []
    if "name" in payload:
        fields.append("name=%s"); args.append(_clean_text(payload["name"], "姓名"))
    if "id_card" in payload:
        fields.append("id_card=%s"); args.append(_validate_id_card(payload["id_card"]))
    if "address" in payload:
        fields.append("address=%s"); args.append(_clean_text(payload["address"], "居住地址", max_len=100))
    if "community_id" in payload:
        community_id = int(payload["community_id"])
        _require_community(cur, community_id)
        fields.append("community_id=%s"); args.append(community_id)
    if "guardian_name" in payload:
        fields.append("guardian_name=%s"); args.append(_clean_text(payload["guardian_name"], "监护人姓名"))
    if "guardian_phone" in payload:
        phone = str(payload["guardian_phone"] or "").strip()
        if not PHONE_RE.match(phone):
            raise ElderError("监护人电话应为 1 开头的 11 位手机号")
        fields.append("guardian_phone=%s"); args.append(phone)
    if "special_tag" in payload:
        fields.append("special_tag=%s"); args.append(_validate_tags(payload["special_tag"]))

    if "status" in payload:
        new_status = payload["status"]
        if new_status not in ("正常", "暂停服务", "注销"):
            raise ElderError("档案状态非法")
        fields.append("status=%s"); args.append(new_status)

    if not fields:
        raise ElderError("没有需要修改的字段")
    args.append(elder_id)
    cur.execute(f"UPDATE elder SET {','.join(fields)} WHERE elder_id=%s", tuple(args))
    return {"elder_id": elder_id, "updated": cur.rowcount}


# ------------------------------------------------------------------ 评估
def record_assessment(cur, elder_id, payload, assessor):
    """录入能力评估：等级按得分核定，结果一年有效；
    该老人因评估过期被暂停的照护计划随复评自动恢复。"""
    _require_elder(cur, elder_id, active_only=True, for_update=True)
    scale = payload.get("scale", "ADL")
    if scale not in SCALES:
        raise ElderError("评估量表只能是「ADL」或「简易智能状态」")
    score = payload.get("score")
    level = level_of_score(score)
    assessor = _clean_text(assessor, "评估员")

    assess_date = _parse_date(payload.get("assess_date") or dt.date.today(), "评估日期")
    if assess_date > dt.date.today():
        raise ElderError("评估日期不能晚于当天")
    expire_date = assess_date + dt.timedelta(days=365)

    cur.execute(
        """INSERT INTO assessment
           (elder_id, scale, score, ability_level, assessor, assess_date, expire_date)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (elder_id, scale, score, level, assessor, assess_date, expire_date),
    )
    assessment_id = cur.lastrowid  # INSERT 后立即保存
    # 复评时仅恢复最新的暂停计划，避免同一老人同时有多个生效计划。
    cur.execute(
        """SELECT plan_id FROM care_plan
           WHERE elder_id=%s AND status='生效'
           LIMIT 1 FOR UPDATE""",
        (elder_id,),
    )
    active_plan = cur.fetchone()
    resumed = 0
    if not active_plan:
        cur.execute(
            """SELECT plan_id FROM care_plan
               WHERE elder_id=%s AND status='暂停'
               ORDER BY plan_id DESC LIMIT 1 FOR UPDATE""",
            (elder_id,),
        )
        paused_plan = cur.fetchone()
        if paused_plan:
            cur.execute(
                "UPDATE care_plan SET status='生效' WHERE plan_id=%s AND status='暂停'",
                (paused_plan["plan_id"],),
            )
            resumed = cur.rowcount
    return {
        "assessment_id": assessment_id,
        "ability_level": level,
        "expire_date": expire_date.strftime("%Y-%m-%d"),
        "resumed_plans": resumed,
    }


def pause_expired_plans(cur):
    """评估到期自动暂停照护计划（与存储过程 sp_pause_expired_plans 同一规则）。
    返回本次暂停的计划数。演示页面走存储过程，DAO 内联同款 UPDATE 便于事务组合。"""
    cur.execute(
        """UPDATE care_plan p
           JOIN (SELECT elder_id, MAX(expire_date) AS latest_expire
                   FROM assessment GROUP BY elder_id) a
             ON a.elder_id = p.elder_id
            SET p.status = '暂停'
          WHERE p.status = '生效'
            AND a.latest_expire < CURDATE()"""
    )
    return {"paused_plans": cur.rowcount}


# ------------------------------------------------------------------ 查询（走视图）
def get_elder_profile(cur, elder_id):
    """档案概览：评估等级/有效期与生效计划（v_elder_assessment_plan，身份证脱敏）。"""
    cur.execute(
        "SELECT * FROM v_elder_assessment_plan WHERE elder_id=%s", (elder_id,)
    )
    row = cur.fetchone()
    if not row:
        raise ElderError("老人档案不存在")
    return row


def list_unassessed_solitary(cur):
    """独居老人未评估清单（v_unassessed_solitary），供安排评估/复评。"""
    cur.execute("SELECT * FROM v_unassessed_solitary ORDER BY community, elder_id")
    return cur.fetchall()


def list_community_distribution(cur):
    """各社区能力等级分布（v_community_ability_distribution）。"""
    cur.execute("SELECT * FROM v_community_ability_distribution ORDER BY community_id")
    return cur.fetchall()
