-- =====================================================================
-- 测试数据（日期均相对 CURDATE()/NOW() 生成，保证任何时候导入演示效果一致）
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;
-- 先删触发器：种子里的历史派单（改派/取消）本就不满足派单校验，导入完由 04 脚本重建
DROP TRIGGER IF EXISTS tr_dispatch_before_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_confirm;
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE quality_inspection;
TRUNCATE subsidy_claim; TRUNCATE subsidy_policy; TRUNCATE schedule;
TRUNCATE dispatch;     TRUNCATE service_order;  TRUNCATE service_item;
TRUNCATE care_plan;    TRUNCATE assessment;     TRUNCATE elder;
TRUNCATE caregiver;    TRUNCATE community;      TRUNCATE sys_user;
SET FOREIGN_KEY_CHECKS = 1;

-- 社区
INSERT INTO community (community_id, name, district, service_radius_km) VALUES
(1,'幸福社区','海淀区',2.5),
(2,'阳光社区','海淀区',3.0),
(3,'梧桐社区','朝阳区',2.0),
(4,'滨江社区','西城区',4.0);

-- 护工（8 号证书已过期、9 号离职，用于演示约束拦截）
INSERT INTO caregiver (caregiver_id, name, agency, cert_type, cert_level, cert_expire, service_regions, on_duty, rating) VALUES
(1,'王秀兰','安康护理服务有限公司','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 2 YEAR),'幸福社区,阳光社区','在岗',4.9),
(2,'李建国','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 1 YEAR),'幸福社区,滨江社区','在岗',4.7),
(3,'张桂英','乐龄养老服务社','家政服务员','中级', DATE_ADD(CURDATE(), INTERVAL 500 DAY),'阳光社区,梧桐社区','在岗',4.6),
(4,'刘晓芬','乐龄养老服务社','护士','护师', DATE_ADD(CURDATE(), INTERVAL 3 YEAR),'幸福社区,阳光社区,梧桐社区,滨江社区','在岗',5.0),
(5,'陈志强','康源康复中心','康复师','初级', DATE_ADD(CURDATE(), INTERVAL 900 DAY),'梧桐社区,滨江社区','在岗',4.8),
(6,'赵春梅','康源康复中心','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 1 YEAR),'幸福社区,梧桐社区','在岗',4.5),
(7,'孙丽华','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 100 DAY),'阳光社区,滨江社区','在岗',4.4),
(8,'周德海','乐龄养老服务社','养老护理员','四级', DATE_SUB(CURDATE(), INTERVAL 30 DAY),'幸福社区','在岗',4.2),
(9,'吴美琴','乐龄养老服务社','家政服务员','初级', DATE_ADD(CURDATE(), INTERVAL 2 YEAR),'阳光社区','离职',4.0);

-- 老人（14 位，11/12 号档案暂停服务）
INSERT INTO elder (elder_id, name, id_card, birth_date, gender, address, community_id, guardian_name, guardian_phone, special_tag, status) VALUES
(1,'陈桂香','110108194503152245','1945-03-15','女','幸福社区3号楼2单元101',1,'陈明','13800000001','独居,高龄','正常'),
(2,'王守义','110108194811040117','1948-11-04','男','幸福社区5号楼1单元302',1,'王芳','13800000002','高龄','正常'),
(3,'李淑珍','110105195109283326','1951-09-28','女','阳光社区8栋601',2,'李强','13800000003','失能','正常'),
(4,'张德福','11010519550612661X','1955-06-12','男','阳光社区2栋1204',2,'张莉','13800000004','低保','正常'),
(5,'刘玉梅','110105195802207745','1958-02-20','女','梧桐社区甲区9号院',3,'刘洋','13800000005','独居','正常'),
(6,'杨振邦','110102194709053318','1947-09-05','男','滨江社区东里11号楼',4,'杨帆','13800000006','高龄,失能','正常'),
(7,'赵凤兰','110102195404184426','1954-04-18','女','滨江社区西里4号楼',4,'赵刚','13800000007','低保,高龄','正常'),
(8,'孙桂英','110108194601072247','1946-01-07','女','幸福社区9号楼5单元501',1,'孙军','13800000008','独居,高龄','正常'),
(9,'周连生','110105195207159915','1952-07-15','男','阳光社区6栋803',2,'周雪','13800000009','','正常'),
(10,'吴桂芳','110105195612301123','1956-12-30','女','梧桐社区乙区2号院',3,'吴斌','13800000010','独居','正常'),
(11,'郑国栋','110102194906115537','1949-06-11','男','滨江社区南里6号楼',4,'郑好','13800000011','失能','暂停服务'),
(12,'冯秀云','110108195303286625','1953-03-28','女','幸福社区2号楼4单元202',1,'冯博','13800000012','高龄','暂停服务'),
(13,'高崇礼','110105194410081130','1944-10-08','男','阳光社区1栋502',2,'高远','13800000013','高龄,独居','正常'),
(14,'林淑仪','11010219570522442X','1957-05-22','女','滨江社区北里8号楼',4,'林峰','13800000014','','正常');

-- 能力评估（4、13 号评估已过期 → 触发"暂停派单"演示）
INSERT INTO assessment (assessment_id, elder_id, scale, score, ability_level, assessor, assess_date, expire_date) VALUES
(1,1,'ADL',95,'能力完好','评估员小马', DATE_SUB(CURDATE(), INTERVAL 100 DAY), DATE_ADD(CURDATE(), INTERVAL 265 DAY)),
(2,1,'简易智能状态',92,'能力完好','评估员小马', DATE_SUB(CURDATE(), INTERVAL 100 DAY), DATE_ADD(CURDATE(), INTERVAL 265 DAY)),
(3,2,'ADL',82,'轻度失能','评估员小马', DATE_SUB(CURDATE(), INTERVAL 150 DAY), DATE_ADD(CURDATE(), INTERVAL 215 DAY)),
(4,3,'ADL',45,'重度失能','评估员小周', DATE_SUB(CURDATE(), INTERVAL 265 DAY), DATE_ADD(CURDATE(), INTERVAL 100 DAY)),
(5,4,'ADL',88,'能力完好','评估员小周', DATE_SUB(CURDATE(), INTERVAL 60 DAY),  DATE_ADD(CURDATE(), INTERVAL 305 DAY)),
(6,5,'ADL',65,'中度失能','评估员小马', DATE_SUB(CURDATE(), INTERVAL 120 DAY), DATE_ADD(CURDATE(), INTERVAL 245 DAY)),
(7,6,'ADL',38,'重度失能','评估员小周', DATE_SUB(CURDATE(), INTERVAL 90 DAY),  DATE_ADD(CURDATE(), INTERVAL 275 DAY)),
(8,7,'ADL',78,'轻度失能','评估员小马', DATE_SUB(CURDATE(), INTERVAL 30 DAY),  DATE_ADD(CURDATE(), INTERVAL 335 DAY)),
(9,8,'ADL',90,'能力完好','评估员小周', DATE_SUB(CURDATE(), INTERVAL 200 DAY), DATE_ADD(CURDATE(), INTERVAL 165 DAY)),
(10,9,'ADL',85,'能力完好','评估员小马', DATE_SUB(CURDATE(), INTERVAL 45 DAY),  DATE_ADD(CURDATE(), INTERVAL 320 DAY)),
(11,10,'ADL',72,'中度失能','评估员小周', DATE_SUB(CURDATE(), INTERVAL 420 DAY), DATE_SUB(CURDATE(), INTERVAL 55 DAY)),
(12,13,'ADL',55,'中度失能','评估员小马', DATE_SUB(CURDATE(), INTERVAL 380 DAY), DATE_SUB(CURDATE(), INTERVAL 15 DAY)),
(13,14,'ADL',93,'能力完好','评估员小周', DATE_SUB(CURDATE(), INTERVAL 70 DAY),  DATE_ADD(CURDATE(), INTERVAL 295 DAY));

-- 照护计划（6 号计划已手动暂停）
INSERT INTO care_plan (plan_id, elder_id, package_name, frequency, start_date, end_date, caregiver_id, status) VALUES
(1,1,'助洁关怀包','每周1次保洁+2次探访', DATE_SUB(CURDATE(), INTERVAL 90 DAY), DATE_ADD(CURDATE(), INTERVAL 270 DAY),3,'生效'),
(2,3,'失能照护包','每日助浴+翻身护理',   DATE_SUB(CURDATE(), INTERVAL 80 DAY), DATE_ADD(CURDATE(), INTERVAL 280 DAY),4,'生效'),
(3,4,'助餐保障包','每日1餐送餐上门',     DATE_SUB(CURDATE(), INTERVAL 60 DAY), DATE_ADD(CURDATE(), INTERVAL 300 DAY),1,'生效'),
(4,5,'康复助行包','每周2次康复训练',     DATE_SUB(CURDATE(), INTERVAL 50 DAY), DATE_ADD(CURDATE(), INTERVAL 310 DAY),5,'生效'),
(5,6,'重度照护包','每日2次上门护理',     DATE_SUB(CURDATE(), INTERVAL 40 DAY), DATE_ADD(CURDATE(), INTERVAL 320 DAY),4,'生效'),
(6,7,'助餐关怀包','每日1餐送餐上门',     DATE_SUB(CURDATE(), INTERVAL 30 DAY), DATE_ADD(CURDATE(), INTERVAL 330 DAY),2,'暂停'),
(7,8,'探访关爱包','每周2次电话+1次上门', DATE_SUB(CURDATE(), INTERVAL 70 DAY), DATE_ADD(CURDATE(), INTERVAL 290 DAY),6,'生效'),
(8,2,'助浴助洁包','每周1次助浴',         DATE_SUB(CURDATE(), INTERVAL 20 DAY), DATE_ADD(CURDATE(), INTERVAL 340 DAY),1,'生效'),
(9,10,'康复助行包','每周2次康复训练',     DATE_SUB(CURDATE(), INTERVAL 10 DAY), DATE_ADD(CURDATE(), INTERVAL 350 DAY),5,'生效');

-- 服务项目
INSERT INTO service_item (item_id, name, type, unit, guide_price, std_hours, subsidizable) VALUES
(1,'上门助餐配餐','助餐','次',20.00,1.0,1),
(2,'协助沐浴','助浴','次',60.00,1.5,1),
(3,'陪同就医','陪诊','次',80.00,3.0,1),
(4,'居家保洁','家政','小时',40.00,2.0,1),
(5,'康复训练指导','康复护理','次',90.00,1.0,1),
(6,'失能老人翻身护理','康复护理','次',50.00,0.5,1),
(7,'代购代办','家政','次',25.00,1.0,0),
(8,'心理疏导陪聊','家政','小时',35.00,1.0,0);

-- 订单（22 条：7 条已完成（上月，供补贴核算）、4 条待派单、5 条已派单、2 条服务中、2 条已取消、2 条今天待服务）
INSERT INTO service_order (order_id, elder_id, item_id, appoint_time, address, channel, amount, status, created_at) VALUES
(1,3,2, DATE_SUB(NOW(), INTERVAL 28 DAY),'阳光社区8栋601','家属端',60.00,'已完成', DATE_SUB(NOW(), INTERVAL 30 DAY)),
(2,3,6, DATE_SUB(NOW(), INTERVAL 26 DAY),'阳光社区8栋601','社区代下单',50.00,'已完成', DATE_SUB(NOW(), INTERVAL 28 DAY)),
(3,4,1, DATE_SUB(NOW(), INTERVAL 25 DAY),'阳光社区2栋1204','电话',20.00,'已完成', DATE_SUB(NOW(), INTERVAL 27 DAY)),
(4,4,1, DATE_SUB(NOW(), INTERVAL 24 DAY),'阳光社区2栋1204','电话',20.00,'已完成', DATE_SUB(NOW(), INTERVAL 26 DAY)),
(5,7,1, DATE_SUB(NOW(), INTERVAL 20 DAY),'滨江社区西里4号楼','社区代下单',20.00,'已完成', DATE_SUB(NOW(), INTERVAL 22 DAY)),
(6,7,3, DATE_SUB(NOW(), INTERVAL 18 DAY),'滨江社区西里4号楼','家属端',80.00,'已完成', DATE_SUB(NOW(), INTERVAL 20 DAY)),
(7,1,4, DATE_SUB(NOW(), INTERVAL 15 DAY),'幸福社区3号楼2单元101','家属端',80.00,'已完成', DATE_SUB(NOW(), INTERVAL 17 DAY)),
(8,1,4, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 1 DAY), INTERVAL 9 HOUR),'幸福社区3号楼2单元101','家属端',80.00,'待派单', DATE_SUB(NOW(), INTERVAL 2 HOUR)),
(9,5,5, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 1 DAY), INTERVAL 14 HOUR),'梧桐社区甲区9号院','社区代下单',90.00,'待派单', DATE_SUB(NOW(), INTERVAL 90 MINUTE)),
(10,8,3, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 2 DAY), INTERVAL 8 HOUR),'幸福社区9号楼5单元501','电话',80.00,'待派单', DATE_SUB(NOW(), INTERVAL 45 MINUTE)),
(11,6,2, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 2 DAY), INTERVAL 10 HOUR),'滨江社区东里11号楼','家属端',60.00,'待派单', DATE_SUB(NOW(), INTERVAL 20 MINUTE)),
(12,2,2, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 1 DAY), INTERVAL 15 HOUR),'幸福社区5号楼1单元302','家属端',60.00,'已派单', DATE_SUB(NOW(), INTERVAL 1 DAY)),
(13,4,1, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 1 DAY), INTERVAL 11 HOUR),'阳光社区2栋1204','电话',20.00,'已派单', DATE_SUB(NOW(), INTERVAL 1 DAY)),
(14,7,1, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 1 DAY), INTERVAL 12 HOUR),'滨江社区西里4号楼','社区代下单',20.00,'已派单', DATE_SUB(NOW(), INTERVAL 22 HOUR)),
(15,5,5, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 3 DAY), INTERVAL 9 HOUR),'梧桐社区甲区9号院','社区代下单',90.00,'已派单', DATE_SUB(NOW(), INTERVAL 20 HOUR)),
(16,3,6, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 3 DAY), INTERVAL 15 HOUR),'阳光社区8栋601','家属端',50.00,'已派单', DATE_SUB(NOW(), INTERVAL 6 HOUR)),
(17,6,6, DATE_SUB(NOW(), INTERVAL 2 HOUR),'滨江社区东里11号楼','家属端',50.00,'服务中', DATE_SUB(NOW(), INTERVAL 6 HOUR)),
(18,1,7, DATE_SUB(NOW(), INTERVAL 1 HOUR),'幸福社区3号楼2单元101','电话',25.00,'服务中', DATE_SUB(NOW(), INTERVAL 4 HOUR)),
(19,9,3, DATE_SUB(NOW(), INTERVAL 4 DAY),'阳光社区6栋803','家属端',80.00,'已取消', DATE_SUB(NOW(), INTERVAL 6 DAY)),
(20,10,4, DATE_SUB(NOW(), INTERVAL 3 DAY),'梧桐社区乙区2号院','电话',40.00,'已取消', DATE_SUB(NOW(), INTERVAL 5 DAY)),
(21,14,8, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 1 DAY), INTERVAL 10 HOUR),'滨江社区北里8号楼','家属端',35.00,'待派单', DATE_SUB(NOW(), INTERVAL 10 MINUTE)),
(22,9,7, DATE_ADD(DATE_ADD(CURDATE(), INTERVAL 2 DAY), INTERVAL 9 HOUR),'阳光社区6栋803','电话',25.00,'待派单', DATE_SUB(NOW(), INTERVAL 5 MINUTE));

