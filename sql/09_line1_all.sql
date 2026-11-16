-- =====================================================================
-- 业务线1（pengkunfeng）SQL 合集
-- 合并自 05_line1_upgrade / 06_line1_scheduler / 07_line1_queries /
-- 08_family_notifications 四个文件，避免多人协作合入后难以辨认本人文件。
--
-- ⚠ 各节用途和执行条件不同，不要把整个文件从头到尾一次执行！
--   §A 旧库一次性增量升级 —— 仅旧版演示库执行一次，先备份；全新安装勿用
--   §B 评估过期自动暂停事件 —— DBA 设 event_scheduler=ON 后单独执行本节
--   §C 5 条多表业务查询 —— 演示/答辩用，需先导入 01~04
--   §D 家属站内信表 —— 可重复执行；应用启动检查也会自动补齐该表
-- 每节自带 USE/SET NAMES，需要哪节就复制哪节单独执行。
-- =====================================================================


-- =====================================================================
-- §A 旧库一次性增量升级（原 05_line1_upgrade.sql）
-- 仅旧版演示库执行一次；请先备份。全新安装无需执行本节。
-- MySQL DDL 不提供整文件事务回滚，失败后核对已执行 DDL 再处理。
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;
ALTER TABLE assessment ADD INDEX idx_assess_latest (elder_id,assess_date,assessment_id);
ALTER TABLE care_plan
  ADD COLUMN pause_reason VARCHAR(20) NULL COMMENT '暂停原因',
  ADD CONSTRAINT chk_pause_reason CHECK (pause_reason IS NULL OR
      (status='暂停' AND pause_reason IN ('评估过期','手动暂停','档案暂停'))),
  DROP INDEX idx_plan_elder,
  ADD INDEX idx_plan_elder (elder_id,status,start_date,end_date);
UPDATE care_plan SET pause_reason='手动暂停' WHERE status='暂停';
-- 计划项目明细：一个计划多个项目，避免逗号拼接，满足第三范式
CREATE TABLE care_plan_item (
  plan_id INT NOT NULL,
  item_id INT NOT NULL,
  PRIMARY KEY (plan_id, item_id),
  CONSTRAINT fk_plan_item_plan FOREIGN KEY (plan_id) REFERENCES care_plan(plan_id),
  CONSTRAINT fk_plan_item_service FOREIGN KEY (item_id) REFERENCES service_item(item_id)
);

-- 旧计划的真实项目清单须由管理员逐份核实补录，不能凭空推断。
-- 完成后依次重新执行 sql/03_views.sql 和 sql/04_procs_triggers.sql。


-- =====================================================================
-- §B 评估过期自动暂停事件（原 06_line1_scheduler.sql）
-- 可选：由数据库管理员启用事件调度器后执行本节（默认每小时检查）。
-- 部署时配置 event_scheduler=ON；不在应用中修改全局数据库配置。
-- MySQL EVENT 每次独立事务；失败自动回滚，人工仍可从运维页重试。
-- 检查：SHOW EVENTS; SHOW VARIABLES LIKE 'event_scheduler';
-- 事件 DEFINER 账号需有例程执行和更新权限；重建例程时先暂停事件。
-- =====================================================================
USE elder_care;
DELIMITER $$
CREATE EVENT IF NOT EXISTS ev_pause_expired_plans
ON SCHEDULE EVERY 1 HOUR
DO
BEGIN
  DECLARE paused INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  START TRANSACTION;
  CALL sp_pause_expired_plans_worker(paused);
  COMMIT;
END$$
DELIMITER ;


-- =====================================================================
-- §C 业务线1提供的5条多表查询（原 07_line1_queries.sql，MySQL 8.0.16+/9.x）
-- 运行前导入01~04；执行计划：在对应SELECT前加 EXPLAIN ANALYZE（8.0.18+）。
-- 本脚本不宣称已经测得性能提升；请在实际MySQL记录执行计划/耗时。
-- =====================================================================
USE elder_care;
SET @community_id=2;

-- Q1 某社区重度失能、评估有效、当前计划生效的老人及责任护工（5个关系）。
SELECT e.elder_id,e.name,c.name AS community,a.ability_level,p.package_name,cg.name AS caregiver
FROM elder e JOIN community c ON c.community_id=e.community_id
JOIN v_latest_assessment a ON a.elder_id=e.elder_id
JOIN care_plan p ON p.elder_id=e.elder_id
LEFT JOIN caregiver cg ON cg.caregiver_id=p.caregiver_id
WHERE e.community_id=@community_id AND e.status='正常' AND a.ability_level='重度失能'
  AND CURDATE() BETWEEN a.assess_date AND a.expire_date
  AND p.status='生效' AND CURDATE() BETWEEN p.start_date AND p.end_date;

