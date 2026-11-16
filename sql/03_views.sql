-- =====================================================================
-- 实用视图（对应任务书"每条业务线至少 3 个视图"的演示子集）
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;

-- 统一最新评估口径：评估日期优先，同日取编号最大的记录。
CREATE OR REPLACE VIEW v_latest_assessment AS
SELECT a.* FROM assessment a
WHERE a.assessment_id = (SELECT a2.assessment_id FROM assessment a2
    WHERE a2.elder_id=a.elder_id ORDER BY a2.assess_date DESC,a2.assessment_id DESC LIMIT 1);

-- 档案一行一个老人，只显示今天处于有效期内的生效计划。
CREATE OR REPLACE VIEW v_elder_assessment_plan AS
SELECT e.elder_id,e.name,TIMESTAMPDIFF(YEAR,e.birth_date,CURDATE()) AS age,
       c.community_id,c.name AS community,
       REPEAT('*',18) AS id_masked,
       e.special_tag,e.status AS elder_status,a.ability_level,a.expire_date AS assess_expire,
       (a.expire_date<CURDATE()) AS assess_expired,
       p.plan_id,p.package_name,p.status AS plan_status
FROM elder e JOIN community c ON c.community_id=e.community_id
LEFT JOIN v_latest_assessment a ON a.elder_id=e.elder_id
LEFT JOIN care_plan p ON p.plan_id=(SELECT p2.plan_id FROM care_plan p2
    WHERE p2.elder_id=e.elder_id AND p2.status='生效'
      AND CURDATE() BETWEEN p2.start_date AND p2.end_date
    ORDER BY p2.plan_id DESC LIMIT 1);

-- 独居且从未评估的正常档案；过期档案另见复评提醒。
CREATE OR REPLACE VIEW v_living_alone_unassessed AS
SELECT e.elder_id,e.name,c.community_id,c.name AS community,e.created_at
FROM elder e JOIN community c ON c.community_id=e.community_id
WHERE e.status='正常' AND FIND_IN_SET('独居',e.special_tag)>0
  AND NOT EXISTS (SELECT 1 FROM assessment a WHERE a.elder_id=e.elder_id);

-- 社区能力分布：每位正常老人计数一次，不受历史评估/计划数量影响。
CREATE OR REPLACE VIEW v_community_ability_distribution AS
SELECT c.community_id,c.name AS community,
       COALESCE(a.ability_level,'未评估') AS ability_level,
       COUNT(e.elder_id) AS elder_count,
       SUM(CASE WHEN a.expire_date<CURDATE() THEN 1 ELSE 0 END) AS expired_count
FROM community c LEFT JOIN elder e ON e.community_id=c.community_id AND e.status='正常'
LEFT JOIN v_latest_assessment a ON a.elder_id=e.elder_id
GROUP BY c.community_id,c.name,a.ability_level;

CREATE OR REPLACE VIEW v_elder_reassessment_due AS
SELECT e.elder_id,e.name,c.community_id,c.name AS community,a.ability_level,a.expire_date,
       DATEDIFF(a.expire_date,CURDATE()) AS days_left,
       CASE WHEN a.assessment_id IS NULL THEN '未评估'
            WHEN a.expire_date<CURDATE() THEN '已过期' ELSE '30天内到期' END AS reminder
FROM elder e JOIN community c ON c.community_id=e.community_id
LEFT JOIN v_latest_assessment a ON a.elder_id=e.elder_id
WHERE e.status='正常' AND (a.assessment_id IS NULL OR a.expire_date<=DATE_ADD(CURDATE(),INTERVAL 30 DAY));

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
       cg.name AS caregiver_name
FROM subsidy_claim cl
JOIN service_order o ON FIND_IN_SET(o.order_id, cl.order_ids) > 0
JOIN service_item si ON si.item_id = o.item_id
LEFT JOIN dispatch d ON d.order_id = o.order_id AND d.is_current = 1
LEFT JOIN caregiver cg ON cg.caregiver_id = d.caregiver_id;

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