-- 派单记录（17/18 服务中；历史改单 9 号订单曾派给离职护工后取消）
INSERT INTO dispatch (dispatch_id, order_id, caregiver_id, dispatch_time, arrive_time, leave_time, service_note, confirmed, is_current, reassign_reason) VALUES
(1,1,4, DATE_SUB(NOW(), INTERVAL 29 DAY), DATE_SUB(NOW(), INTERVAL 28 DAY), DATE_SUB(NOW(), INTERVAL 28 DAY) + INTERVAL 90 MINUTE,'助浴完成，老人状态良好',1,1,NULL),
(2,2,4, DATE_SUB(NOW(), INTERVAL 27 DAY), DATE_SUB(NOW(), INTERVAL 26 DAY), DATE_SUB(NOW(), INTERVAL 26 DAY) + INTERVAL 40 MINUTE,'翻身护理按时完成',1,1,NULL),
(3,3,1, DATE_SUB(NOW(), INTERVAL 26 DAY), DATE_SUB(NOW(), INTERVAL 25 DAY), DATE_SUB(NOW(), INTERVAL 25 DAY) + INTERVAL 60 MINUTE,'送餐上门，家属签收',1,1,NULL),
(4,4,1, DATE_SUB(NOW(), INTERVAL 25 DAY), DATE_SUB(NOW(), INTERVAL 24 DAY), DATE_SUB(NOW(), INTERVAL 24 DAY) + INTERVAL 60 MINUTE,'送餐上门，家属签收',1,1,NULL),
(5,5,2, DATE_SUB(NOW(), INTERVAL 21 DAY), DATE_SUB(NOW(), INTERVAL 20 DAY), DATE_SUB(NOW(), INTERVAL 20 DAY) + INTERVAL 60 MINUTE,'送餐上门',1,1,NULL),
(6,6,4, DATE_SUB(NOW(), INTERVAL 19 DAY), DATE_SUB(NOW(), INTERVAL 18 DAY), DATE_SUB(NOW(), INTERVAL 18 DAY) + INTERVAL 180 MINUTE,'陪诊协和，全程顺利',1,1,NULL),
(7,7,3, DATE_SUB(NOW(), INTERVAL 16 DAY), DATE_SUB(NOW(), INTERVAL 15 DAY), DATE_SUB(NOW(), INTERVAL 15 DAY) + INTERVAL 150 MINUTE,'保洁2小时完成',1,1,NULL),
(8,12,1, DATE_SUB(NOW(), INTERVAL 1 DAY), NULL,NULL,NULL,0,1,NULL),
(9,13,1, DATE_SUB(NOW(), INTERVAL 1 DAY), NULL,NULL,NULL,0,1,NULL),
(10,14,2, DATE_SUB(NOW(), INTERVAL 22 HOUR), NULL,NULL,NULL,0,1,NULL),
(11,15,5, DATE_SUB(NOW(), INTERVAL 20 HOUR), NULL,NULL,NULL,0,1,NULL),
(12,16,4, DATE_SUB(NOW(), INTERVAL 6 HOUR), NULL,NULL,NULL,0,1,NULL),
(13,17,4, DATE_SUB(NOW(), INTERVAL 6 HOUR), DATE_SUB(NOW(), INTERVAL 2 HOUR),NULL,NULL,0,1,NULL),
(14,18,6, DATE_SUB(NOW(), INTERVAL 4 HOUR), DATE_SUB(NOW(), INTERVAL 1 HOUR),NULL,NULL,0,1,NULL),
(15,9,9, DATE_SUB(NOW(), INTERVAL 85 MINUTE), NULL,NULL,NULL,0,0,'原护工离职，改派'),
(16,19,3, DATE_SUB(NOW(), INTERVAL 5 DAY), NULL,NULL,NULL,0,0,'家属临时取消订单');