-- Q2 未来30天需要复评的老人、监护人（电话脱敏）与当前计划（4个关系）。
SELECT e.elder_id,e.name,c.name AS community,a.expire_date,
       CONCAT(LEFT(e.guardian_phone,3),'****',RIGHT(e.guardian_phone,4)) AS phone_masked,
       p.plan_id,p.package_name
FROM elder e JOIN community c ON c.community_id=e.community_id
JOIN v_latest_assessment a ON a.elder_id=e.elder_id
LEFT JOIN care_plan p ON p.elder_id=e.elder_id AND p.status='生效'
    AND CURDATE() BETWEEN p.start_date AND p.end_date
WHERE e.status='正常' AND a.expire_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(),INTERVAL 30 DAY)
ORDER BY a.expire_date,e.elder_id;

-- Q3 缺少有效评估但仍生效的计划，供运维核对（4个关系）。
SELECT p.plan_id,e.name,c.name AS community,p.package_name,a.expire_date
FROM care_plan p JOIN elder e ON e.elder_id=p.elder_id
JOIN community c ON c.community_id=e.community_id
LEFT JOIN v_latest_assessment a ON a.elder_id=e.elder_id
WHERE p.status='生效' AND (a.assessment_id IS NULL OR a.expire_date<CURDATE() OR a.assess_date>CURDATE());

-- Q4 当前计划中各社区各项目覆盖人数；按老人去重（5个关系）。
SELECT c.community_id,c.name AS community,si.item_id,si.name AS service_item,
       COUNT(DISTINCT e.elder_id) AS covered_elders
FROM community c JOIN elder e ON e.community_id=c.community_id AND e.status='正常'
JOIN care_plan p ON p.elder_id=e.elder_id AND p.status='生效'
JOIN care_plan_item pi ON pi.plan_id=p.plan_id JOIN service_item si ON si.item_id=pi.item_id
WHERE CURDATE() BETWEEN p.start_date AND p.end_date
GROUP BY c.community_id,c.name,si.item_id,si.name;

-- Q5 各社区正常档案的能力分布与过期人数，不连接计划，避免历史记录倍增（3个关系）。
SELECT c.community_id,c.name AS community,COALESCE(a.ability_level,'未评估') AS ability_level,
       COUNT(e.elder_id) AS elder_count,
       SUM(CASE WHEN a.expire_date<CURDATE() THEN 1 ELSE 0 END) AS expired_count
FROM community c LEFT JOIN elder e ON e.community_id=c.community_id AND e.status='正常'
LEFT JOIN v_latest_assessment a ON a.elder_id=e.elder_id
GROUP BY c.community_id,c.name,a.ability_level
ORDER BY c.community_id,ability_level;


-- =====================================================================
-- §D 家属站内信表（原 08_family_notifications.sql）
-- 已有数据库的增量升级，可重复执行，不清空档案或消息。
-- 应用启动检查（prepare_database）在本表缺失时会自动执行本节建表，
-- 手动升级时也可直接执行。
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS family_notification (
  notification_id INT PRIMARY KEY AUTO_INCREMENT,
  recipient_id INT NOT NULL COMMENT '收信家属账号',
  elder_id INT NOT NULL COMMENT '提醒对应老人',
  sender_id INT NOT NULL COMMENT '发送提醒的社区管理员',
  reminder_key VARCHAR(64) NOT NULL COMMENT '评估编号及提醒类型，用于当日去重',
  sent_date DATE NOT NULL,
  title VARCHAR(100) NOT NULL,
  content VARCHAR(500) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at DATETIME NULL,
  CONSTRAINT fk_notification_recipient FOREIGN KEY (recipient_id) REFERENCES sys_user(user_id),
  CONSTRAINT fk_notification_elder FOREIGN KEY (elder_id) REFERENCES elder(elder_id),
  CONSTRAINT fk_notification_sender FOREIGN KEY (sender_id) REFERENCES sys_user(user_id),
  CONSTRAINT uk_notification_daily UNIQUE (recipient_id,elder_id,reminder_key,sent_date),
  INDEX idx_notification_inbox (recipient_id,elder_id,created_at,notification_id),
  INDEX idx_notification_unread (recipient_id,elder_id,read_at)
) ENGINE=InnoDB;
