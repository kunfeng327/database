-- 可选：由数据库管理员启用事件调度器后执行本文件（默认每小时检查）。
-- 部署时配置 event_scheduler=ON；不在应用中修改全局数据库配置。
-- MySQL EVENT 每次独立事务；失败自动回滚，人工仍可从运维页重试。
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
