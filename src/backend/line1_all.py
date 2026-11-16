"""业务线1（pengkunfeng）后端模块合集。

合并自 errors / db_diagnostics / elder_dao / notification_dao /
demo_family_accounts / prepare_database / demo_server 七个文件，
避免多人协作合入后难以辨认本人代码。共享模块（app.py、db.py、
config_example.py）与业务线5（line5_dao.py）不在本文件内。

分节目录（按依赖顺序）：
  §1 errors              可安全展示的业务异常
  §2 db_diagnostics      数据库故障安全提示（不泄露SQL/凭据）
  §3 elder_dao           档案/评估/照护计划持久层
  §4 notification_dao    家属提醒站内信
  §5 demo_family_accounts 启动时补齐家属演示账号
  §6 prepare_database     启动前检查并升级已有演示库
  §7 demo_server          演示服务启动（绑定端口后才开浏览器）

命令行入口：python line1_all.py --prepare  等价于原 prepare_database.py。
运行后端仍用 python app.py（app.py 从本文件导入 DAO 与 run_demo）。
"""

import datetime as dt
import hashlib
import re
import secrets
import threading
import webbrowser
from pathlib import Path

from db import transaction


# =====================================================================
# §1 业务异常（原 errors.py）
# =====================================================================


class BizError(Exception):
    """可安全展示给用户的业务异常。"""


# =====================================================================
# §2 数据库故障提示（原 db_diagnostics.py）
# =====================================================================


def database_error_message(code):
    """数据库故障的安全提示；不拼接驱动返回的SQL、凭据或用户数据。"""
    if code in (2002, 2003, 2006, 2013):
        return "无法连接 MySQL，请确认数据库服务已启动、连接地址和端口正确，然后重试。"
    if code in (1044, 1045):
        return "数据库连接被拒绝，请检查数据库账号、密码及访问权限。"
    if code == 1049:
        return "数据库尚未初始化。首次演示请运行启动演示.bat，确认无需保留旧数据后选择初始化。"
    if code in (1054, 1146, 1305, 1356):
        return "数据库结构与程序版本不一致，请使用最新版启动演示.bat重新启动并完成保留数据升级。"
    if code in (1142, 1227, 1370):
        return "数据库账号权限不足，请由管理员完成数据库升级或授权后重试。"
    return None


# =====================================================================
# §3 老人档案持久层（原 elder_dao.py）
# SQL 全部参数化；写操作先锁老人行以串行化同一档案的变更。
# =====================================================================

LEVELS = ("能力完好", "轻度失能", "中度失能", "重度失能")
TAGS = ("独居", "失能", "低保", "高龄")
STATUSES = ("正常", "暂停服务", "注销")
# 课程演示口径，不作为医学诊断或补贴资格核定标准。
PACKAGES = {
    "能力完好": ("探访关爱包", "每周2次探访", ("家政", "助餐")),
    "轻度失能": ("助浴助洁包", "每周1次助浴、1次保洁", ("助浴", "家政", "助餐")),
    "中度失能": ("康复助行包", "每周2次康复训练", ("康复护理", "陪诊", "助餐")),
    "重度失能": ("失能照护包", "每日2次上门护理", ("康复护理", "助浴", "助餐")),
}


