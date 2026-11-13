-- =====================================================================
-- 线5 补贴核算与质量监管：5 条多表业务 SQL
-- 运行前先按 01→04 顺序初始化，保证视图和触发器已创建
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;

-- 1. 申报追溯：补贴申报 → 订单 → 服务项目 → 派单护工
SELECT cl.claim_id,
       cl.claim_period,
       cl.audit_status,
       cl.pay_status,
       e.name AS elder_name,
       o.order_id,
       si.name AS item_name,
       o.appoint_time,
       o.amount AS order_amount,
       cg.name AS caregiver_name
FROM subsidy_claim cl
JOIN elder e ON e.elder_id = cl.elder_id
JOIN service_order o ON FIND_IN_SET(o.order_id, cl.order_ids) > 0
JOIN service_item si ON si.item_id = o.item_id
LEFT JOIN dispatch d ON d.order_id = o.order_id AND d.is_current = 1
LEFT JOIN caregiver cg ON cg.caregiver_id = d.caregiver_id
ORDER BY cl.claim_id DESC, o.order_id;

-- 2. 区县补贴监管：申报数、通过率、拨付率和已拨付金额
SELECT c.district,
       COUNT(*) AS claim_count,
       ROUND(SUM(cl.audit_status = '通过') / COUNT(*) * 100, 2) AS approval_rate_pct,
       SUM(cl.pay_status = '已拨付') AS paid_count,
       ROUND(SUM(cl.pay_status = '已拨付') / COUNT(*) * 100, 2) AS payment_rate_pct,
       SUM(cl.amount) AS claimed_amount,
       SUM(CASE WHEN cl.pay_status = '已拨付' THEN cl.amount ELSE 0 END) AS paid_amount
FROM subsidy_claim cl
JOIN elder e ON e.elder_id = cl.elder_id
JOIN community c ON c.community_id = e.community_id
GROUP BY c.district
ORDER BY paid_amount DESC;

-- 3. 护工质量画像：抽查均分、未完成整改数与正式评分对照
SELECT cg.caregiver_id,
       cg.name AS caregiver_name,
       cg.agency,
       cg.rating AS official_rating,
       COUNT(qi.inspection_id) AS inspection_count,
       ROUND(AVG(qi.score), 2) AS inspection_avg_score,
       SUM(qi.rectification_status IN ('待整改','整改中')) AS open_rectifications,
       GROUP_CONCAT(DISTINCT qi.issue_tags ORDER BY qi.issue_tags SEPARATOR '; ') AS issue_history
FROM caregiver cg
LEFT JOIN quality_inspection qi
       ON qi.caregiver_id = cg.caregiver_id
      AND qi.inspection_status = '已抽查'
GROUP BY cg.caregiver_id, cg.name, cg.agency, cg.rating
HAVING open_rectifications > 0 OR inspection_avg_score < 80
ORDER BY open_rectifications DESC, inspection_avg_score;

-- 4. 待审核队列：按街道分组的审核时限与关联订单数
SELECT c.district,
       cl.claim_id,
       e.name AS elder_name,
       si.name AS item_name,
       cl.claim_period,
       cl.amount,
       cl.audit_status,
       DATEDIFF(CURDATE(), DATE(cl.created_at)) AS waiting_days,
       LENGTH(cl.order_ids) - LENGTH(REPLACE(cl.order_ids, ',', '')) + 1 AS traced_order_count
FROM subsidy_claim cl
JOIN elder e ON e.elder_id = cl.elder_id
JOIN community c ON c.community_id = e.community_id
JOIN subsidy_policy sp ON sp.policy_id = cl.policy_id
JOIN service_item si ON si.item_id = sp.item_id
WHERE cl.audit_status IN ('待审核','街道已审')
ORDER BY waiting_days DESC, c.district, cl.amount DESC;

-- 5. 补贴政策执行分析：政策覆盖、申报次数与已完成服务量
SELECT sp.policy_id,
       sp.district,
       sp.target_type,
       si.name AS item_name,
       sp.standard,
       COUNT(DISTINCT cl.claim_id) AS claim_count,
       COUNT(DISTINCT o.order_id) AS completed_order_count,
       SUM(CASE WHEN cl.pay_status = '已拨付' THEN cl.amount ELSE 0 END) AS paid_amount
FROM subsidy_policy sp
JOIN service_item si ON si.item_id = sp.item_id
LEFT JOIN subsidy_claim cl ON cl.policy_id = sp.policy_id
LEFT JOIN service_order o
       ON o.item_id = sp.item_id
      AND o.status = '已完成'
      AND DATE_FORMAT(o.appoint_time, '%Y-%m') = cl.claim_period
GROUP BY sp.policy_id, sp.district, sp.target_type, si.name, sp.standard
ORDER BY claim_count DESC, paid_amount DESC;
