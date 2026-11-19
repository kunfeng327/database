-- =====================================================================
-- 测试数据（日期均相对 CURDATE()/NOW() 生成，保证任何时候导入演示效果一致）
-- =====================================================================
USE elder_care;
SET NAMES utf8mb4;
-- 先删触发器：种子里的历史派单（改派/取消）本就不满足派单校验，导入完由 04 脚本重建；
-- 线4 的体征/应急触发器同样在种子阶段删除，以便直接写入带指定异常标记/等级的测试数据
DROP TRIGGER IF EXISTS tr_dispatch_before_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_insert;
DROP TRIGGER IF EXISTS tr_dispatch_after_confirm;
DROP TRIGGER IF EXISTS tr_vital_sign_before_insert;
DROP TRIGGER IF EXISTS tr_emergency_before_update;
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE emergency;     TRUNCATE vital_sign;     TRUNCATE device;
TRUNCATE quality_inspection; TRUNCATE work_hour;
TRUNCATE subsidy_claim; TRUNCATE subsidy_policy; TRUNCATE schedule;
TRUNCATE dispatch;     TRUNCATE service_order;  TRUNCATE service_item;
TRUNCATE care_plan;    TRUNCATE assessment;     TRUNCATE elder;
TRUNCATE caregiver;    TRUNCATE community;      TRUNCATE sys_user;
TRUNCATE caregiver_item; TRUNCATE work_hour;
SET FOREIGN_KEY_CHECKS = 1;

-- 社区（20 条）
INSERT INTO community (community_id, name, district, service_radius_km) VALUES
(1,'幸福社区','海淀区',2.5),
(2,'阳光社区','海淀区',3.0),
(3,'梧桐社区','朝阳区',2.0),
(4,'滨江社区','西城区',4.0),
(5,'花园路社区','海淀区',2.5),
(6,'安贞社区','朝阳区',3.0),
(7,'月坛社区','西城区',3.5),
(8,'东直门社区','东城区',2.0),
(9,'和平里社区','东城区',3.0),
(10,'建国门社区','东城区',2.5),
(11,'丰台桥南社区','丰台区',3.5),
(12,'方庄社区','丰台区',3.0),
(13,'石景山古城社区','石景山区',3.0),
(14,'鲁谷社区','石景山区',2.5),
(15,'万寿路社区','海淀区',2.5),
(16,'八里庄社区','朝阳区',2.5),
(17,'甘家口社区','海淀区',3.0),
(18,'天坛社区','东城区',2.0),
(19,'永外社区','东城区',3.0),
(20,'金顶街社区','石景山区',3.0);

