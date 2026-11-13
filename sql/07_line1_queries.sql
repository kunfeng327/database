-- 业务线1提供的5条多表查询（MySQL 8.0.16+/9.x）。
-- 运行前导入01~04；执行计划：在对应SELECT前加 EXPLAIN ANALYZE（MySQL 8.0.18+）。
-- 本脚本不宣称已经测得性能提升；请在实际MySQL记录执行计划/耗时。
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
