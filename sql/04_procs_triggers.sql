-- =====================================================================
-- 存储过程与触发器（演示：评估到期暂停计划 / 派单容量与资质校验 / 完成回写）
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;
DROP PROCEDURE IF EXISTS sp_pause_expired_plans;
DROP TRIGGER IF EXISTS tr_dispatch_before_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_confirm;
DROP TRIGGER IF EXISTS tr_work_hour_before_update;
DROP TRIGGER IF EXISTS tr_vital_sign_before_insert;
DROP TRIGGER IF EXISTS tr_emergency_before_update;
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

-- ---------------------------------------------------------------------
-- 触发器4 体征数据入库自动标记（BEFORE INSERT ON vital_sign）：
--   按指标类型分别校验阈值，超阈值自动标记为「待确认」，供人工复核确认
--   阈值口径：收缩压 90-140 / 舒张压 60-90 / 心率 60-100 /
--            血氧 95-100 / 体温 36.0-37.3 / 血糖 3.9-6.1
-- ---------------------------------------------------------------------
DELIMITER $$
CREATE TRIGGER tr_vital_sign_before_insert
BEFORE INSERT ON vital_sign
FOR EACH ROW
BEGIN
  SET NEW.abnormal_flag = CASE NEW.metric_type
    WHEN '收缩压' THEN IF(NEW.metric_value BETWEEN 90 AND 140, '正常', '待确认')
    WHEN '舒张压' THEN IF(NEW.metric_value BETWEEN 60 AND 90,  '正常', '待确认')
    WHEN '心率'   THEN IF(NEW.metric_value BETWEEN 60 AND 100, '正常', '待确认')
    WHEN '血氧'   THEN IF(NEW.metric_value BETWEEN 95 AND 100, '正常', '待确认')
    WHEN '体温'   THEN IF(NEW.metric_value BETWEEN 36.0 AND 37.3, '正常', '待确认')
    WHEN '血糖'   THEN IF(NEW.metric_value BETWEEN 3.9 AND 6.1, '正常', '待确认')
    ELSE '正常'
  END;
END$$

-- ---------------------------------------------------------------------
-- 触发器5 应急事件自动升级（BEFORE UPDATE ON emergency）：
--   待响应事件被更新（回填响应人/到场时间）时，若已超过该等级响应时限，
--   自动把等级升级一档（一般→紧急→危急）并打上 escalated 标记；危急不再升级
-- ---------------------------------------------------------------------
DELIMITER $$
CREATE TRIGGER tr_emergency_before_update
BEFORE UPDATE ON emergency
FOR EACH ROW
BEGIN
  DECLARE v_deadline INT;
  DECLARE v_elapsed  INT;
  DECLARE v_next     VARCHAR(10);

  SET v_deadline = CASE OLD.event_level WHEN '一般' THEN 60 WHEN '紧急' THEN 30 ELSE 15 END;
  SET v_elapsed  = TIMESTAMPDIFF(MINUTE, OLD.occur_time, COALESCE(NEW.arrive_time, NOW()));

  -- 超时未响应 → 自动升级上报
  IF OLD.status = '待响应' AND v_elapsed > v_deadline AND OLD.event_level <> '危急' THEN
    SET v_next = CASE OLD.event_level WHEN '一般' THEN '紧急' ELSE '危急' END;
    SET NEW.event_level = v_next;
    SET NEW.escalated   = 1;
  END IF;

  -- 回填响应人 → 状态推进为已响应
  IF OLD.status = '待响应' AND NEW.responder IS NOT NULL AND NEW.responder <> '' THEN
    SET NEW.status = '已响应';
  END IF;

  -- 回填处置结果且已到场 → 处置闭环
  IF NEW.result IS NOT NULL AND NEW.result <> '' AND NEW.arrive_time IS NOT NULL THEN
    SET NEW.status = '已处置';
  END IF;
END$$
DELIMITER ;

-- ---------------------------------------------------------------------
-- 触发器4 工时签退结算（BEFORE UPDATE ON work_hour）：
--   护工签退时（checkout_time 由 NULL 变为非空）：
--   ① 若围栏校验为'通过'，自动按分钟差折算 valid_hours（保留2位小数），状态置为'自动认定'
--   ② 若围栏校验为'围栏外异常'，有效工时暂记 0.00，状态自动转为'待人工复核'
-- ---------------------------------------------------------------------
DELIMITER $$
CREATE TRIGGER tr_work_hour_before_update
BEFORE UPDATE ON work_hour
FOR EACH ROW
BEGIN
  IF NEW.checkout_time IS NOT NULL AND OLD.checkout_time IS NULL THEN
    IF NEW.checkout_time < NEW.checkin_time THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '签退失败：签退时间不能早于签到时间';
    END IF;
    IF NEW.fence_result = '通过' THEN
      SET NEW.valid_hours = ROUND(TIMESTAMPDIFF(MINUTE, NEW.checkin_time, NEW.checkout_time) / 60.0, 2);
      SET NEW.review_status = '自动认定';
    ELSE
      SET NEW.valid_hours = 0.00;
      SET NEW.review_status = '待人工复核';
    END IF;
  END IF;
