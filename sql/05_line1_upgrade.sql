-- 仅旧版演示库执行一次；请先备份。全新安装无需执行本文件。
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
