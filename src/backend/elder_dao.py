"""业务线 1 持久层。SQL 全部参数化；写操作先锁老人行以串行化同一档案的变更。"""

import datetime as dt
import re

from db import transaction
from errors import BizError

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
        sql = "SELECT * FROM v_elder_assessment_plan" + where + " ORDER BY elder_id"
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
            CONCAT(LEFT(e.id_card,6),'********',RIGHT(e.id_card,4)) AS id_masked
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
