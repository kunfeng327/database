# -*- coding: utf-8 -*-
"""Line 4 persistence operations: health monitoring and emergency response."""
import datetime as dt


class Line4Error(Exception):
    """A line-4 business rule was not satisfied."""


DEVICE_TYPES = ("血压计", "心电贴", "跌倒雷达", "一键呼叫")
METRIC_TYPES = ("收缩压", "舒张压", "心率", "血氧", "体温", "血糖")
TRIGGER_SOURCES = ("设备告警", "家属呼叫", "主动上报")
EVENT_LEVELS = ("一般", "紧急", "危急")


def _clean_text(value, field_name, required=False):
    text = str(value or "").strip()
    if required and not text:
        raise Line4Error(f"{field_name}不能为空")
    return text or None


def _require_elder(cur, elder_id):
    cur.execute(
        "SELECT elder_id, name FROM elder WHERE elder_id=%s AND status='正常'",
        (elder_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line4Error("老人档案不存在或已暂停服务")
    return row


def _require_device(cur, device_id, must_bound=True):
    cur.execute(
        "SELECT device_id, elder_id, device_type, status FROM device WHERE device_id=%s",
        (device_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line4Error("监测设备不存在")
    if must_bound and row["status"] != "绑定":
        raise Line4Error("该设备当前已解绑，无法采集数据")
    return row


def _parse_datetime(text):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return dt.datetime.strptime(str(text).strip(), fmt)
        except (ValueError, TypeError):
            continue
    raise Line4Error("时间格式应为 YYYY-MM-DD HH:MM")


# ------------------------------------------------------------------ 设备
def bind_device(cur, payload):
    """Bind a device to an elder (one device bound to one elder at a time)."""
    device_type = payload.get("device_type")
    if device_type not in DEVICE_TYPES:
        raise Line4Error("设备类型只能是「血压计/心电贴/跌倒雷达/一键呼叫」")
    elder_id = int(payload["elder_id"])
    _require_elder(cur, elder_id)
    location = _clean_text(payload.get("install_location"), "安装位置", required=True)

    cur.execute(
        """INSERT INTO device (elder_id, device_type, install_location, bind_time, status)
           VALUES (%s,%s,%s,NOW(),'绑定')""",
        (elder_id, device_type, location),
    )
    return {"device_id": cur.lastrowid, "status": "绑定"}


def unbind_device(cur, device_id):
    """Unbind a device; historical vital-sign/emergency data keeps its owner."""
    device_id = int(device_id)
    row = _require_device(cur, device_id, must_bound=False)
    if row["status"] == "解绑":
        raise Line4Error("该设备已处于解绑状态")
    cur.execute(
        """UPDATE device
              SET status='解绑', unbind_time=NOW()
            WHERE device_id=%s AND status='绑定'""",
        (device_id,),
    )
    if cur.rowcount == 0:
        raise Line4Error("设备不存在或已解绑")
    return {"device_id": device_id, "status": "解绑"}


# ------------------------------------------------------------------ 体征
def record_vital_sign(cur, payload):
    """Record a vital sign. The abnormal flag is auto-set by the DB trigger."""
    device_id = int(payload["device_id"])
    device = _require_device(cur, device_id)
    metric_type = payload.get("metric_type")
    if metric_type not in METRIC_TYPES:
        raise Line4Error("指标类型不合法")
    try:
        value = float(payload["metric_value"])
    except (TypeError, ValueError):
        raise Line4Error("指标值必须是数字")
    source = payload.get("data_source", "自动采集")
    if source not in ("自动采集", "人工录入"):
        raise Line4Error("数据来源只能是「自动采集」或「人工录入」")

    collect_time = payload.get("collect_time") or dt.datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )
    collect_time = _parse_datetime(collect_time)

    cur.execute(
        """INSERT INTO vital_sign
           (device_id, elder_id, collect_time, metric_type, metric_value, data_source)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (device_id, device["elder_id"], collect_time, metric_type, value, source),
    )
    cur.execute(
        "SELECT abnormal_flag FROM vital_sign WHERE vital_id=%s", (cur.lastrowid,)
    )
    flag = cur.fetchone()["abnormal_flag"]
    return {
        "vital_id": cur.lastrowid,
        "elder_id": device["elder_id"],
        "abnormal_flag": flag,
    }


def confirm_vital_abnormal(cur, vital_id, decision):
    """Confirm (异常) or dismiss (正常) a pending abnormal flag."""
    vital_id = int(vital_id)
    if decision not in ("异常", "正常"):
        raise Line4Error("处置结果只能是「异常」或「正常」")
    cur.execute(
        """SELECT abnormal_flag FROM vital_sign WHERE vital_id=%s FOR UPDATE""",
        (vital_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line4Error("体征数据不存在")
    if row["abnormal_flag"] != "待确认":
        raise Line4Error("该体征数据不是「待确认」状态，无需复核")
    cur.execute(
        "UPDATE vital_sign SET abnormal_flag=%s WHERE vital_id=%s",
        (decision, vital_id),
    )
    return {"vital_id": vital_id, "abnormal_flag": decision}


# ------------------------------------------------------------------ 应急事件
def create_emergency(cur, payload):
    """Create an emergency event; level defaults to 一般."""
    elder_id = int(payload["elder_id"])
    _require_elder(cur, elder_id)
    trigger_source = payload.get("trigger_source")
    if trigger_source not in TRIGGER_SOURCES:
        raise Line4Error("触发来源只能是「设备告警/家属呼叫/主动上报」")
    event_level = payload.get("event_level", "一般")
    if event_level not in EVENT_LEVELS:
        raise Line4Error("事件等级只能是「一般/紧急/危急」")
    occur_time = payload.get("occur_time") or dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    occur_time = _parse_datetime(occur_time)

    cur.execute(
        """INSERT INTO emergency (elder_id, trigger_source, event_level, occur_time, status)
           VALUES (%s,%s,%s,%s,'待响应')""",
        (elder_id, trigger_source, event_level, occur_time),
    )
    return {"event_id": cur.lastrowid, "status": "待响应"}


def respond_emergency(cur, event_id, payload):
    """Respond to an emergency; the trigger auto-escalates the level if late."""
    event_id = int(event_id)
    responder = _clean_text(payload.get("responder"), "响应人", required=True)
    arrive_time = payload.get("arrive_time") or dt.datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )
    arrive_time = _parse_datetime(arrive_time)

    cur.execute(
        "SELECT status, event_level, escalated FROM emergency WHERE event_id=%s FOR UPDATE",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line4Error("应急事件不存在")
    if row["status"] not in ("待响应", "已响应"):
        raise Line4Error("该事件已处置闭环，不能再次响应")

    cur.execute(
        """UPDATE emergency
              SET responder=%s, arrive_time=%s
            WHERE event_id=%s""",
        (responder, arrive_time, event_id),
    )
    cur.execute(
        "SELECT event_level, escalated, status FROM emergency WHERE event_id=%s",
        (event_id,),
    )
    state = cur.fetchone()
    return {
        "event_id": event_id,
        "status": state["status"],
        "event_level": state["event_level"],
        "escalated": bool(state["escalated"]),
    }


def complete_emergency(cur, event_id, result):
    """Complete the disposal loop; the trigger flips status to 已处置."""
    event_id = int(event_id)
    result = _clean_text(result, "处置结果", required=True)

    cur.execute(
        "SELECT status, arrive_time FROM emergency WHERE event_id=%s FOR UPDATE",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        raise Line4Error("应急事件不存在")
    if row["status"] == "已处置":
        raise Line4Error("该事件已处置闭环")

    # 未到场先补记为当前时间，保证闭环字段完整（响应时限由触发器校验）
    cur.execute(
        """UPDATE emergency
              SET result=%s,
                  arrive_time = COALESCE(arrive_time, NOW())
            WHERE event_id=%s""",
        (result, event_id),
    )
    cur.execute(
        "SELECT status, event_level, escalated FROM emergency WHERE event_id=%s",
        (event_id,),
    )
    state = cur.fetchone()
    return {
        "event_id": event_id,
        "status": state["status"],
        "event_level": state["event_level"],
        "escalated": bool(state["escalated"]),
    }