-- 护工（20 条；8 号证书已过期、9 号离职，用于演示约束拦截）
INSERT INTO caregiver (caregiver_id, name, agency, cert_type, cert_level, cert_expire, service_regions, on_duty, rating) VALUES
(1,'王秀兰','安康护理服务有限公司','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 2 YEAR),'幸福社区,阳光社区','在岗',4.9),
(2,'李建国','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 1 YEAR),'幸福社区,滨江社区','在岗',4.7),
(3,'张桂英','乐龄养老服务社','家政服务员','中级', DATE_ADD(CURDATE(), INTERVAL 500 DAY),'阳光社区,梧桐社区','在岗',4.6),
(4,'刘晓芬','乐龄养老服务社','护士','护师', DATE_ADD(CURDATE(), INTERVAL 3 YEAR),'幸福社区,阳光社区,梧桐社区,滨江社区','在岗',5.0),
(5,'陈志强','康源康复中心','康复师','初级', DATE_ADD(CURDATE(), INTERVAL 900 DAY),'梧桐社区,滨江社区','在岗',4.8),
(6,'赵春梅','康源康复中心','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 1 YEAR),'幸福社区,梧桐社区','在岗',4.5),
(7,'孙丽华','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 100 DAY),'阳光社区,滨江社区','在岗',4.4),
(8,'周德海','乐龄养老服务社','养老护理员','四级', DATE_SUB(CURDATE(), INTERVAL 30 DAY),'幸福社区','在岗',4.2),
(9,'吴美琴','乐龄养老服务社','家政服务员','初级', DATE_ADD(CURDATE(), INTERVAL 2 YEAR),'阳光社区','离职',4.0),
(10,'马桂香','安康护理服务有限公司','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 2 YEAR),'花园路社区,万寿路社区','在岗',4.7),
(11,'周志明','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 400 DAY),'甘家口社区,月坛社区','在岗',4.3),
(12,'郑丽娟','乐龄养老服务社','家政服务员','中级', DATE_ADD(CURDATE(), INTERVAL 3 YEAR),'安贞社区,八里庄社区','在岗',4.5),
(13,'冯国庆','乐龄养老服务社','护士','护士', DATE_ADD(CURDATE(), INTERVAL 2 YEAR),'东直门社区,和平里社区','在岗',4.8),
(14,'蒋秀珍','康源康复中心','康复师','中级', DATE_ADD(CURDATE(), INTERVAL 700 DAY),'建国门社区,天坛社区','在岗',4.9),
(15,'韩丽','康源康复中心','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 1 YEAR),'丰台桥南社区,方庄社区','在岗',4.4),
(16,'董文','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 300 DAY),'石景山古城社区,鲁谷社区','在岗',4.2),
(17,'苏芳','乐龄养老服务社','家政服务员','初级', DATE_ADD(CURDATE(), INTERVAL 600 DAY),'永外社区,金顶街社区','在岗',4.1),
(18,'沈国梁','康源康复中心','康复师','初级', DATE_ADD(CURDATE(), INTERVAL 800 DAY),'花园路社区,八里庄社区','在岗',4.6),
(19,'姚桂芝','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 150 DAY),'方庄社区,月坛社区','在岗',4.0),
(20,'曹秀兰','乐龄养老服务社','家政服务员','中级', DATE_ADD(CURDATE(), INTERVAL 2 YEAR),'和平里社区,天坛社区','在岗',4.5);

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
(14,'林淑仪','11010219570522442X','1957-05-22','女','滨江社区北里8号楼',4,'林峰','13800000014','','正常'),
(15,'徐桂兰','110108194903052245','1949-03-05','女','花园路社区6号楼3单元201',5,'徐强','13800000015','独居,高龄','正常'),
(16,'钱守诚','110108195004162233','1950-04-16','男','万寿路社区12号楼1单元403',15,'钱芳','13800000016','高龄','正常'),
(17,'孙玉珍','110101195112082467','1951-12-08','女','和平里社区3号楼601',9,'孙磊','13800000017','失能,高龄','正常'),
(18,'李桂英','110106195308193345','1953-08-19','女','方庄社区5号楼2单元1102',12,'李娜','13800000018','低保','正常'),
(19,'周凤兰','110107195411262348','1954-11-26','女','石景山古城社区2号楼404',13,'周杰','13800000019','独居','正常'),
(20,'吴国华','110108195611302254','1956-11-30','男','甘家口社区7号楼2单元803',17,'吴静','13800000020','高龄','正常');

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
(13,14,'ADL',93,'能力完好','评估员小周', DATE_SUB(CURDATE(), INTERVAL 70 DAY),  DATE_ADD(CURDATE(), INTERVAL 295 DAY)),
(14,15,'ADL',88,'能力完好','评估员小马', DATE_SUB(CURDATE(), INTERVAL 60 DAY), DATE_ADD(CURDATE(), INTERVAL 305 DAY)),
(15,16,'ADL',78,'轻度失能','评估员小周', DATE_SUB(CURDATE(), INTERVAL 50 DAY), DATE_ADD(CURDATE(), INTERVAL 315 DAY)),
(16,17,'ADL',40,'重度失能','评估员小马', DATE_SUB(CURDATE(), INTERVAL 40 DAY), DATE_ADD(CURDATE(), INTERVAL 325 DAY)),
(17,18,'ADL',82,'轻度失能','评估员小周', DATE_SUB(CURDATE(), INTERVAL 30 DAY), DATE_ADD(CURDATE(), INTERVAL 335 DAY)),
(18,19,'ADL',90,'能力完好','评估员小马', DATE_SUB(CURDATE(), INTERVAL 25 DAY), DATE_ADD(CURDATE(), INTERVAL 340 DAY)),
(19,20,'ADL',75,'轻度失能','评估员小周', DATE_SUB(CURDATE(), INTERVAL 20 DAY), DATE_ADD(CURDATE(), INTERVAL 345 DAY)),
(20,5,'简易智能状态',70,'中度失能','评估员小马', DATE_SUB(CURDATE(), INTERVAL 45 DAY), DATE_ADD(CURDATE(), INTERVAL 320 DAY));

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
(9,10,'康复助行包','每周2次康复训练',     DATE_SUB(CURDATE(), INTERVAL 10 DAY), DATE_ADD(CURDATE(), INTERVAL 350 DAY),5,'生效'),
(10,9,'探访关爱包','每周2次电话+1次上门', DATE_SUB(CURDATE(), INTERVAL 40 DAY), DATE_ADD(CURDATE(), INTERVAL 320 DAY),6,'生效'),
(11,13,'助餐关怀包','每日1餐送餐上门',     DATE_SUB(CURDATE(), INTERVAL 30 DAY), DATE_ADD(CURDATE(), INTERVAL 330 DAY),NULL,'暂停'),
(12,14,'助洁关怀包','每周1次保洁+2次探访', DATE_SUB(CURDATE(), INTERVAL 25 DAY), DATE_ADD(CURDATE(), INTERVAL 340 DAY),3,'生效'),
(13,15,'助餐保障包','每日1餐送餐上门',     DATE_SUB(CURDATE(), INTERVAL 30 DAY), DATE_ADD(CURDATE(), INTERVAL 330 DAY),10,'生效'),
(14,16,'康复助行包','每周2次康复训练',     DATE_SUB(CURDATE(), INTERVAL 20 DAY), DATE_ADD(CURDATE(), INTERVAL 340 DAY),14,'生效'),
(15,17,'重度照护包','每日2次上门护理',     DATE_SUB(CURDATE(), INTERVAL 25 DAY), DATE_ADD(CURDATE(), INTERVAL 335 DAY),13,'生效'),
(16,18,'助餐关怀包','每日1餐送餐上门',     DATE_SUB(CURDATE(), INTERVAL 15 DAY), DATE_ADD(CURDATE(), INTERVAL 345 DAY),15,'生效'),
(17,19,'探访关爱包','每周2次电话+1次上门', DATE_SUB(CURDATE(), INTERVAL 10 DAY), DATE_ADD(CURDATE(), INTERVAL 350 DAY),16,'生效'),
(18,20,'助浴助洁包','每周1次助浴',         DATE_SUB(CURDATE(), INTERVAL 30 DAY), DATE_ADD(CURDATE(), INTERVAL 330 DAY),11,'生效'),
(19,2,'助洁关怀包','每周1次保洁',         DATE_SUB(CURDATE(), INTERVAL 400 DAY), DATE_SUB(CURDATE(), INTERVAL 100 DAY),1,'结束'),
(20,3,'失能照护包','每日助浴',             DATE_SUB(CURDATE(), INTERVAL 380 DAY), DATE_SUB(CURDATE(), INTERVAL 80 DAY),4,'结束');

-- 服务项目
INSERT INTO service_item (item_id, name, type, unit, guide_price, std_hours, subsidizable) VALUES
(1,'上门助餐配餐','助餐','次',20.00,1.0,1),
(2,'协助沐浴','助浴','次',60.00,1.5,1),
(3,'陪同就医','陪诊','次',80.00,3.0,1),
(4,'居家保洁','家政','小时',40.00,2.0,1),
(5,'康复训练指导','康复护理','次',90.00,1.0,1),
(6,'失能老人翻身护理','康复护理','次',50.00,0.5,1),
(7,'代购代办','家政','次',25.00,1.0,0),
(8,'心理疏导陪聊','家政','小时',35.00,1.0,0),
(9,'夜间陪护服务','康复护理','小时',70.00,8.0,1),
(10,'上门理发','家政','次',30.00,0.5,1),
(11,'营养助餐套餐','助餐','次',25.00,1.0,1),
(12,'失禁护理','康复护理','次',55.00,1.0,1),
(13,'陪诊代取药','陪诊','次',40.00,1.5,1),
(14,'擦浴护理','助浴','次',50.00,1.0,1),
(15,'康复理疗','康复护理','次',120.00,1.5,1),
(16,'情感陪伴','家政','小时',35.00,1.0,0),
(17,'换季整理收纳','家政','次',45.00,2.0,0),
(18,'用药提醒','康复护理','次',15.00,0.5,0),
(19,'助行训练','康复护理','次',60.00,1.0,1),
(20,'节日聚餐配送','助餐','次',35.00,1.0,0);

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
(16,19,3, DATE_SUB(NOW(), INTERVAL 5 DAY), NULL,NULL,NULL,0,0,'家属临时取消订单'),
(17,2,4, DATE_SUB(NOW(), INTERVAL 27 DAY), NULL,NULL,NULL,0,0,'护工临时调整，改派'),
(18,5,2, DATE_SUB(NOW(), INTERVAL 21 DAY), NULL,NULL,NULL,0,0,'机构内部调配'),
(19,15,5, DATE_SUB(NOW(), INTERVAL 20 HOUR), NULL,NULL,NULL,0,0,'护工请假，改派'),
(20,14,2, DATE_SUB(NOW(), INTERVAL 22 HOUR), NULL,NULL,NULL,0,0,'班次冲突，改派');

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
(6,'海淀区','高龄',4,100.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(7,'朝阳区','低保',1,15.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(8,'东城区','失能',2,40.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(9,'西城区','独居',4,80.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(10,'海淀区','独居',5,60.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(11,'丰台区','低保',1,12.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(12,'石景山区','高龄',3,45.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(13,'东城区','高龄',4,90.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(14,'朝阳区','失能',6,30.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(15,'海淀区','失能',2,38.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(16,'西城区','低保',1,14.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(17,'丰台区','失能',6,28.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(18,'石景山区','失能',2,36.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(19,'东城区','低保',1,13.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR)),
(20,'朝阳区','高龄',3,48.00,'月', DATE_SUB(CURDATE(), INTERVAL 1 YEAR), DATE_ADD(CURDATE(), INTERVAL 1 YEAR));

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
('jianguan',SHA2(CONCAT('s@lt!jianguan','123456'),256), 's@lt!jianguan','街道张监管', '监管人员', NULL, NULL),
('jiashu03',SHA2(CONCAT('s@lt!js03','123456'),256),'s@lt!js03','王芳(王守义之女)','家属',2,NULL),
('jiashu04',SHA2(CONCAT('s@lt!js04','123456'),256),'s@lt!js04','张莉(张德福之女)','家属',4,NULL),
('jiashu05',SHA2(CONCAT('s@lt!js05','123456'),256),'s@lt!js05','刘洋(刘玉梅之子)','家属',5,NULL),
('jiashu06',SHA2(CONCAT('s@lt!js06','123456'),256),'s@lt!js06','杨帆(杨振邦之子)','家属',6,NULL),
('jiashu07',SHA2(CONCAT('s@lt!js07','123456'),256),'s@lt!js07','赵刚(赵凤兰之子)','家属',7,NULL),
('jiashu08',SHA2(CONCAT('s@lt!js08','123456'),256),'s@lt!js08','孙军(孙桂英之子)','家属',8,NULL),
('jiashu09',SHA2(CONCAT('s@lt!js09','123456'),256),'s@lt!js09','周雪(周连生之女)','家属',9,NULL),
('jiashu10',SHA2(CONCAT('s@lt!js10','123456'),256),'s@lt!js10','吴斌(吴桂芳之子)','家属',10,NULL),
('hugong2',SHA2(CONCAT('s@lt!hg2','123456'),256),'s@lt!hg2','李建国','护工',NULL,2),
('hugong3',SHA2(CONCAT('s@lt!hg3','123456'),256),'s@lt!hg3','张桂英','护工',NULL,3),
('hugong4',SHA2(CONCAT('s@lt!hg4','123456'),256),'s@lt!hg4','刘晓芬','护工',NULL,4),
('hugong5',SHA2(CONCAT('s@lt!hg5','123456'),256),'s@lt!hg5','陈志强','护工',NULL,5),
('hugong6',SHA2(CONCAT('s@lt!hg6','123456'),256),'s@lt!hg6','赵春梅','护工',NULL,6),
('jianguan2',SHA2(CONCAT('s@lt!jg2','123456'),256),'s@lt!jg2','区级王监管','监管人员',NULL,NULL);

-- =====================================================================
-- 线4 健康监测与应急响应 测试数据（设备 20 / 体征 25 / 应急事件 22）
-- =====================================================================

-- 监测设备（20 条：18 条绑定 + 2 条解绑，解绑后保留原归属与时间）
INSERT INTO device (device_id, elder_id, device_type, install_location, bind_time, unbind_time, status) VALUES
(1, 1,'血压计','卧室床头',  DATE_SUB(NOW(), INTERVAL 100 DAY), NULL, '绑定'),
(2, 1,'一键呼叫','床边随身',  DATE_SUB(NOW(), INTERVAL 100 DAY), NULL, '绑定'),
(3, 3,'心电贴','胸前贴片',  DATE_SUB(NOW(), INTERVAL 80 DAY),  NULL, '绑定'),
(4, 5,'跌倒雷达','客厅顶部',  DATE_SUB(NOW(), INTERVAL 70 DAY),  NULL, '绑定'),
(5, 2,'血压计','卧室床头',  DATE_SUB(NOW(), INTERVAL 90 DAY),  NULL, '绑定'),
(6, 4,'一键呼叫','床头',      DATE_SUB(NOW(), INTERVAL 60 DAY),  NULL, '绑定'),
(7, 6,'心电贴','胸前贴片',  DATE_SUB(NOW(), INTERVAL 50 DAY),  NULL, '绑定'),
(8, 8,'跌倒雷达','卫生间顶部', DATE_SUB(NOW(), INTERVAL 65 DAY),  NULL, '绑定'),
(9, 7,'血压计','客厅',      DATE_SUB(NOW(), INTERVAL 55 DAY),  NULL, '绑定'),
(10,10,'跌倒雷达','卧室顶部',  DATE_SUB(NOW(), INTERVAL 45 DAY),  NULL, '绑定'),
(11,13,'一键呼叫','随身',      DATE_SUB(NOW(), INTERVAL 40 DAY),  NULL, '绑定'),
(12,17,'心电贴','胸前贴片',  DATE_SUB(NOW(), INTERVAL 35 DAY),  NULL, '绑定'),
(13,15,'血压计','卧室',      DATE_SUB(NOW(), INTERVAL 30 DAY),  NULL, '绑定'),
(14,16,'一键呼叫','床头',      DATE_SUB(NOW(), INTERVAL 28 DAY),  NULL, '绑定'),
(15,18,'血压计','卧室',      DATE_SUB(NOW(), INTERVAL 25 DAY),  NULL, '绑定'),
(16,19,'跌倒雷达','客厅',      DATE_SUB(NOW(), INTERVAL 20 DAY),  NULL, '绑定'),
(17,14,'血压计','卧室',      DATE_SUB(NOW(), INTERVAL 120 DAY), DATE_SUB(NOW(), INTERVAL 20 DAY), '解绑'),
(18,12,'一键呼叫','床头',      DATE_SUB(NOW(), INTERVAL 130 DAY), DATE_SUB(NOW(), INTERVAL 30 DAY), '解绑'),
(19,20,'心电贴','胸前贴片',  DATE_SUB(NOW(), INTERVAL 15 DAY),  NULL, '绑定'),
(20, 9,'跌倒雷达','客厅顶部',  DATE_SUB(NOW(), INTERVAL 12 DAY),  NULL, '绑定');

-- 体征数据（25 条；异常标记为种子直接指定，运行期由 tr_vital_sign_before_insert 自动判定）
INSERT INTO vital_sign (vital_id, device_id, elder_id, collect_time, metric_type, metric_value, abnormal_flag, data_source) VALUES
(1, 1,1,  DATE_SUB(NOW(), INTERVAL 2 HOUR), '收缩压', 128, '正常',  '自动采集'),
(2, 1,1,  DATE_SUB(NOW(), INTERVAL 2 HOUR), '舒张压', 82,  '正常',  '自动采集'),
(3, 1,1,  DATE_SUB(NOW(), INTERVAL 1 HOUR), '收缩压', 168, '异常',  '自动采集'),
(4, 1,1,  DATE_SUB(NOW(), INTERVAL 1 HOUR), '舒张压', 96,  '待确认','自动采集'),
(5, 3,3,  DATE_SUB(NOW(), INTERVAL 3 HOUR), '心率',   96,  '正常',  '自动采集'),
(6, 3,3,  DATE_SUB(NOW(), INTERVAL 3 HOUR), '血氧',   92,  '待确认','自动采集'),
(7, 4,5,  DATE_SUB(NOW(), INTERVAL 30 MINUTE),'心率', 55,  '待确认','自动采集'),
(8, 2,1,  DATE_SUB(NOW(), INTERVAL 10 MINUTE),'体温', 38.5,'待确认','自动采集'),
(9, 5,2,  DATE_SUB(NOW(), INTERVAL 4 HOUR), '收缩压', 135, '正常',  '自动采集'),
(10,6,4,  DATE_SUB(NOW(), INTERVAL 5 HOUR), '血氧',   97,  '正常',  '自动采集'),
(11,7,6,  DATE_SUB(NOW(), INTERVAL 6 HOUR), '心率',   110, '待确认','自动采集'),
(12,8,8,  DATE_SUB(NOW(), INTERVAL 2 HOUR), '血氧',   94,  '待确认','自动采集'),
(13,9,7,  DATE_SUB(NOW(), INTERVAL 7 HOUR), '血糖',   5.2, '正常',  '人工录入'),
(14,10,10,DATE_SUB(NOW(), INTERVAL 8 HOUR), '血糖',   8.5, '待确认','自动采集'),
(15,11,13,DATE_SUB(NOW(), INTERVAL 1 HOUR), '心率',   88,  '正常',  '自动采集'),
(16,12,17,DATE_SUB(NOW(), INTERVAL 30 MINUTE),'收缩压',155,'待确认','自动采集'),
(17,13,15,DATE_SUB(NOW(), INTERVAL 2 HOUR), '体温',   36.8,'正常',  '自动采集'),
(18,14,16,DATE_SUB(NOW(), INTERVAL 3 HOUR), '收缩压', 120, '正常',  '自动采集'),
(19,15,18,DATE_SUB(NOW(), INTERVAL 4 HOUR), '舒张压', 88,  '正常',  '自动采集'),
(20,16,19,DATE_SUB(NOW(), INTERVAL 5 HOUR), '血氧',   98,  '正常',  '自动采集'),
(21,3,3,  DATE_SUB(NOW(), INTERVAL 1 DAY),  '心率',   78,  '正常',  '自动采集'),
(22,1,1,  DATE_SUB(NOW(), INTERVAL 1 DAY),  '收缩压', 142, '异常',  '自动采集'),
(23,17,14,DATE_SUB(NOW(), INTERVAL 2 DAY),  '收缩压', 130, '正常',  '自动采集'),
(24,18,12,DATE_SUB(NOW(), INTERVAL 3 DAY),  '血氧',   96,  '正常',  '自动采集'),
(25,2,1,  DATE_SUB(NOW(), INTERVAL 1 DAY),  '体温',   39.1,'异常',  '自动采集');

-- 应急事件（22 条；待响应/已响应/已处置闭环，等级对应响应时限 60/30/15 分钟）
INSERT INTO emergency (event_id, elder_id, trigger_source, event_level, occur_time, responder, arrive_time, result, status, escalated) VALUES
(1, 3,'设备告警','紧急', DATE_SUB(NOW(), INTERVAL 10 MINUTE), NULL, NULL, NULL, '待响应', 0),
(2, 1,'家属呼叫','一般', DATE_SUB(NOW(), INTERVAL 70 MINUTE), NULL, NULL, NULL, '待响应', 0),
(3, 5,'设备告警','危急', DATE_SUB(NOW(), INTERVAL 5 MINUTE),  NULL, NULL, NULL, '待响应', 0),
(4, 6,'主动上报','一般', DATE_SUB(NOW(), INTERVAL 40 MINUTE), NULL, NULL, NULL, '待响应', 0),
(5, 8,'设备告警','一般', DATE_SUB(NOW(), INTERVAL 90 MINUTE), NULL, NULL, NULL, '待响应', 0),
(6,17,'设备告警','紧急', DATE_SUB(NOW(), INTERVAL 45 MINUTE), NULL, NULL, NULL, '待响应', 0),
(7,13,'家属呼叫','一般', DATE_SUB(NOW(), INTERVAL 20 MINUTE), NULL, NULL, NULL, '待响应', 0),
(8,19,'设备告警','危急', DATE_SUB(NOW(), INTERVAL 8 MINUTE),  NULL, NULL, NULL, '待响应', 0),
(9,20,'主动上报','一般', DATE_SUB(NOW(), INTERVAL 15 MINUTE), NULL, NULL, NULL, '待响应', 0),
(10,4,'主动上报','紧急', DATE_SUB(NOW(), INTERVAL 2 DAY), '社区李干事', DATE_SUB(NOW(), INTERVAL 2 DAY) + INTERVAL 15 MINUTE, NULL, '已响应', 0),
(11,2,'设备告警','一般', DATE_SUB(NOW(), INTERVAL 3 DAY), '社区李干事', DATE_SUB(NOW(), INTERVAL 3 DAY) + INTERVAL 20 MINUTE, '血压偏高，已通知家属服药', '已处置', 0),
(12,7,'家属呼叫','一般', DATE_SUB(NOW(), INTERVAL 4 DAY), '护工王秀兰', DATE_SUB(NOW(), INTERVAL 4 DAY) + INTERVAL 25 MINUTE, '代取药并上门探望', '已处置', 0),
(13,10,'设备告警','紧急', DATE_SUB(NOW(), INTERVAL 1 DAY), '护工刘晓芬', DATE_SUB(NOW(), INTERVAL 1 DAY) + INTERVAL 12 MINUTE, NULL, '已响应', 0),
(14,15,'主动上报','一般', DATE_SUB(NOW(), INTERVAL 1 DAY), '社区李干事', DATE_SUB(NOW(), INTERVAL 1 DAY) + INTERVAL 30 MINUTE, '轻微不适，观察无碍', '已处置', 0),
(15,1,'设备告警','危急', DATE_SUB(NOW(), INTERVAL 6 DAY), '护工刘晓芬', DATE_SUB(NOW(), INTERVAL 6 DAY) + INTERVAL 10 MINUTE, '紧急送医，已脱险', '已处置', 0),
(16,6,'主动上报','一般', DATE_SUB(NOW(), INTERVAL 5 DAY), '护工张桂英', DATE_SUB(NOW(), INTERVAL 5 DAY) + INTERVAL 18 MINUTE, '协助翻身护理完成', '已处置', 0),
(17,12,'家属呼叫','一般', DATE_SUB(NOW(), INTERVAL 7 DAY), '社区李干事', DATE_SUB(NOW(), INTERVAL 7 DAY) + INTERVAL 22 MINUTE, '安抚并转介社区', '已处置', 0),
(18,16,'设备告警','一般', DATE_SUB(NOW(), INTERVAL 2 DAY), '护工郑丽娟', DATE_SUB(NOW(), INTERVAL 2 DAY) + INTERVAL 15 MINUTE, '血压正常，误报解除', '已处置', 0),
(19,9,'主动上报','紧急', DATE_SUB(NOW(), INTERVAL 3 DAY), '护工冯国庆', DATE_SUB(NOW(), INTERVAL 3 DAY) + INTERVAL 14 MINUTE, '突发不适，陪同就医', '已处置', 0),
(20,14,'设备告警','一般', DATE_SUB(NOW(), INTERVAL 8 DAY), '护工刘晓芬', DATE_SUB(NOW(), INTERVAL 8 DAY) + INTERVAL 20 MINUTE, '设备故障，已更换', '已处置', 0),
(21,3,'设备告警','紧急', DATE_SUB(NOW(), INTERVAL 100 MINUTE), NULL, NULL, NULL, '待响应', 1),
(22,5,'家属呼叫','危急', DATE_SUB(NOW(), INTERVAL 20 MINUTE), NULL, NULL, NULL, '待响应', 1);

-- =====================================================================
-- 线3 护工与排班 · 补充种子(合并层重排编号,避开线4 已占用主键)
--   护工 21-31 = 线3 原 10-20(含证书临期/离职场景)
--   订单 23-33 = 线3 原编号(线4 订单止于 22)
--   派单 21-31 = 线3 原 17-27;工时引用同步重映射
-- =====================================================================
TRUNCATE work_hour;
INSERT INTO caregiver (caregiver_id, name, agency, cert_type, cert_level, cert_expire, service_regions, on_duty, rating) VALUES
(21,'马桂兰','安康护理服务有限公司','养老护理员','三级', DATE_ADD(CURDATE(), INTERVAL 12 DAY),'幸福社区,阳光社区','在岗',4.8),
(22,'林建军','康源康复中心','康复师','中级', DATE_ADD(CURDATE(), INTERVAL 25 DAY),'梧桐社区,滨江社区','在岗',4.7),
(23,'何秀英','乐龄养老服务社','家政服务员','高级', DATE_ADD(CURDATE(), INTERVAL 5 DAY),'幸福社区,梧桐社区','在岗',4.6),
(24,'高明远','安康护理服务有限公司','护士','主管护师', DATE_ADD(CURDATE(), INTERVAL 400 DAY),'海淀片区,幸福社区','在岗',4.9),
(25,'徐丽娜','康源康复中心','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 600 DAY),'阳光社区,滨江社区','在岗',4.5),
(26,'宋志刚','乐龄养老服务社','家政服务员','中级', DATE_ADD(CURDATE(), INTERVAL 320 DAY),'梧桐社区','在岗',4.3),
(27,'唐玉珍','安康护理服务有限公司','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 180 DAY),'幸福社区,阳光社区','在岗',4.6),
(28,'董文博','康源康复中心','康复师','初级', DATE_ADD(CURDATE(), INTERVAL 720 DAY),'滨江社区','在岗',4.7),
(29,'韩梅梅','乐龄养老服务社','家政服务员','初级', DATE_ADD(CURDATE(), INTERVAL 210 DAY),'阳光社区,梧桐社区','在岗',4.4),
(30,'曹建华','安康护理服务有限公司','养老护理员','四级', DATE_ADD(CURDATE(), INTERVAL 510 DAY),'幸福社区','在岗',4.8),
(31,'沈翠花','康源康复中心','养老护理员','五级', DATE_ADD(CURDATE(), INTERVAL 150 DAY),'滨江社区,幸福社区','离职',4.1);

INSERT INTO service_order (order_id, elder_id, item_id, appoint_time, address, channel, amount, status, created_at) VALUES
(23, 1, 1, DATE_SUB(NOW(), INTERVAL 14 DAY), '幸福社区3号楼2单元101', '家属端',     20.00, '已完成', DATE_SUB(NOW(), INTERVAL 16 DAY)),
(24, 2, 4, DATE_SUB(NOW(), INTERVAL 13 DAY), '幸福社区5号楼1单元302', '电话',       80.00, '已完成', DATE_SUB(NOW(), INTERVAL 15 DAY)),
(25, 3, 2, DATE_SUB(NOW(), INTERVAL 12 DAY), '阳光社区8栋601',       '社区代下单', 60.00, '已完成', DATE_SUB(NOW(), INTERVAL 14 DAY)),
(26, 5, 5, DATE_SUB(NOW(), INTERVAL 11 DAY), '梧桐社区甲区9号院',     '家属端',     90.00, '已完成', DATE_SUB(NOW(), INTERVAL 13 DAY)),
(27, 6, 6, DATE_SUB(NOW(), INTERVAL 10 DAY), '滨江社区东里11号楼',   '社区代下单', 50.00, '已完成', DATE_SUB(NOW(), INTERVAL 12 DAY)),
(28, 7, 3, DATE_SUB(NOW(), INTERVAL 9 DAY),  '滨江社区西里4号楼',     '家属端',     80.00, '已完成', DATE_SUB(NOW(), INTERVAL 11 DAY)),
(29, 8, 1, DATE_SUB(NOW(), INTERVAL 8 DAY),  '幸福社区9号楼5单元501', '电话',       20.00, '已完成', DATE_SUB(NOW(), INTERVAL 10 DAY)),
(30, 1, 4, DATE_SUB(NOW(), INTERVAL 7 DAY),  '幸福社区3号楼2单元101', '家属端',     80.00, '已完成', DATE_SUB(NOW(), INTERVAL 9 DAY)),
(31, 4, 1, DATE_SUB(NOW(), INTERVAL 6 DAY),  '阳光社区2栋1204',       '电话',       20.00, '已完成', DATE_SUB(NOW(), INTERVAL 8 DAY)),
(32, 5, 5, DATE_SUB(NOW(), INTERVAL 5 DAY),  '梧桐社区甲区9号院',     '社区代下单', 90.00, '已完成', DATE_SUB(NOW(), INTERVAL 7 DAY)),
(33, 6, 2, DATE_SUB(NOW(), INTERVAL 4 DAY),  '滨江社区东里11号楼',   '家属端',     60.00, '已完成', DATE_SUB(NOW(), INTERVAL 6 DAY));

INSERT INTO dispatch (dispatch_id, order_id, caregiver_id, dispatch_time, arrive_time, leave_time, service_note, confirmed, is_current, reassign_reason) VALUES
(21, 23, 1,  DATE_SUB(NOW(), INTERVAL 15 DAY), DATE_SUB(NOW(), INTERVAL 14 DAY), DATE_SUB(NOW(), INTERVAL 14 DAY) + INTERVAL 60 MINUTE,  '准时送餐，家属签收', 1, 1, NULL),
(22, 24, 6,  DATE_SUB(NOW(), INTERVAL 14 DAY), DATE_SUB(NOW(), INTERVAL 13 DAY), DATE_SUB(NOW(), INTERVAL 13 DAY) + INTERVAL 120 MINUTE, '全屋保洁完成',       1, 1, NULL),
(23, 25, 4,  DATE_SUB(NOW(), INTERVAL 13 DAY), DATE_SUB(NOW(), INTERVAL 12 DAY), DATE_SUB(NOW(), INTERVAL 12 DAY) + INTERVAL 90 MINUTE,  '助浴完成，状态平稳', 1, 1, NULL),
(24, 26, 5,  DATE_SUB(NOW(), INTERVAL 12 DAY), DATE_SUB(NOW(), INTERVAL 11 DAY), DATE_SUB(NOW(), INTERVAL 11 DAY) + INTERVAL 60 MINUTE,  '下肢康复指导完成',   1, 1, NULL),
(25, 27, 4,  DATE_SUB(NOW(), INTERVAL 11 DAY), DATE_SUB(NOW(), INTERVAL 10 DAY), DATE_SUB(NOW(), INTERVAL 10 DAY) + INTERVAL 45 MINUTE,  '翻身及皮肤护理完成', 1, 1, NULL),
(26, 28, 2,  DATE_SUB(NOW(), INTERVAL 10 DAY), DATE_SUB(NOW(), INTERVAL 9 DAY),  DATE_SUB(NOW(), INTERVAL 9 DAY)  + INTERVAL 180 MINUTE, '陪同取药复诊完成',   1, 1, NULL),
(27, 29, 21, DATE_SUB(NOW(), INTERVAL 9 DAY),  DATE_SUB(NOW(), INTERVAL 8 DAY),  DATE_SUB(NOW(), INTERVAL 8 DAY)  + INTERVAL 60 MINUTE,  '午餐配送完成',       1, 1, NULL),
(28, 30, 23, DATE_SUB(NOW(), INTERVAL 8 DAY),  DATE_SUB(NOW(), INTERVAL 7 DAY),  DATE_SUB(NOW(), INTERVAL 7 DAY)  + INTERVAL 120 MINUTE, '玻璃及厨房保洁完成', 1, 1, NULL),
(29, 31, 25, DATE_SUB(NOW(), INTERVAL 7 DAY),  DATE_SUB(NOW(), INTERVAL 6 DAY),  DATE_SUB(NOW(), INTERVAL 6 DAY)  + INTERVAL 60 MINUTE,  '送餐上门完成',       1, 1, NULL),
(30, 32, 22, DATE_SUB(NOW(), INTERVAL 6 DAY),  DATE_SUB(NOW(), INTERVAL 5 DAY),  DATE_SUB(NOW(), INTERVAL 5 DAY)  + INTERVAL 60 MINUTE,  '关节活动度训练完成', 1, 1, NULL),
(31, 33, 27, DATE_SUB(NOW(), INTERVAL 5 DAY),  DATE_SUB(NOW(), INTERVAL 4 DAY),  DATE_SUB(NOW(), INTERVAL 4 DAY)  + INTERVAL 90 MINUTE,  '协助沐浴完成',       1, 1, NULL);

INSERT INTO work_hour (work_hour_id, caregiver_id, dispatch_id, checkin_time, checkout_time, checkin_location, fence_result, valid_hours, review_status) VALUES
(1, 4, 1,  DATE_SUB(NOW(), INTERVAL 28 DAY), DATE_SUB(NOW(), INTERVAL 28 DAY) + INTERVAL 90 MINUTE,  '阳光社区8栋601楼下(116.312,39.981)', '通过', 1.50, '自动认定'),
(2, 4, 2,  DATE_SUB(NOW(), INTERVAL 26 DAY), DATE_SUB(NOW(), INTERVAL 26 DAY) + INTERVAL 40 MINUTE,  '阳光社区8栋601楼下(116.312,39.981)', '通过', 0.67, '自动认定'),
(3, 1, 3,  DATE_SUB(NOW(), INTERVAL 25 DAY), DATE_SUB(NOW(), INTERVAL 25 DAY) + INTERVAL 60 MINUTE,  '阳光社区2栋1204门前(116.314,39.982)', '通过', 1.00, '自动认定'),
(4, 1, 4,  DATE_SUB(NOW(), INTERVAL 24 DAY), DATE_SUB(NOW(), INTERVAL 24 DAY) + INTERVAL 60 MINUTE,  '阳光社区2栋1204门前(116.314,39.982)', '通过', 1.00, '自动认定'),
(5, 2, 5,  DATE_SUB(NOW(), INTERVAL 20 DAY), DATE_SUB(NOW(), INTERVAL 20 DAY) + INTERVAL 60 MINUTE,  '滨江社区西里4号楼(116.351,39.912)',   '通过', 1.00, '自动认定'),
(6, 4, 6,  DATE_SUB(NOW(), INTERVAL 18 DAY), DATE_SUB(NOW(), INTERVAL 18 DAY) + INTERVAL 180 MINUTE, '滨江社区西里4号楼(116.351,39.912)',   '通过', 3.00, '自动认定'),
(7, 3, 7,  DATE_SUB(NOW(), INTERVAL 15 DAY), DATE_SUB(NOW(), INTERVAL 15 DAY) + INTERVAL 150 MINUTE, '幸福社区3号楼2单元(116.305,39.990)',  '围栏外异常', 0.00, '待人工复核'),
(8, 4, 13, DATE_SUB(NOW(), INTERVAL 2 HOUR), NULL,                                                 '滨江社区东里11号楼(116.353,39.914)', '通过', 0.00, '自动认定'),
(9, 6, 14, DATE_SUB(NOW(), INTERVAL 1 HOUR), NULL,                                                 '幸福社区3号楼2单元(116.305,39.990)',  '通过', 0.00, '自动认定');

INSERT INTO work_hour (work_hour_id, caregiver_id, dispatch_id, checkin_time, checkout_time, checkin_location, fence_result, valid_hours, review_status) VALUES
(10, 1,  21, DATE_SUB(NOW(), INTERVAL 14 DAY), DATE_SUB(NOW(), INTERVAL 14 DAY) + INTERVAL 60 MINUTE,  '幸福社区3号楼2单元(116.305,39.990)', '通过',       1.00, '自动认定'),
(11, 6,  22, DATE_SUB(NOW(), INTERVAL 13 DAY), DATE_SUB(NOW(), INTERVAL 13 DAY) + INTERVAL 120 MINUTE, '幸福社区5号楼1单元(116.306,39.991)', '通过',       2.00, '自动认定'),
(12, 4,  23, DATE_SUB(NOW(), INTERVAL 12 DAY), DATE_SUB(NOW(), INTERVAL 12 DAY) + INTERVAL 90 MINUTE,  '阳光社区8栋601楼下(116.312,39.981)', '通过',       1.50, '自动认定'),
(13, 5,  24, DATE_SUB(NOW(), INTERVAL 11 DAY), DATE_SUB(NOW(), INTERVAL 11 DAY) + INTERVAL 60 MINUTE,  '梧桐社区甲区9号院(116.412,39.931)',   '通过',       1.00, '自动认定'),
(14, 4,  25, DATE_SUB(NOW(), INTERVAL 10 DAY), DATE_SUB(NOW(), INTERVAL 10 DAY) + INTERVAL 45 MINUTE,  '滨江社区东里11号楼(116.353,39.914)', '通过',       0.75, '自动认定'),
(15, 2,  26, DATE_SUB(NOW(), INTERVAL 9 DAY),  DATE_SUB(NOW(), INTERVAL 9 DAY)  + INTERVAL 180 MINUTE, '滨江社区西里4号楼(116.351,39.912)',   '围栏外异常', 3.00, '复核通过'),
(16, 21, 27, DATE_SUB(NOW(), INTERVAL 8 DAY),  DATE_SUB(NOW(), INTERVAL 8 DAY)  + INTERVAL 60 MINUTE,  '幸福社区9号楼5单元(116.308,39.993)', '通过',       1.00, '自动认定'),
(17, 23, 28, DATE_SUB(NOW(), INTERVAL 7 DAY),  DATE_SUB(NOW(), INTERVAL 7 DAY)  + INTERVAL 120 MINUTE, '幸福社区3号楼2单元(116.305,39.990)', '通过',       2.00, '自动认定'),
(18, 25, 29, DATE_SUB(NOW(), INTERVAL 6 DAY),  DATE_SUB(NOW(), INTERVAL 6 DAY)  + INTERVAL 60 MINUTE,  '阳光社区2栋1204门前(116.314,39.982)', '通过',       1.00, '自动认定'),
(19, 22, 30, DATE_SUB(NOW(), INTERVAL 5 DAY),  DATE_SUB(NOW(), INTERVAL 5 DAY)  + INTERVAL 60 MINUTE,  '梧桐社区甲区9号院(116.412,39.931)',   '围栏外异常', 0.00, '待人工复核'),
(20, 27, 31, DATE_SUB(NOW(), INTERVAL 4 DAY),  DATE_SUB(NOW(), INTERVAL 4 DAY)  + INTERVAL 90 MINUTE,  '滨江社区东里11号楼(116.353,39.914)', '通过',       1.50, '自动认定');

INSERT INTO schedule (caregiver_id, work_date, shift, capacity, booked, status)
SELECT cg.caregiver_id,
       DATE_ADD(CURDATE(), INTERVAL d.n DAY),
       s.shift,
       3 + (cg.caregiver_id % 2), 0, '开放'
FROM caregiver cg
CROSS JOIN (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6) d
CROSS JOIN (SELECT '上午' shift UNION SELECT '下午') s
WHERE cg.on_duty = '在岗' AND cg.caregiver_id >= 21;

-- 护工可承接服务项目种子数据 (24条，满足每表>=20条规范)
INSERT INTO caregiver_item (caregiver_id, item_id, cert_verified) VALUES
(1, 1, 1), (1, 4, 1), (1, 6, 1),
(2, 3, 1), (2, 6, 1), (2, 7, 1),
(4, 2, 1), (4, 6, 1),
(5, 5, 1), (5, 7, 1),
(6, 1, 1), (6, 4, 1),
(8, 1, 1), (8, 4, 1),
(9, 2, 1), (9, 6, 1),
(10, 1, 1), (10, 4, 1),
(11, 5, 1), (11, 7, 1),
(12, 1, 1), (12, 4, 1),
(14, 1, 1), (16, 2, 1);