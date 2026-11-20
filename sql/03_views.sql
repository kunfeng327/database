-- =====================================================================
-- 实用视图（对应任务书"每条业务线至少 3 个视图"的演示子集）
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;

-- 视图1 档案业务线：评估有效期与照护计划视图（含"评估是否已过期"标志）
CREATE OR REPLACE VIEW v_elder_assessment_plan AS
SELECT e.elder_id,
       e.name,
       TIMESTAMPDIFF(YEAR, e.birth_date, CURDATE()) AS age,
       c.name AS community,
       CONCAT(LEFT(e.id_card,6),'********',RIGHT(e.id_card,4)) AS id_masked,  -- 身份证脱敏
       e.special_tag,
       e.status AS elder_status,
       a.ability_level,
       a.expire_date AS assess_expire,
       (a.expire_date < CURDATE()) AS assess_expired,
       p.plan_id,
       p.package_name,
       p.status  AS plan_status
FROM elder e
JOIN community c ON c.community_id = e.community_id
LEFT JOIN assessment a ON a.elder_id = e.elder_id
     AND a.assessment_id = (SELECT MAX(a2.assessment_id) FROM assessment a2 WHERE a2.elder_id = e.elder_id)
LEFT JOIN care_plan p ON p.elder_id = e.elder_id AND p.status = '生效';

-- 视图2 派单业务线：待派单订单视图（含等待时长与超时标志，30 分钟未接单视为超时）
CREATE OR REPLACE VIEW v_pending_dispatch_orders AS
SELECT o.order_id,
       e.name  AS elder_name,
       c.name  AS community,
       si.name AS item_name,
       o.appoint_time,
       o.channel,
       TIMESTAMPDIFF(MINUTE, o.created_at, NOW()) AS waited_min,
       CASE WHEN TIMESTAMPDIFF(MINUTE, o.created_at, NOW()) > 30 THEN '超时'
            WHEN TIMESTAMPDIFF(MINUTE, o.created_at, NOW()) > 15 THEN '临近超时'
            ELSE '正常' END AS timeout_flag
FROM service_order o
JOIN elder e        ON e.elder_id = o.elder_id
JOIN community c    ON c.community_id = e.community_id
JOIN service_item si ON si.item_id = o.item_id
WHERE o.status = '待派单';

-- 视图2A 派单业务线：改派历史追溯
-- 每一条记录对应一次派单尝试；is_current=0 表示后来被改派，保留原因便于审计。
CREATE OR REPLACE VIEW v_dispatch_reassign_history AS
SELECT d.dispatch_id,
       d.order_id,
       o.status AS order_status,
       e.elder_id,
       e.name AS elder_name,
       si.name AS item_name,
       cg.caregiver_id,
       cg.name AS caregiver_name,
       d.dispatch_time,
       d.arrive_time,
       d.leave_time,
       d.confirmed,
       d.is_current,
       d.reassign_reason
FROM dispatch d
JOIN service_order o ON o.order_id=d.order_id
JOIN elder e ON e.elder_id=o.elder_id
JOIN service_item si ON si.item_id=o.item_id
JOIN caregiver cg ON cg.caregiver_id=d.caregiver_id
WHERE d.is_current=0 OR d.reassign_reason IS NOT NULL;

-- 视图2B 派单业务线：各渠道订单构成
-- 统计订单总量、已完成量和金额，比较电话、家属端、社区代下单三种渠道。
CREATE OR REPLACE VIEW v_order_channel_summary AS
SELECT o.channel,
       COUNT(*) AS order_count,
       SUM(o.status='已完成') AS completed_count,
       SUM(o.status='已取消') AS cancelled_count,
       ROUND(SUM(o.amount),2) AS total_amount,
       ROUND(AVG(o.amount),2) AS average_amount
FROM service_order o
GROUP BY o.channel;

-- 视图3 补贴业务线：申报与拨付进度视图
CREATE OR REPLACE VIEW v_claim_progress AS
SELECT cl.claim_id,
       cl.elder_id,
       e.name  AS elder_name,
       c.district,
       sp.target_type,
       si.name AS item_name,
       cl.claim_period,
       cl.amount,
       cl.audit_status,
       cl.pay_status,
       CASE cl.audit_status WHEN '待审核' THEN 1 WHEN '街道已审' THEN 2
                            WHEN '通过' THEN 3 WHEN '驳回' THEN 0 END AS progress_step,
       cl.reviewer,
       cl.audited_at,
       cl.paid_at,
       cl.order_ids
