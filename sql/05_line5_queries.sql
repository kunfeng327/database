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

-- =====================================================================
-- 线3 护工与排班：5 条多表业务 SQL（含 3 表以上连接与聚合统计）
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;

-- 1. 护工月度绩效考核：有效工时、已完成订单数、质量抽查均分（4表连接）
SELECT cg.caregiver_id,
       cg.name AS caregiver_name,
       cg.agency,
       cg.cert_type,
       COUNT(DISTINCT d.dispatch_id) AS completed_orders,
       COALESCE(SUM(wh.valid_hours), 0) AS total_valid_hours,
       ROUND(AVG(qi.score), 2) AS avg_quality_score
FROM caregiver cg
LEFT JOIN dispatch d ON d.caregiver_id = cg.caregiver_id AND d.confirmed = 1
LEFT JOIN work_hour wh ON wh.dispatch_id = d.dispatch_id AND wh.review_status IN ('自动认定','复核通过')
LEFT JOIN quality_inspection qi ON qi.caregiver_id = cg.caregiver_id AND qi.inspection_status = '已抽查'
WHERE cg.on_duty = '在岗'
GROUP BY cg.caregiver_id, cg.name, cg.agency, cg.cert_type
ORDER BY total_valid_hours DESC, avg_quality_score DESC;

-- 2. 跨区接单与围栏异常排查：定位服务社区不在护工注册区域或围栏校验异常的派单（5表连接）
SELECT wh.work_hour_id,
       cg.name AS caregiver_name,
       cg.service_regions AS registered_regions,
       c.name AS actual_community,
       o.order_id,
       o.appoint_time,
       wh.fence_result,
       wh.review_status
FROM work_hour wh
JOIN caregiver cg    ON cg.caregiver_id = wh.caregiver_id
JOIN dispatch d      ON d.dispatch_id = wh.dispatch_id
JOIN service_order o ON o.order_id = d.order_id
JOIN elder e         ON e.elder_id = o.elder_id
JOIN community c     ON c.community_id = e.community_id
WHERE FIND_IN_SET(c.name, cg.service_regions) = 0
   OR wh.fence_result = '围栏外异常';

-- 3. 机构排班饱和度与证书合规分析（3表连接）
SELECT cg.agency,
       s.work_date,
       s.shift,
       COUNT(DISTINCT cg.caregiver_id) AS duty_caregivers,
       SUM(s.capacity) AS total_capacity,
       SUM(s.booked) AS total_booked,
       ROUND(SUM(s.booked) / NULLIF(SUM(s.capacity), 0) * 100, 2) AS utilization_rate_pct
FROM schedule s
JOIN caregiver cg ON cg.caregiver_id = s.caregiver_id
LEFT JOIN dispatch d ON d.caregiver_id = cg.caregiver_id AND DATE(d.dispatch_time) = s.work_date
WHERE cg.on_duty = '在岗'
  AND cg.cert_expire >= s.work_date
GROUP BY cg.agency, s.work_date, s.shift
ORDER BY s.work_date ASC, utilization_rate_pct DESC;

-- 4. 可用护工智能匹配查询：筛选指定日期/社区/项目类型下证书有效且有余量的护工（4表连接）
SELECT cg.caregiver_id,
       cg.name AS caregiver_name,
       cg.cert_type,
       cg.cert_level,
       cg.rating,
       s.work_date,
       s.shift,
       (s.capacity - s.booked) AS remaining_slots,
       COUNT(qi.inspection_id) AS pending_rectifications
FROM caregiver cg
JOIN schedule s ON s.caregiver_id = cg.caregiver_id
LEFT JOIN quality_inspection qi
       ON qi.caregiver_id = cg.caregiver_id
      AND qi.rectification_status IN ('待整改','整改中')
LEFT JOIN care_plan cp ON cp.caregiver_id = cg.caregiver_id AND cp.status = '生效'
WHERE cg.on_duty = '在岗'
  AND cg.cert_expire >= CURDATE()
  AND s.status = '开放'
  AND s.booked < s.capacity
  AND FIND_IN_SET('幸福社区', cg.service_regions) > 0
GROUP BY cg.caregiver_id, cg.name, cg.cert_type, cg.cert_level, cg.rating, s.work_date, s.shift, s.capacity, s.booked
HAVING pending_rectifications = 0
ORDER BY cg.rating DESC, remaining_slots DESC;

-- 5. 各类服务项目的实际平均耗时 vs 标准时长对比（4表连接）
SELECT si.item_id,
       si.name AS item_name,
       si.type AS service_type,
       si.std_hours,
       COUNT(wh.work_hour_id) AS sample_count,
       ROUND(AVG(wh.valid_hours), 2) AS actual_avg_hours,
       ROUND(AVG(wh.valid_hours) - si.std_hours, 2) AS hours_diff
FROM service_item si
JOIN service_order o ON o.item_id = si.item_id
JOIN dispatch d      ON d.order_id = o.order_id
JOIN work_hour wh    ON wh.dispatch_id = d.dispatch_id
WHERE wh.checkout_time IS NOT NULL
  AND wh.fence_result = '通过'
GROUP BY si.item_id, si.name, si.type, si.std_hours
ORDER BY sample_count DESC;