-- 排班：每位在岗护工未来 7 天，上午/下午各一班
INSERT INTO schedule (caregiver_id, work_date, shift, capacity, booked, status)
SELECT cg.caregiver_id,
       DATE_ADD(CURDATE(), INTERVAL d.n DAY),
       s.shift,
       3 + (cg.caregiver_id % 2), 0, '开放'
FROM caregiver cg
CROSS JOIN (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6) d
CROSS JOIN (SELECT '上午' shift UNION SELECT '下午') s
WHERE cg.on_duty = '在岗';

-- 补贴政策
INSERT INTO subsidy_policy (policy_id, district, target_type, item_id, standard, period, effective_from, effective_to) VALUES
(1,'海淀区','低保',1,15.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(2,'海淀区','失能',2,40.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(3,'朝阳区','高龄',3,50.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(4,'西城区','失能',6,30.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(5,'西城区','高龄',1,10.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(6,'海淀区','高龄',4,100.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR));

-- 补贴申报（20 条，覆盖 3 个历史账期；审核状态与拨付状态分离）
INSERT INTO subsidy_claim
(claim_id, elder_id, policy_id, claim_period, order_ids, amount,
 audit_status, pay_status, reviewer, audited_at, paid_at) VALUES
(1, 3,2, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'1,2',80.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 33 DAY),DATE_SUB(NOW(), INTERVAL 31 DAY)),
(2, 4,1, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'3,4',30.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 33 DAY),DATE_SUB(NOW(), INTERVAL 31 DAY)),
(3, 7,5, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'5',10.00,'街道已审','未拨付','街道小王',DATE_SUB(NOW(), INTERVAL 32 DAY),NULL),
(4, 1,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'7',100.00,'待审核','未拨付',NULL,NULL,NULL),
(5, 6,4, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'6',30.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 34 DAY),DATE_SUB(NOW(), INTERVAL 30 DAY)),
(6, 2,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'1,3',200.00,'通过','已拨付','街道小王',DATE_SUB(NOW(), INTERVAL 33 DAY),DATE_SUB(NOW(), INTERVAL 29 DAY)),
(7, 8,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'7',100.00,'街道已审','未拨付','街道小王',DATE_SUB(NOW(), INTERVAL 31 DAY),NULL),
(8,13,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 35 DAY),'%Y-%m'),'3,4',200.00,'驳回','未拨付','街道小李',DATE_SUB(NOW(), INTERVAL 30 DAY),NULL),
(9, 3,2, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'1,2',80.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 63 DAY),DATE_SUB(NOW(), INTERVAL 61 DAY)),
(10,4,1, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'3,4',30.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 63 DAY),DATE_SUB(NOW(), INTERVAL 61 DAY)),
(11,7,5, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'5',10.00,'通过','已拨付','街道小王',DATE_SUB(NOW(), INTERVAL 62 DAY),DATE_SUB(NOW(), INTERVAL 60 DAY)),
(12,1,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'7',100.00,'驳回','未拨付','街道小王',DATE_SUB(NOW(), INTERVAL 61 DAY),NULL),
(13,6,4, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'6',30.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 64 DAY),DATE_SUB(NOW(), INTERVAL 60 DAY)),
(14,2,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'1,3',200.00,'街道已审','未拨付','街道小王',DATE_SUB(NOW(), INTERVAL 62 DAY),NULL),
(15,8,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'7',100.00,'待审核','未拨付',NULL,NULL,NULL),
(16,13,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 65 DAY),'%Y-%m'),'3,4',200.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 63 DAY),DATE_SUB(NOW(), INTERVAL 59 DAY)),
(17,3,2, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 95 DAY),'%Y-%m'),'1,2',80.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 93 DAY),DATE_SUB(NOW(), INTERVAL 91 DAY)),
(18,4,1, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 95 DAY),'%Y-%m'),'3,4',30.00,'通过','已拨付','街道小王',DATE_SUB(NOW(), INTERVAL 93 DAY),DATE_SUB(NOW(), INTERVAL 90 DAY)),
(19,7,5, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 95 DAY),'%Y-%m'),'5',10.00,'驳回','未拨付','街道小王',DATE_SUB(NOW(), INTERVAL 92 DAY),NULL),
(20,1,6, DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 95 DAY),'%Y-%m'),'7',100.00,'通过','已拨付','街道小李',DATE_SUB(NOW(), INTERVAL 94 DAY),DATE_SUB(NOW(), INTERVAL 90 DAY));

