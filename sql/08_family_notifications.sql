-- 已有数据库的增量升级，可重复执行，不清空档案或消息。
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