def text_field(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise BizError(f"{label}不能为空且不能超过 {limit} 个字符")
    return value.strip()


def date_field(value, label):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return dt.date.fromisoformat(value)
    except ValueError:
        raise BizError(f"{label}应为有效日期 YYYY-MM-DD") from None


def positive_id(value, label):
    if type(value) is not int or value <= 0:
        raise BizError(f"{label}应为正整数")
    return value


def ability_level(score):
    if type(score) is not int or not 0 <= score <= 100:
        raise BizError("得分应为 0-100 的整数")
    return LEVELS[0 if score >= 85 else 1 if score >= 75 else 2 if score >= 50 else 3]


class ElderDAO:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def _write(self, operation):
        return transaction(self.connection_factory, operation)

    def _read(self, sql, args=()):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return cur.fetchall()
        finally:
            conn.close()

    @staticmethod
    def _lock_elder(cur, elder_id, normal=False):
        cur.execute("SELECT * FROM elder WHERE elder_id=%s FOR UPDATE", (elder_id,))
        elder = cur.fetchone()
        if not elder:
            raise BizError("老人档案不存在")
        if normal and elder["status"] != "正常":
            raise BizError("老人档案已暂停服务或注销")
        return elder

    @staticmethod
    def _valid_assessment(cur, elder_id):
        cur.execute(
            """SELECT *, CURDATE() AS today FROM assessment WHERE elder_id=%s
                       ORDER BY assess_date DESC, assessment_id DESC LIMIT 1""",
            (elder_id,),
        )
        row = cur.fetchone()
        if not row or not row["assess_date"] <= row["today"] <= row["expire_date"]:
            raise BizError("请先完成有效的能力评估或复评")
        return row

    def list_elders(
        self,
        elder_id=None,
        keyword="",
        community_id=None,
        status=None,
        page=None,
        page_size=20,
    ):
        clauses, args = [], []
        for field, value in [
            ("elder_id", elder_id),
            ("community_id", community_id),
            ("elder_status", status),
        ]:
            if value is not None:
                clauses.append(field + "=%s")
                args.append(value)
        if keyword:
            clauses.append("name LIKE %s")
            args.append("%" + keyword + "%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        # 显式选列并全隐藏，旧库视图尚未升级时也不返回身份证的任何片段。
        sql = """SELECT elder_id,name,age,community_id,community,special_tag,elder_status,
                 ability_level,assess_expire,assess_expired,plan_id,package_name,plan_status,
                 REPEAT('*',18) AS id_masked FROM v_elder_assessment_plan""" + where + " ORDER BY elder_id"
        if page is None:
            return self._read(sql, tuple(args))
        total = self._read(
            "SELECT COUNT(*) AS n FROM v_elder_assessment_plan" + where, tuple(args)
        )[0]["n"]
        rows = self._read(
            sql + " LIMIT %s OFFSET %s",
            tuple(args) + (page_size, (page - 1) * page_size),
        )
        return rows, total

    def get_elder(self, elder_id):
        rows = self._read(
            """SELECT e.elder_id, e.name, e.birth_date, e.gender, e.address,
            e.community_id, c.name AS community, e.guardian_name, e.guardian_phone,
            e.special_tag, e.status, e.created_at,
            REPEAT('*',18) AS id_masked
            FROM elder e JOIN community c ON c.community_id=e.community_id
            WHERE e.elder_id=%s""",
            (elder_id,),
        )
        if not rows:
            raise BizError("老人档案不存在")
        return rows[0]

    @staticmethod
    def _elder_fields(body, creating):
        if not isinstance(body, dict):
            raise BizError("档案应为 JSON 对象")
        values = {
            key: text_field(body.get(key), label, limit)
            for key, label, limit in (
                ("name", "姓名", 30),
                ("address", "居住地址", 100),
                ("guardian_name", "监护人姓名", 30),
                ("guardian_phone", "监护人电话", 11),
            )
        }
        if not re.fullmatch(r"1[3-9]\d{9}", values["guardian_phone"]):
            raise BizError("监护人电话应为 11 位手机号")
        values["birth_date"] = date_field(body.get("birth_date"), "出生日期")
        if values["birth_date"] > dt.date.today():
            raise BizError("出生日期不能晚于今天")
        if body.get("gender") not in ("男", "女"):
            raise BizError("性别应为男或女")
        values["gender"] = body["gender"]
        values["community_id"] = positive_id(body.get("community_id"), "社区编号")
        tags = body.get("special_tag", [])
        if not isinstance(tags, list) or any(tag not in TAGS for tag in tags):
            raise BizError("特殊标签应为独居、失能、低保、高龄组成的数组")
        values["special_tag"] = ",".join(tag for tag in TAGS if tag in tags) or None
        if creating:
            card = text_field(body.get("id_card"), "身份证号", 18).upper()
            if not re.fullmatch(r"\d{17}[\dX]", card):
                raise BizError("身份证号应为18位，末位可为X")
            if card[6:14] != values["birth_date"].strftime("%Y%m%d"):
                raise BizError("身份证中的出生日期与档案不一致")
            values["id_card"] = card
        elif "id_card" in body:
            raise BizError("身份证号不可修改；跨社区迁移请修改所属社区")
        return values

    @staticmethod
    def _community(cur, community_id):
        cur.execute(
            "SELECT community_id FROM community WHERE community_id=%s", (community_id,)
        )
        if not cur.fetchone():
            raise BizError("所属社区不存在")

    def create_elders(self, bodies):
        if not isinstance(bodies, list) or not 1 <= len(bodies) <= 100:
            raise BizError("每批应包含1至100份档案")
        records = [self._elder_fields(body, True) for body in bodies]

        def operation(cur):
            ids = []
            for values in records:
                self._community(cur, values["community_id"])
                fields = ",".join(values)
                placeholders = ",".join(["%s"] * len(values))
                cur.execute(
                    f"INSERT INTO elder ({fields}) VALUES ({placeholders})",
                    tuple(values.values()),
                )
                ids.append(cur.lastrowid)
            return ids

        return self._write(operation)

    def update_elder(self, elder_id, body):
        values = self._elder_fields(body, False)

        def operation(cur):
            elder = self._lock_elder(cur, elder_id)
            if elder["status"] == "注销":
                raise BizError("注销档案只读")
            if values["birth_date"] != elder["birth_date"]:
                raise BizError("出生日期不可修改，以原身份证档案为准")
            self._community(cur, values["community_id"])
            fields = ",".join(key + "=%s" for key in values)
            cur.execute(
                f"UPDATE elder SET {fields} WHERE elder_id=%s",
                tuple(values.values()) + (elder_id,),
            )
            return {"elder_id": elder_id}

        return self._write(operation)

    def set_elder_status(self, elder_id, status):
        if status not in STATUSES:
            raise BizError("档案状态只能为正常、暂停服务、注销")

        def operation(cur):
            elder = self._lock_elder(cur, elder_id)
            if elder["status"] == "注销" and status != "注销":
                raise BizError("注销档案不可重新启用")
            cur.execute(
                "UPDATE elder SET status=%s WHERE elder_id=%s", (status, elder_id)
            )
            if status == "注销":
                cur.execute(
                    "UPDATE care_plan SET status='结束', pause_reason=NULL WHERE elder_id=%s AND status<>'结束'",
                    (elder_id,),
                )
            elif status == "暂停服务":
                cur.execute(
                    "UPDATE care_plan SET status='暂停', pause_reason='档案暂停' WHERE elder_id=%s AND status='生效'",
                    (elder_id,),
                )
            return {"elder_id": elder_id, "status": status}

        return self._write(operation)

    def assessments(self, elder_id):
        return self._read(
            """SELECT *, (expire_date < CURDATE()) AS expired,
            DATEDIFF(expire_date,CURDATE()) AS days_left FROM assessment
            WHERE elder_id=%s ORDER BY assess_date DESC, assessment_id DESC""",
            (elder_id,),
        )

    def create_assessment(self, elder_id, body, assessor):
        score = body.get("score")
        level = ability_level(score)
        scale = body.get("scale", "ADL")
        if scale not in ("ADL", "简易智能状态"):
            raise BizError("评估量表只能为 ADL 或简易智能状态")
        assessor = text_field(assessor, "评估员", 30)

        def operation(cur):
            self._lock_elder(cur, elder_id, normal=True)
            cur.execute(
                """INSERT INTO assessment
                (elder_id,scale,score,ability_level,assessor,assess_date,expire_date)
                VALUES (%s,%s,%s,%s,%s,CURDATE(),DATE_ADD(CURDATE(),INTERVAL 1 YEAR))""",
                (elder_id, scale, score, level, assessor),
            )
            assessment_id = cur.lastrowid
            # 日期由数据库返回，避免闰年和应用/数据库时区不同产生误差。
            cur.execute(
                "SELECT expire_date FROM assessment WHERE assessment_id=%s",
                (assessment_id,),
            )
            expire_date = cur.fetchone()["expire_date"]
            cur.execute(
                """SELECT * FROM care_plan WHERE elder_id=%s AND status='暂停'
                AND pause_reason='评估过期' AND end_date>=CURDATE()
                AND EXISTS (SELECT 1 FROM care_plan_item pi WHERE pi.plan_id=care_plan.plan_id)
                ORDER BY start_date,plan_id""",
                (elder_id,),
            )
            candidates = cur.fetchall()
            resumed = 0
            for plan in candidates:
                if not self._overlap(
                    cur, elder_id, plan["start_date"], plan["end_date"], plan["plan_id"]
                ):
                    cur.execute(
                        "UPDATE care_plan SET status='生效',pause_reason=NULL WHERE plan_id=%s",
                        (plan["plan_id"],),
                    )
                    resumed += 1
            return {
                "assessment_id": assessment_id,
                "ability_level": level,
                "expire_date": expire_date,
                "resumed_plans": resumed,
            }

        return self._write(operation)

    def plans(self, elder_id):
        plans = self._read(
            """SELECT p.*, c.name AS caregiver_name FROM care_plan p
            LEFT JOIN caregiver c ON c.caregiver_id=p.caregiver_id
            WHERE p.elder_id=%s ORDER BY p.start_date DESC,p.plan_id DESC""",
            (elder_id,),
        )
        items = self._read(
            """SELECT pi.plan_id,si.item_id,si.name,si.type FROM care_plan_item pi
            JOIN service_item si ON si.item_id=pi.item_id JOIN care_plan p ON p.plan_id=pi.plan_id
            WHERE p.elder_id=%s ORDER BY pi.plan_id,si.item_id""",
            (elder_id,),
        )
        for plan in plans:
            plan["items"] = [
                item for item in items if item["plan_id"] == plan["plan_id"]
            ]
        return plans

    @staticmethod
    def _overlap(cur, elder_id, start, end, excluding=0):
        # 老人行已锁住；相同老人所有计划写入必须遵循同一锁顺序。
        cur.execute(
            """SELECT plan_id FROM care_plan WHERE elder_id=%s AND status='生效'
            AND start_date<=%s AND end_date>=%s AND plan_id<>%s LIMIT 1 FOR UPDATE""",
            (elder_id, end, start, excluding),
        )
        return cur.fetchone()

    def save_plan(self, elder_id, body, plan_id=None):
        name = text_field(body.get("package_name"), "服务包名称", 50)
        frequency = text_field(body.get("frequency"), "服务频次", 50)
        start = date_field(body.get("start_date"), "开始日期")
        end = date_field(body.get("end_date"), "结束日期")
        if end < start:
            raise BizError("结束日期不能早于开始日期")
        caregiver_id = body.get("caregiver_id")
        if caregiver_id is not None:
            positive_id(caregiver_id, "责任护工编号")
        items = body.get("item_ids")
        if not isinstance(items, list) or not items or len(items) > 100:
            raise BizError("计划应包含1至100个服务项目")
        for item in items:
            positive_id(item, "服务项目编号")
        items = sorted(set(items))

        def operation(cur):
            self._lock_elder(cur, elder_id, normal=True)
            assessment = self._valid_assessment(cur, elder_id)
            if end < assessment["today"]:
                raise BizError("不能创建或编辑已经到期的计划")
            status = "生效"
            if plan_id is not None:
                cur.execute(
                    "SELECT status FROM care_plan WHERE elder_id=%s AND plan_id=%s",
                    (elder_id, plan_id),
                )
                old = cur.fetchone()
                if not old or old["status"] == "结束":
                    raise BizError("计划不存在或已结束")
                status = old["status"]
            if status == "生效" and self._overlap(
                cur, elder_id, start, end, plan_id or 0
            ):
                raise BizError("该时段已有生效照护计划（起止日期均包含在内）")
            if caregiver_id:
                cur.execute(
                    "SELECT caregiver_id FROM caregiver WHERE caregiver_id=%s AND on_duty='在岗' AND cert_expire>=CURDATE()",
                    (caregiver_id,),
                )
                if not cur.fetchone():
                    raise BizError("责任护工不存在、已离职或证书已过期")
            placeholders = ",".join(["%s"] * len(items))
            cur.execute(
                f"SELECT item_id FROM service_item WHERE item_id IN ({placeholders})",
                tuple(items),
            )
            if len(cur.fetchall()) != len(items):
                raise BizError("服务项目不存在")
            values = (name, frequency, start, end, caregiver_id)
            if plan_id is None:
                cur.execute(
                    """INSERT INTO care_plan
                    (package_name,frequency,start_date,end_date,caregiver_id,elder_id)
                    VALUES (%s,%s,%s,%s,%s,%s)""",
                    values + (elder_id,),
                )
                saved_id = cur.lastrowid
            else:
                saved_id = plan_id
                cur.execute(
                    """UPDATE care_plan SET package_name=%s,frequency=%s,start_date=%s,
                    end_date=%s,caregiver_id=%s WHERE plan_id=%s""",
                    values + (saved_id,),
                )
                cur.execute("DELETE FROM care_plan_item WHERE plan_id=%s", (saved_id,))
            cur.executemany(
                "INSERT INTO care_plan_item (plan_id,item_id) VALUES (%s,%s)",
                [(saved_id, item) for item in items],
            )
            return {"plan_id": saved_id}

        return self._write(operation)

    def set_plan_status(self, elder_id, plan_id, status):
        if status not in ("生效", "暂停", "结束"):
            raise BizError("计划状态只能为生效、暂停、结束")

        def operation(cur):
            self._lock_elder(cur, elder_id, normal=(status == "生效"))
            cur.execute(
                "SELECT *,CURDATE() AS today FROM care_plan WHERE elder_id=%s AND plan_id=%s",
                (elder_id, plan_id),
            )
            plan = cur.fetchone()
            if not plan or plan["status"] == "结束":
                raise BizError("计划不存在或已结束")
            if status == "生效":
                self._valid_assessment(cur, elder_id)
                if plan["end_date"] < plan["today"]:
                    raise BizError("计划已经到期，不能恢复")
                cur.execute(
                    "SELECT COUNT(*) AS n FROM care_plan_item WHERE plan_id=%s",
                    (plan_id,),
                )
                if not cur.fetchone()["n"]:
                    raise BizError("请先编辑计划并补齐服务项目清单")
                if self._overlap(
                    cur, elder_id, plan["start_date"], plan["end_date"], plan_id
                ):
                    raise BizError("该时段已有生效照护计划")
            cur.execute(
                "UPDATE care_plan SET status=%s,pause_reason=%s WHERE plan_id=%s",
                (status, "手动暂停" if status == "暂停" else None, plan_id),
            )
            return {"plan_id": plan_id, "status": status}

        return self._write(operation)

    def recommendations(self, elder_id):
        rows = self.assessments(elder_id)
        if not rows or rows[0]["expired"]:
            raise BizError("请先完成有效的能力评估或复评")
        level = rows[0]["ability_level"]
        name, frequency, types = PACKAGES[level]
        items = self._read(
            "SELECT item_id,name,type FROM service_item WHERE type IN ("
            + ",".join(["%s"] * len(types))
            + ") ORDER BY item_id",
            types,
        )
        return {
            "ability_level": level,
            "package_name": name,
            "frequency": frequency,
            "items": items,
        }

    def pause_expired(self):
        def operation(cur):
            cur.execute("CALL sp_pause_expired_plans()")
            result = cur.fetchone()
            while cur.nextset():
                pass
            return result

        return self._write(operation)


# =====================================================================
# §4 家属提醒站内信（原 notification_dao.py）
# 接收人由数据库绑定决定，消息按账号和当前档案双重隔离。
# =====================================================================


class NotificationDAO:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def send_reminder(self, elder_id, sender_id):
        def operation(cur):
            elder = ElderDAO._lock_elder(cur, elder_id, normal=True)
            # 锁定读取与建评估共用的老人行后，再读取最新评估，避免发送过时提醒。
            cur.execute(
                """SELECT assessment_id,expire_date,
                   DATEDIFF(expire_date,CURDATE()) AS days_left
                   FROM assessment WHERE elder_id=%s
                   ORDER BY assess_date DESC,assessment_id DESC LIMIT 1 FOR UPDATE""",
                (elder_id,),
            )
            assessment = cur.fetchone()
            if not assessment:
                kind, key = "首次评估提醒", "unassessed"
                detail = "尚未完成能力评估，请联系所属社区安排首次评估。"
            elif assessment["days_left"] > 30:
                raise BizError("该老人当前无需评估提醒，请刷新清单后重试")
            else:
                expired = assessment["days_left"] < 0
                kind = "评估过期提醒" if expired else "复评提醒"
                key = f"{assessment['assessment_id']}:{'expired' if expired else 'due'}"
                detail = (
                    f"能力评估已于 {assessment['expire_date']} 过期，请尽快联系所属社区安排复评。"
                    if expired
                    else f"能力评估将于 {assessment['expire_date']} 到期（剩余 {assessment['days_left']} 天），请联系所属社区安排复评。"
                )
            cur.execute(
                """SELECT user_id FROM sys_user WHERE elder_id=%s
                   AND role='家属' AND status='启用' ORDER BY user_id FOR UPDATE""",
                (elder_id,),
            )
            recipients = cur.fetchall()
            if not recipients:
                raise BizError(
                    "该老人尚未绑定启用的家属账号，无法发送站内提醒，请先配置家属账号绑定"
                )
            cur.execute(
                """SELECT recipient_id FROM family_notification
                   WHERE elder_id=%s AND reminder_key=%s AND sent_date=CURDATE() FOR UPDATE""",
                (elder_id, key),
            )
            sent = {row["recipient_id"] for row in cur.fetchall()}
            created = 0
            for recipient in recipients:
                if recipient["user_id"] in sent:
                    continue
                cur.execute(
                    """INSERT INTO family_notification
                       (recipient_id,elder_id,sender_id,reminder_key,sent_date,title,content)
                       VALUES (%s,%s,%s,%s,CURDATE(),%s,%s)""",
                    (
                        recipient["user_id"],
                        elder_id,
                        sender_id,
                        key,
                        kind,
                        f"{elder['name']}家属您好：{detail}",
                    ),
                )
                created += 1
            return {
                "created_count": created,
                "existing_count": len(recipients) - created,
                "recipient_count": len(recipients),
            }

        return transaction(self.connection_factory, operation)

    @staticmethod
    def _scope():
        # 即使旧登录会话仍保留原档案，解绑/改绑/停用后也不能读原家庭消息。
        return """FROM family_notification n JOIN sys_user u ON u.user_id=n.recipient_id
                  AND u.elder_id=n.elder_id
                  WHERE n.recipient_id=%s AND u.role='家属' AND u.status='启用'"""

    def inbox(self, user_id, page=1, page_size=20):
        def operation(cur):
            cur.execute(
                "SELECT COUNT(*) AS total,COALESCE(SUM(n.read_at IS NULL),0) AS unread_count "
                + self._scope(),
                (user_id,),
            )
            counts = cur.fetchone()
            cur.execute(
                "SELECT n.notification_id,n.elder_id,n.title,n.content,n.created_at,n.read_at "
                + self._scope()
                + " ORDER BY n.created_at DESC,n.notification_id DESC LIMIT %s OFFSET %s",
                (user_id, page_size, (page - 1) * page_size),
            )
            return {
                "messages": cur.fetchall(),
                "total": int(counts["total"]),
                "unread_count": int(counts["unread_count"]),
                "page": page,
                "page_size": page_size,
            }

        return transaction(self.connection_factory, operation)

    def mark_read(self, notification_id, user_id):
        def operation(cur):
            cur.execute(
                "SELECT n.notification_id "
                + self._scope()
                + " AND n.notification_id=%s FOR UPDATE",
                (user_id, notification_id),
            )
            if not cur.fetchone():
                raise BizError("消息不存在或无权访问")
            cur.execute(
                "UPDATE family_notification SET read_at=COALESCE(read_at,NOW()) "
                "WHERE notification_id=%s AND recipient_id=%s",
                (notification_id, user_id),
            )
            return {"notification_id": notification_id}

        return transaction(self.connection_factory, operation)


# =====================================================================
# §5 家属演示账号补齐（原 demo_family_accounts.py）
# =====================================================================


def create_missing_family_accounts(conn):
    """原子补齐；重复启动不重置密码，也不绕过已有家属账号的停用状态。"""
    created = []
    try:
        with conn.cursor() as cur:
            # 与提醒发送采用相同的老人行锁；并发启动按档案编号依次处理。
            cur.execute(
                "SELECT elder_id,name,guardian_name FROM elder ORDER BY elder_id FOR UPDATE"
            )
            for elder in cur.fetchall():
                cur.execute(
                    "SELECT user_id FROM sys_user WHERE elder_id=%s AND role='家属' FOR UPDATE",
                    (elder["elder_id"],),
                )
                if cur.fetchone():
                    continue

                name = elder["name"].strip() or f"老人{elder['elder_id']}"
                username, attempt = name, 0
                while True:
                    # 用数据库实际排序规则判断同名，避免抢占其他家庭或角色的账号。
                    cur.execute(
                        "SELECT user_id FROM sys_user WHERE username=%s FOR UPDATE",
                        (username,),
                    )
                    if not cur.fetchone():
                        break
                    attempt += 1
                    suffix = f"_{elder['elder_id']}" + (f"_{attempt}" if attempt > 1 else "")
                    username = name[:30 - len(suffix)] + suffix

                salt = secrets.token_hex(8)
                password_hash = hashlib.sha256((salt + "123456").encode("utf-8")).hexdigest()
                cur.execute(
                    """INSERT INTO sys_user
                    (username,password_hash,salt,real_name,role,elder_id,status)
                    VALUES (%s,%s,%s,%s,'家属',%s,'启用')""",
                    (username, password_hash, salt, elder["guardian_name"] or name, elder["elder_id"]),
                )
                created.append({"elder_id": elder["elder_id"], "elder_name": elder["name"], "username": username})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return created


# =====================================================================
# §6 启动检查与升级（原 prepare_database.py）
# 不会创建/清空业务库或重新导入种子数据，已有账号保持不变。
# 可重复运行；MySQL DDL隐式提交，失败后修正权限等问题再重试。
# =====================================================================

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
BASE_TABLES = {
    "community",
    "elder",
    "assessment",
    "care_plan",
    "caregiver",
    "service_item",
    "service_order",
    "dispatch",
    "schedule",
    "subsidy_policy",
    "subsidy_claim",
    "sys_user",
}


def sql_statements(source):
    """读取仓库中的SQL脚本，识别DELIMITER、字符串及行注释。"""
    delimiter = ";"
    buffer = ""
    quote = None
    for line in source.splitlines(keepends=True):
        if (
            not quote
            and not buffer.strip()
            and line.strip().upper().startswith("DELIMITER ")
        ):
            delimiter = line.strip().split()[1]
            continue
        pos = 0
        while pos < len(line):
            char = line[pos]
            if quote:
                buffer += char
                if char == "\\" and pos + 1 < len(line):
                    pos += 1
                    buffer += line[pos]
                elif char == quote:
                    if pos + 1 < len(line) and line[pos + 1] == quote:
                        pos += 1
                        buffer += line[pos]
                    else:
                        quote = None
                pos += 1
                continue
            if line.startswith("--", pos) and (
                pos + 2 == len(line) or line[pos + 2].isspace()
            ):
                buffer += "\n"
                break
            if char in ("'", '"', "`"):
                quote = char
            elif line.startswith(delimiter, pos):
                if buffer.strip():
                    yield buffer.strip()
                buffer = ""
                pos += len(delimiter)
                continue
            buffer += char
            pos += 1
    if quote or buffer.strip():
        raise ValueError("SQL脚本未正常结束")


def schema_objects(source):
    return set(
        re.findall(r"CREATE (?:OR REPLACE )?(?:VIEW|PROCEDURE|TRIGGER)\s+(\w+)", source)
    )


def prepare_database(conn):
    view_sql = (SQL_DIR / "03_views.sql").read_text(encoding="utf-8")
    routine_sql = (SQL_DIR / "04_procs_triggers.sql").read_text(encoding="utf-8")
    # 在任何DDL之前完整解析脚本，语法分隔错误时不开始升级。
    scripts = list(sql_statements(view_sql)) + list(sql_statements(routine_sql))
    # 站内信建表语句收录于 09_line1_all.sql §D；启动检查只执行该建表语句，
    # 合集其余各节（一次性升级/定时事件/演示查询）不得在启动时执行。
    notification_scripts = [
        statement
        for statement in sql_statements((SQL_DIR / "09_line1_all.sql").read_text(encoding="utf-8"))
        if statement.upper().startswith("CREATE TABLE IF NOT EXISTS FAMILY_NOTIFICATION")
    ]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME AS name FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
        )
        tables = {row["name"] for row in cur.fetchall()}
        if not BASE_TABLES <= tables:
            raise ValueError(
                "数据库基础表不完整。请先备份并按README完成初始化；本检查不会清空已有数据。"
            )
        cur.execute(
            "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='care_plan'"
        )
        columns = {row["name"] for row in cur.fetchall()}
        cur.execute(
            """SELECT TABLE_NAME AS table_name,INDEX_NAME AS name,COLUMN_NAME AS column_name
            FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
            AND TABLE_NAME IN ('assessment','care_plan') ORDER BY SEQ_IN_INDEX"""
        )
        indexes = {}
        for row in cur.fetchall():
            indexes.setdefault((row["table_name"], row["name"]), []).append(
                row["column_name"]
            )
        cur.execute(
            "SELECT ROUTINE_NAME AS name FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()"
        )
        routines = {row["name"] for row in cur.fetchall()}
        cur.execute(
            "SELECT TRIGGER_NAME AS name FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"
        )
        triggers = {row["name"] for row in cur.fetchall()}
        statements = []
        if "pause_reason" not in columns:
            statements.append(
                "ALTER TABLE care_plan ADD COLUMN pause_reason VARCHAR(20) NULL COMMENT '暂停原因'"
            )
        # 恢复此前中断在ADD COLUMN之后的升级。
        cur.execute(
            "SELECT CONSTRAINT_NAME AS name FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='care_plan'"
        )
        constraints = {row["name"] for row in cur.fetchall()}
        if "chk_pause_reason" not in constraints:
            statements.append(
                """ALTER TABLE care_plan ADD CONSTRAINT chk_pause_reason CHECK
                (pause_reason IS NULL OR (status='暂停' AND pause_reason IN ('评估过期','手动暂停','档案暂停')))"""
            )
        if ("assessment", "idx_assess_latest") not in indexes:
            statements.append(
                "ALTER TABLE assessment ADD INDEX idx_assess_latest (elder_id,assess_date,assessment_id)"
            )
        if indexes.get(("care_plan", "idx_plan_elder")) != [
            "elder_id",
            "status",
            "start_date",
            "end_date",
        ]:
            drop = (
                "DROP INDEX idx_plan_elder,"
                if ("care_plan", "idx_plan_elder") in indexes
                else ""
            )
            statements.append(
                "ALTER TABLE care_plan "
                + drop
                + "ADD INDEX idx_plan_elder (elder_id,status,start_date,end_date)"
            )
        if "care_plan_item" not in tables:
            statements.append(
                """CREATE TABLE care_plan_item (
                plan_id INT NOT NULL,item_id INT NOT NULL,PRIMARY KEY (plan_id,item_id),
                CONSTRAINT fk_plan_item_plan FOREIGN KEY (plan_id) REFERENCES care_plan(plan_id),
                CONSTRAINT fk_plan_item_service FOREIGN KEY (item_id) REFERENCES service_item(item_id)) ENGINE=InnoDB"""
            )
        cur.execute("SELECT VIEW_DEFINITION AS definition FROM information_schema.VIEWS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='v_elder_assessment_plan'")
        archive_view = cur.fetchone()
        # 旧视图保留身份证前后片段，升级为全部隐藏。
        partial_identity = bool(archive_view and "id_card" in (archive_view["definition"] or "").lower())
        changed = (
            bool(statements)
            or partial_identity
            or not schema_objects(view_sql) <= tables
            or not schema_objects(routine_sql) <= routines | triggers
        )
        notifications_missing = "family_notification" not in tables
        if changed:
            for statement in statements:
                cur.execute(statement)
            cur.execute(
                "UPDATE care_plan SET pause_reason='手动暂停' WHERE status='暂停' AND pause_reason IS NULL"
            )
            for statement in scripts:
                # 保持使用连接指定的库，禁止脚本USE切换到别的库（也便于独立测试库验证）。
                if not statement.upper().startswith("USE "):
                    cur.execute(statement)
        if notifications_missing:
            for statement in notification_scripts:
                if not statement.upper().startswith("USE "):
                    cur.execute(statement)
        if changed or notifications_missing:
            conn.commit()
        cur.execute("SELECT COUNT(*) AS n FROM sys_user")
        users = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM elder")
        elders = cur.fetchone()["n"]
    return {"upgraded": changed or notifications_missing, "users": users, "elders": elders}


def main():
    import pymysql
    from db import DB_CONFIG

    conn = None
    try:
        conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CONFIG)
        result = prepare_database(conn)
        if result["upgraded"]:
            print(
                "[完成] 数据库结构已升级，原有档案和业务数据已保留；旧计划的服务项目请在页面核实补录。"
            )
        if not result["users"]:
            print(
                "[错误] 数据库没有登录账号。请先备份，再按README初始化演示数据或由管理员配置账号。"
            )
            return 1
        accounts = create_missing_family_accounts(conn)
        if accounts:
            print(f"[完成] 已补齐 {len(accounts)} 个家属账号，密码均为123456；已有账号保持不变。")
            for account in accounts:
                print(f"  {account['elder_name']}（档案{account['elder_id']}）→ 账号：{account['username']}")
        print(f"[就绪] 数据库中有 {result['elders']} 份老人档案。")
        if not result["elders"]:
            print(
                "[提示] 当前库确实没有老人档案，可登录后新建。演示样例需显式初始化，不会自动覆盖已有业务数据。"
            )
        return 0
    except pymysql.err.MySQLError as error:
        if conn:
            conn.rollback()
        message = database_error_message(error.args[0] if error.args else None)
        print(
            "[错误] "
            + (
                message
                or "数据库升级未完成，请检查MySQL版本及升级权限；已完成的结构变更可在下次启动时继续检查。"
            )
        )
        return 1
    except ValueError as error:
        print("[错误] " + str(error))
        return 1
    finally:
        if conn:
            conn.close()