END$$
DELIMITER ;

DELIMITER $$

-- 1. 排班跨班次重叠拦截触发器（拦截同一天"上午+全天"或"下午+全天"冲突）
DROP TRIGGER IF EXISTS tr_schedule_before_insert$$
CREATE TRIGGER tr_schedule_before_insert
BEFORE INSERT ON schedule
FOR EACH ROW
BEGIN
    DECLARE v_conflict INT DEFAULT 0;
    SELECT COUNT(*) INTO v_conflict
      FROM schedule
     WHERE caregiver_id = NEW.caregiver_id
       AND work_date = NEW.work_date
       AND (
            NEW.shift = '全天'
            OR shift = '全天'
            OR shift = NEW.shift
       );
    IF v_conflict > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '排班冲突：该护工当日已存在重叠班次（全天与上午/下午互斥）';
    END IF;
END$$

-- 2. 派单前校验护工是否具备对应服务项目承接资质 (caregiver_item)
DROP TRIGGER IF EXISTS tr_dispatch_check_item$$
CREATE TRIGGER tr_dispatch_check_item
BEFORE INSERT ON dispatch
FOR EACH ROW
BEGIN
    DECLARE v_item_id INT;
    DECLARE v_capable INT DEFAULT 0;

    SELECT item_id INTO v_item_id
      FROM service_order
     WHERE order_id = NEW.order_id;

    SELECT COUNT(*) INTO v_capable
      FROM caregiver_item
     WHERE caregiver_id = NEW.caregiver_id
       AND item_id = v_item_id
       AND cert_verified = 1;

    IF v_capable = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '派单失败：该护工未获得此服务项目的承接资质授权';
    END IF;
END$$

-- 3. 工时签退认定通过后，自动将有效工时累加到护工档案 total_hours
DROP TRIGGER IF EXISTS tr_work_hour_after_update$$
CREATE TRIGGER tr_work_hour_after_update
AFTER UPDATE ON work_hour
FOR EACH ROW
BEGIN
    IF OLD.valid_hours = 0 AND NEW.valid_hours > 0
       AND NEW.review_status IN ('自动认定', '复核通过') THEN
        UPDATE caregiver
           SET total_hours = total_hours + NEW.valid_hours
         WHERE caregiver_id = NEW.caregiver_id;
    END IF;
END$$

-- 4. 机构端按日期范围批量排班存储过程（自动跳过已存在冲突排班的日期，返回成功排班天数）
DROP PROCEDURE IF EXISTS sp_batch_create_schedule$$
CREATE PROCEDURE sp_batch_create_schedule(
    IN  p_caregiver_id INT,
    IN  p_start_date   DATE,
    IN  p_end_date     DATE,
    IN  p_shift        VARCHAR(10),
    IN  p_capacity     INT,
    OUT p_created_cnt  INT
)
BEGIN
    DECLARE v_curr DATE DEFAULT p_start_date;
    DECLARE v_exists INT DEFAULT 0;
    SET p_created_cnt = 0;

    WHILE v_curr <= p_end_date DO
        SELECT COUNT(*) INTO v_exists
          FROM schedule
         WHERE caregiver_id = p_caregiver_id
           AND work_date = v_curr
           AND (p_shift = '全天' OR shift = '全天' OR shift = p_shift);

        IF v_exists = 0 THEN
            INSERT INTO schedule (caregiver_id, work_date, shift, capacity, booked, status)
            VALUES (p_caregiver_id, v_curr, p_shift, p_capacity, 0, '开放');
            SET p_created_cnt = p_created_cnt + 1;
        END IF;

        SET v_curr = DATE_ADD(v_curr, INTERVAL 1 DAY);
    END WHILE;
END$$

DELIMITER ;

-- ---------------------------------------------------------------------
-- 触发器：抽查评分回写护工评分（对应任务书 2.1.5「抽查结果与护工评分挂钩」）
--   规则：抽查录入评分（0-100）时，按 1:20 折算到护工评分（0-5），保留 1 位小数
-- ---------------------------------------------------------------------
DELIMITER $$
DROP TRIGGER IF EXISTS tr_inspection_after_insert$$
CREATE TRIGGER tr_inspection_after_insert
AFTER INSERT ON quality_inspection
FOR EACH ROW
BEGIN
  IF NEW.inspection_status = '已抽查' AND NEW.caregiver_id IS NOT NULL AND NEW.score IS NOT NULL THEN
    UPDATE caregiver cg
       SET cg.rating = ROUND(NEW.score / 20, 1)
     WHERE cg.caregiver_id = NEW.caregiver_id;
  END IF;
END$$

DROP TRIGGER IF EXISTS tr_inspection_after_update$$
CREATE TRIGGER tr_inspection_after_update
AFTER UPDATE ON quality_inspection
FOR EACH ROW
BEGIN
  IF NEW.inspection_status = '已抽查' AND NEW.caregiver_id IS NOT NULL AND NEW.score IS NOT NULL THEN
    UPDATE caregiver cg
       SET cg.rating = ROUND(NEW.score / 20, 1)
     WHERE cg.caregiver_id = NEW.caregiver_id;
  END IF;
END$$
DELIMITER ;