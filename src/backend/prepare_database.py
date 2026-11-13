"""一键启动前检查并升级已有演示库。不会创建/清空业务库或导入种子数据。

可重复运行；MySQL DDL隐式提交，失败后修正权限等问题再重试。
仅缺失结构时执行升级，正常启动不重复重建视图/触发器。
"""

from pathlib import Path
import re

from db_diagnostics import database_error_message

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
    notification_scripts = list(sql_statements((SQL_DIR / "08_family_notifications.sql").read_text(encoding="utf-8")))
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


if __name__ == "__main__":
    raise SystemExit(main())