FROM subsidy_claim cl
JOIN elder e          ON e.elder_id = cl.elder_id
JOIN community c      ON c.community_id = e.community_id
JOIN subsidy_policy sp ON sp.policy_id = cl.policy_id
JOIN service_item si  ON si.item_id = sp.item_id;

-- 视图4 排班业务线：护工未来 7 天接单余量视图
CREATE OR REPLACE VIEW v_schedule_capacity AS
SELECT s.schedule_id,
       cg.caregiver_id,
       cg.name AS caregiver_name,
       cg.cert_type,
       cg.cert_expire,
       (cg.cert_expire >= CURDATE()) AS cert_valid,
       s.work_date,
       s.shift,
       s.capacity,
       s.booked,
       (s.capacity - s.booked) AS remaining
FROM schedule s
JOIN caregiver cg ON cg.caregiver_id = s.caregiver_id
WHERE s.work_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)
  AND s.status = '开放'
  AND cg.on_duty = '在岗';

-- 视图5 补贴业务线：申报追溯明细（申报 → 订单 → 派单护工）
CREATE OR REPLACE VIEW v_claim_trace_detail AS
SELECT cl.claim_id,
       cl.claim_period,
       cl.audit_status,
       cl.pay_status,
       o.order_id,
       o.appoint_time,
       si.name AS item_name,
       o.amount AS order_amount,
       o.status AS order_status,
       d.caregiver_id,
       cg.name AS caregiver_name,
       wh.work_hour_id,
       wh.checkin_time,
       wh.checkout_time,
       wh.valid_hours,
       wh.review_status,
       (wh.work_hour_id IS NOT NULL
        AND wh.review_status IN ('自动认定','复核通过')
        AND wh.valid_hours > 0) AS work_hour_valid
FROM subsidy_claim cl
JOIN service_order o ON FIND_IN_SET(o.order_id, cl.order_ids) > 0
JOIN service_item si ON si.item_id = o.item_id
LEFT JOIN dispatch d ON d.order_id = o.order_id AND d.is_current = 1
LEFT JOIN caregiver cg ON cg.caregiver_id = d.caregiver_id
LEFT JOIN work_hour wh ON wh.dispatch_id = d.dispatch_id;

-- 视图6 质量监管业务线：抽查、订单、护工与整改闭环
CREATE OR REPLACE VIEW v_quality_inspection_summary AS
SELECT qi.inspection_id,
       qi.order_id,
       e.name AS elder_name,
       c.name AS community,
       qi.caregiver_id,
       cg.name AS caregiver_name,
       cg.agency,
       qi.inspection_method,
       qi.score,
       qi.issue_tags,
       qi.rectification_requirement,
       qi.rectification_result,
       qi.inspection_status,
       qi.rectification_status,
       qi.inspector,
       qi.inspected_at,
       qi.rectified_at,
       CASE WHEN qi.rectification_status IN ('待整改','整改中')
            THEN DATEDIFF(CURDATE(), DATE(qi.inspected_at)) ELSE 0 END AS open_days
FROM quality_inspection qi
LEFT JOIN service_order o ON o.order_id = qi.order_id
LEFT JOIN elder e ON e.elder_id = o.elder_id
LEFT JOIN community c ON c.community_id = e.community_id
LEFT JOIN caregiver cg ON cg.caregiver_id = qi.caregiver_id;

-- 视图7 质量监管业务线：区县补贴审核与拨付统计
CREATE OR REPLACE VIEW v_district_subsidy_stats AS
SELECT c.district,
       COUNT(*) AS claim_count,
       SUM(cl.amount) AS claimed_amount,
       SUM(cl.audit_status = '通过') AS approved_count,
       SUM(cl.audit_status = '驳回') AS rejected_count,
       SUM(cl.pay_status = '已拨付') AS paid_count,
       SUM(CASE WHEN cl.pay_status = '已拨付' THEN cl.amount ELSE 0 END) AS paid_amount
FROM subsidy_claim cl
JOIN elder e ON e.elder_id = cl.elder_id
JOIN community c ON c.community_id = e.community_id
GROUP BY c.district;

-- 视图8 质量监管业务线：护工抽查评分与未完成整改联动
CREATE OR REPLACE VIEW v_caregiver_quality_score AS
SELECT cg.caregiver_id,
       cg.name AS caregiver_name,
       cg.agency,
       cg.rating AS official_rating,
       COUNT(qi.score) AS inspected_count,
       ROUND(AVG(qi.score), 2) AS inspection_avg_score,
       SUM(qi.rectification_status IN ('待整改','整改中')) AS open_rectifications