-- 质量抽查（20 条：7 条订单抽查 + 13 条护工抽查；含 1 条待抽查、1 条待整改）
INSERT INTO quality_inspection
(inspection_id, order_id, caregiver_id, inspection_method, score, issue_tags,
 rectification_requirement, rectification_result, inspection_status,
 rectification_status, inspector, inspected_at, rectified_at) VALUES
(1,1,4,'电话回访',95,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 24 DAY),NULL),
(2,2,4,'上门核查',88,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 22 DAY),NULL),
(3,3,1,'电话回访',92,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 21 DAY),NULL),
(4,4,1,'上门核查',76,'送餐迟到','补齐迟到说明并连续两次回访合格','已补交说明，后续回访正常','已抽查','已完成','街道张监管',DATE_SUB(NOW(), INTERVAL 18 DAY),DATE_SUB(NOW(), INTERVAL 12 DAY)),
(5,5,2,'电话回访',85,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 16 DAY),NULL),
(6,6,4,'上门核查',70,'服务时长不足','补做陪诊记录并提交机构复核','机构已复核，补齐服务记录','已抽查','已完成','街道张监管',DATE_SUB(NOW(), INTERVAL 15 DAY),DATE_SUB(NOW(), INTERVAL 9 DAY)),
(7,7,3,'电话回访',90,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 14 DAY),NULL),
(8,NULL,1,'电话回访',82,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 13 DAY),NULL),
(9,NULL,1,'上门核查',78,'沟通态度','参加服务沟通复训并提交培训证明','已提交复训证明，等待复查','已抽查','待整改','街道张监管',DATE_SUB(NOW(), INTERVAL 8 DAY),NULL),
(10,NULL,2,'电话回访',86,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 11 DAY),NULL),
(11,NULL,2,'上门核查',60,'服务记录缺失','补齐服务记录并由机构负责人签字','记录已补齐','已抽查','已完成','街道张监管',DATE_SUB(NOW(), INTERVAL 20 DAY),DATE_SUB(NOW(), INTERVAL 10 DAY)),
(12,NULL,3,'电话回访',88,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 9 DAY),NULL),
(13,NULL,3,'电话回访',91,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 7 DAY),NULL),
(14,NULL,4,'电话回访',89,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 6 DAY),NULL),
(15,NULL,4,'上门核查',62,'护理流程不规范','按标准流程复训并提交整改照片','已完成复训并上传照片','已抽查','已完成','街道张监管',DATE_SUB(NOW(), INTERVAL 17 DAY),DATE_SUB(NOW(), INTERVAL 5 DAY)),
(16,NULL,5,'电话回访',87,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 4 DAY),NULL),
(17,NULL,5,'电话回访',95,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 3 DAY),NULL),
(18,NULL,6,'上门核查',80,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 2 DAY),NULL),
(19,NULL,7,'电话回访',84,NULL,NULL,NULL,'已抽查','无需整改','街道张监管',DATE_SUB(NOW(), INTERVAL 1 DAY),NULL),
(20,7,3,'电话回访',NULL,NULL,NULL,NULL,'待抽查',NULL,'街道张监管',NOW(),NULL);

