-- =====================================================================
-- 存储过程与触发器（演示：评估到期暂停计划 / 派单容量与资质校验 / 完成回写）
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;
DROP PROCEDURE IF EXISTS sp_pause_expired_plans;
DROP TRIGGER IF EXISTS tr_dispatch_before_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_confirm;

-- ---------------------------------------------------------------------
-- 存储过程：评估到期自动暂停照护计划（任务书示例场景）
-- 规则：老人最新一次评估已过期 → 其"生效"状态的照护计划全部置为"暂停"
-- ---------------------------------------------------------------------
DELIMITER $$
CREATE PROCEDURE sp_pause_expired_plans()
BEGIN
  UPDATE care_plan p
  JOIN (SELECT elder_id, MAX(expire_date) AS latest_expire
          FROM assessment GROUP BY elder_id) a
    ON a.elder_id = p.elder_id
   SET p.status = '暂停'
   WHERE p.status = '生效'
     AND a.latest_expire < CURDATE();
  SELECT ROW_COUNT() AS paused_plans;
END$$
DELIMITER ;

-- ---------------------------------------------------------------------
-- 触发器1 派单前校验（BEFORE INSERT ON dispatch）：
--   ① 排班存在且有余量（已接单量 < 可接单量）
--   ② 护工在岗且证书在有效期内
--   ③ 订单处于可派单状态
-- 不满足则 SIGNAL 拒绝写入 —— 数据库层兜底，应用层漏检也拦得住
-- ---------------------------------------------------------------------
DELIMITER $$
CREATE TRIGGER tr_dispatch_before_insert
BEFORE INSERT ON dispatch
FOR EACH ROW
BEGIN
  DECLARE v_booked INT; DECLARE v_capacity INT;
  DECLARE v_on_duty VARCHAR(10); DECLARE v_cert_expire DATE;
  DECLARE v_order_status VARCHAR(10);
  DECLARE v_open_rectifications INT;

  SELECT status INTO v_order_status FROM service_order WHERE order_id = NEW.order_id;
  IF v_order_status NOT IN ('待派单','已派单') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '派单失败：订单当前状态不允许派单';
  END IF;

  SELECT on_duty, cert_expire INTO v_on_duty, v_cert_expire
    FROM caregiver WHERE caregiver_id = NEW.caregiver_id;
  IF v_on_duty <> '在岗' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '派单失败：该护工已离职';
  END IF;
  IF v_cert_expire < DATE(NOW()) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '派单失败：护工证书已过期';
  END IF;

  SELECT COUNT(*) INTO v_open_rectifications
    FROM quality_inspection
   WHERE caregiver_id = NEW.caregiver_id
     AND rectification_status IN ('待整改','整改中');
  IF v_open_rectifications > 0 THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = '派单失败：该护工存在未完成整改，暂限制接单';
  END IF;

  SELECT s.booked, s.capacity INTO v_booked, v_capacity
    FROM schedule s
    JOIN service_order o ON o.order_id = NEW.order_id
   WHERE s.caregiver_id = NEW.caregiver_id
     AND s.work_date = DATE(o.appoint_time)
     AND s.shift = (CASE WHEN TIME(o.appoint_time) < '12:00:00' THEN '上午' ELSE '下午' END);
  IF v_booked IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '派单失败：该护工在订单预约日期当天没有开放排班';
  END IF;
  IF v_booked >= v_capacity THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '派单失败：该护工当班已接满（已接单量=可接单量）';
  END IF;
END$$

-- ---------------------------------------------------------------------
-- 触发器2 派单成功后：排班表已接单量 +1（booked 自动维护）
-- ---------------------------------------------------------------------
DELIMITER $$
CREATE TRIGGER tr_dispatch_after_insert
AFTER INSERT ON dispatch
FOR EACH ROW
BEGIN
  UPDATE schedule s
    JOIN service_order o ON o.order_id = NEW.order_id
   SET s.booked = s.booked + 1
   WHERE s.caregiver_id = NEW.caregiver_id
     AND s.work_date = DATE(o.appoint_time)
     AND s.shift = (CASE WHEN TIME(o.appoint_time) < '12:00:00' THEN '上午' ELSE '下午' END);
END$$

-- ---------------------------------------------------------------------
-- 触发器3 家属确认后：订单状态自动回写为"已完成"（订单-派单链路闭环）
-- ---------------------------------------------------------------------
DELIMITER $$
CREATE TRIGGER tr_dispatch_after_confirm
AFTER UPDATE ON dispatch
FOR EACH ROW
BEGIN
  IF NEW.confirmed = 1 AND OLD.confirmed = 0 THEN
    UPDATE service_order
       SET status = '已完成'
     WHERE order_id = NEW.order_id
       AND status IN ('已派单','服务中');
  END IF;
END$$

DELIMITER ;
