"""评估提醒站内信。接收人由数据库绑定决定，消息按账号和当前档案双重隔离。"""

from db import transaction
from elder_dao import ElderDAO
from errors import BizError


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