-- 同步排班已接单量与种子派单数据一致（触发器建好后新派单会自动维护 booked）
UPDATE schedule s
SET s.booked = LEAST(s.capacity,
  (SELECT COUNT(*) FROM dispatch d
     JOIN service_order o ON o.order_id = d.order_id
    WHERE d.caregiver_id = s.caregiver_id
      AND d.is_current = 1
      AND o.status IN ('已派单','服务中')
      AND DATE(o.appoint_time) = s.work_date));

-- 系统用户（演示账号，密码全部为 123456；哈希=SHA256(盐+密码)，由 MySQL 现场计算）
INSERT INTO sys_user (username, password_hash, salt, real_name, role, elder_id, caregiver_id) VALUES
('shequ',   SHA2(CONCAT('s@lt!shequ',   '123456'),256), 's@lt!shequ',   '社区李干事', '社区管理员', NULL, NULL),
('jiashu',  SHA2(CONCAT('s@lt!jiashu',  '123456'),256), 's@lt!jiashu',  '陈明(陈桂香之子)', '家属', 1, NULL),
('jiashu2', SHA2(CONCAT('s@lt!jiashu2', '123456'),256), 's@lt!jiashu2', '李强(李淑珍之子)', '家属', 3, NULL),
('hugong',  SHA2(CONCAT('s@lt!hugong',  '123456'),256), 's@lt!hugong',  '王秀兰', '护工', NULL, 1),
('jigou',   SHA2(CONCAT('s@lt!jigou',   '123456'),256), 's@lt!jigou',   '安康护理负责人', '机构负责人', NULL, NULL),
('jianguan',SHA2(CONCAT('s@lt!jianguan','123456'),256), 's@lt!jianguan','街道张监管', '监管人员', NULL, NULL);