FROM caregiver cg
LEFT JOIN quality_inspection qi
       ON qi.caregiver_id = cg.caregiver_id
      AND qi.inspection_status = '已抽查'
GROUP BY cg.caregiver_id, cg.name, cg.agency, cg.rating;

-- 视图9 护工与排班业务线：证书到期预警视图（已过期 + 30天内即将到期）
CREATE OR REPLACE VIEW v_caregiver_cert_warning AS
SELECT cg.caregiver_id,
       cg.name AS caregiver_name,
       cg.agency,
       cg.cert_type,
       cg.cert_level,
       cg.cert_expire,
       DATEDIFF(cg.cert_expire, CURDATE()) AS days_remaining,
       CASE WHEN cg.cert_expire < CURDATE() THEN '已过期(禁止派单)'
            WHEN DATEDIFF(cg.cert_expire, CURDATE()) <= 30 THEN '30天内临期预警'
            ELSE '正常' END AS cert_status,
       cg.on_duty
FROM caregiver cg
WHERE cg.on_duty = '在岗'
  AND DATEDIFF(cg.cert_expire, CURDATE()) <= 30
ORDER BY days_remaining ASC;

-- 视图10 护工与排班业务线：跨区接单与异常工时核查视图
CREATE OR REPLACE VIEW v_work_hour_audit AS
SELECT wh.work_hour_id,
       cg.caregiver_id,
       cg.name AS caregiver_name,
       cg.service_regions AS allowed_regions,
       c.name AS order_community,
       FIND_IN_SET(c.name, cg.service_regions) > 0 AS is_in_region,
       d.dispatch_id,
       o.order_id,
       wh.checkin_time,
       wh.checkout_time,
       wh.checkin_location,
       wh.fence_result,
       wh.valid_hours,
       wh.review_status
FROM work_hour wh
JOIN caregiver cg    ON cg.caregiver_id = wh.caregiver_id
JOIN dispatch d      ON d.dispatch_id = wh.dispatch_id
JOIN service_order o ON o.order_id = d.order_id
JOIN elder e         ON e.elder_id = o.elder_id
JOIN community c     ON c.community_id = e.community_id;

-- 视图11 健康监测业务线：当日异常体征（待确认 + 已确认异常）
CREATE OR REPLACE VIEW v_daily_abnormal_vitals AS
SELECT vs.vital_id,
       vs.elder_id,
       e.name AS elder_name,
       c.name AS community,
       vs.device_id,
       d.device_type,
       vs.metric_type,
       vs.metric_value,
       vs.abnormal_flag,
       vs.data_source,
       vs.collect_time
FROM vital_sign vs
JOIN device d    ON d.device_id = vs.device_id
JOIN elder e     ON e.elder_id  = vs.elder_id
JOIN community c ON c.community_id = e.community_id
WHERE vs.abnormal_flag IN ('待确认','异常')
  AND DATE(vs.collect_time) = CURDATE();

-- 视图12 健康监测业务线：待响应应急事件（含等待时长、响应时限与超时/升级标志）
CREATE OR REPLACE VIEW v_pending_emergencies AS
SELECT em.event_id,
       em.elder_id,
       e.name AS elder_name,
       c.name AS community,
       em.trigger_source,
       em.event_level,
       em.occur_time,
       TIMESTAMPDIFF(MINUTE, em.occur_time, NOW()) AS waited_min,
       CASE em.event_level WHEN '一般' THEN 60 WHEN '紧急' THEN 30 ELSE 15 END AS deadline_min,
       CASE WHEN TIMESTAMPDIFF(MINUTE, em.occur_time, NOW())
                 > (CASE em.event_level WHEN '一般' THEN 60 WHEN '紧急' THEN 30 ELSE 15 END)
            THEN '超时' ELSE '正常' END AS timeout_flag,
       em.escalated
FROM emergency em
JOIN elder e     ON e.elder_id = em.elder_id
JOIN community c ON c.community_id = e.community_id
WHERE em.status = '待响应';

-- 视图13 健康监测业务线：设备绑定状态（含已绑定天数）
CREATE OR REPLACE VIEW v_device_binding_status AS
SELECT d.device_id,
       d.device_type,
       d.install_location,
       d.status,
       d.bind_time,
       d.unbind_time,
       d.elder_id,
       e.name AS elder_name,
       c.name AS community,
       DATEDIFF(COALESCE(d.unbind_time, NOW()), d.bind_time) AS bound_days
FROM device d
JOIN elder e     ON e.elder_id = d.elder_id
JOIN community c ON c.community_id = e.community_id;
