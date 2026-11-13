"""为尚无家属账号的老人补齐演示登录账号，保留已有账号及其状态。"""

import hashlib
import secrets


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
