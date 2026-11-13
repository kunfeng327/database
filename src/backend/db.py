# -*- coding: utf-8 -*-
"""数据库连接配置。

读取顺序：config_local.py（本机实际配置，已被 .gitignore 排除）
       → 环境变量 MYSQL_PWD 等
       → config_example.py 里的默认值
"""
import os

DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PWD", ""),
    "database": os.environ.get("MYSQL_DB", "elder_care"),
    "charset": "utf8mb4",
}

# 尝试用本机私有配置覆盖（里面写着真实密码，不要提交到 GitHub）
_local_path = os.path.join(os.path.dirname(__file__), "config_local.py")
if os.path.exists(_local_path):
    with open(_local_path, "r", encoding="utf-8") as f:
        _code = f.read()
    _ns = {}
    exec(compile(_code, _local_path, "exec"), _ns)
    for _k in ("host", "port", "user", "password", "database"):
        if _k.upper() in _ns:
            DB_CONFIG[_k] = _ns[_k.upper()]

# 环境变量优先（启动演示.bat 用 MYSQL_PWD 同时喂给 mysql 客户端和后端，最不容易出错）
if os.environ.get("MYSQL_HOST"):
    DB_CONFIG["host"] = os.environ["MYSQL_HOST"]
if os.environ.get("MYSQL_PORT"):
    DB_CONFIG["port"] = int(os.environ["MYSQL_PORT"])
if os.environ.get("MYSQL_USER"):
    DB_CONFIG["user"] = os.environ["MYSQL_USER"]
if os.environ.get("MYSQL_PWD"):
    DB_CONFIG["password"] = os.environ["MYSQL_PWD"]
if os.environ.get("MYSQL_DB"):
    DB_CONFIG["database"] = os.environ["MYSQL_DB"]


def transaction(connection_factory, operation):
    """一次连接、一次提交；任一步失败都回滚，调用方不能提前提交。"""
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            result = operation(cur)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