# =====================================================================
# §7 演示服务启动（原 demo_server.py）
# 成功绑定本机演示端口后才打开浏览器，避免误用仍在运行的旧后端。
# =====================================================================

URL = "http://127.0.0.1:5000"


def run_demo(app, *, open_browser=False, server_factory=None):
    if server_factory is None:
        from werkzeug.serving import make_server

        server_factory = make_server
    try:
        server = server_factory("127.0.0.1", 5000, app, threaded=True)
    except (OSError, SystemExit):
        print(
            "[错误] 后端未能监听本机5000端口，浏览器未打开。请关闭旧的后端窗口或占用该端口的程序，再重新启动。"
        )
        return 1

    print(f"养老服务平台演示后端已启动 → {URL}")
    print(
        "演示账号（密码均为 123456）：shequ / jiashu / jiashu2 / hugong / jigou / jianguan"
    )
    browser = None
    try:
        if open_browser:
            browser = threading.Timer(0.5, webbrowser.open, args=(URL,))
            browser.daemon = True
            browser.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if browser:
            browser.cancel()
        server.server_close()
    return 0


if __name__ == "__main__":
    import sys

    if "--prepare" in sys.argv:
        raise SystemExit(main())
    print("用法：python line1_all.py --prepare  # 启动前检查并升级演示库（原 prepare_database.py）")
    raise SystemExit(2)
