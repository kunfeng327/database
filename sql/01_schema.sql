-- =====================================================================
-- 社区居家养老智慧服务平台 · 演示库建库建表脚本（MySQL 8.0+ / 9.x）
-- 库名：elder_care   注意：会先 DROP 旧库，重复执行=全部重置
-- =====================================================================
SET NAMES utf8mb4;
DROP DATABASE IF EXISTS elder_care;
CREATE DATABASE elder_care DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE elder_care;

-- ------------------------- 1 社区 -------------------------
CREATE TABLE community (
  community_id      INT PRIMARY KEY AUTO_INCREMENT COMMENT '社区编号',
  name              VARCHAR(50)  NOT NULL UNIQUE COMMENT '社区名称',
  district          VARCHAR(50)  NOT NULL COMMENT '所属区县',
  service_radius_km DECIMAL(4,1) NOT NULL DEFAULT 3.0 COMMENT '服务半径(公里)'
);

-- ------------------------- 2 护工档案 -------------------------
CREATE TABLE caregiver (
  caregiver_id   INT PRIMARY KEY AUTO_INCREMENT COMMENT '护工编号',
  name           VARCHAR(30) NOT NULL COMMENT '姓名',
  agency         VARCHAR(50) NOT NULL COMMENT '所属机构',
  cert_type      ENUM('养老护理员','康复师','护士','家政服务员') NOT NULL COMMENT '证书类型',
  cert_level     VARCHAR(10) NULL COMMENT '证书等级',
  cert_expire    DATE NOT NULL COMMENT '证书有效期截止',
  service_regions VARCHAR(100) NOT NULL COMMENT '可服务区域(社区名,逗号分隔)',
  on_duty        ENUM('在岗','离职') NOT NULL DEFAULT '在岗',
  rating         DECIMAL(2,1) NOT NULL DEFAULT 5.0 COMMENT '评分',
  CONSTRAINT chk_rating CHECK (rating BETWEEN 0 AND 5),
  INDEX idx_caregiver_region (service_regions(20)),
  INDEX idx_caregiver_cert (cert_expire)
);

-- ------------------------- 3 老人档案 -------------------------
CREATE TABLE elder (
  elder_id       INT PRIMARY KEY AUTO_INCREMENT COMMENT '档案编号',
  name           VARCHAR(30) NOT NULL COMMENT '姓名',
  id_card        CHAR(18) NOT NULL UNIQUE COMMENT '身份证号(唯一,展示时脱敏)',
  birth_date     DATE NOT NULL COMMENT '出生日期',
  gender         ENUM('男','女') NOT NULL,
  address        VARCHAR(100) NOT NULL COMMENT '居住地址',
  community_id   INT NOT NULL COMMENT '所属社区',
  guardian_name  VARCHAR(30) NOT NULL COMMENT '监护人姓名',
  guardian_phone CHAR(11) NOT NULL COMMENT '监护人电话',
  special_tag    SET('独居','失能','低保','高龄') NULL COMMENT '特殊标签',
  status         ENUM('正常','暂停服务','注销') NOT NULL DEFAULT '正常' COMMENT '档案状态',
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_elder_community FOREIGN KEY (community_id) REFERENCES community(community_id),
  CONSTRAINT chk_idcard CHECK (CHAR_LENGTH(id_card) = 18),
  INDEX idx_elder_community (community_id),
  INDEX idx_elder_status (status)
);

-- ------------------------- 4 能力评估 -------------------------
CREATE TABLE assessment (
  assessment_id  INT PRIMARY KEY AUTO_INCREMENT COMMENT '评估编号',
  elder_id       INT NOT NULL,
  scale          ENUM('ADL','简易智能状态') NOT NULL COMMENT '评估量表',
  score          INT NOT NULL COMMENT '得分',
  ability_level  ENUM('能力完好','轻度失能','中度失能','重度失能') NOT NULL COMMENT '能力等级',
  assessor       VARCHAR(30) NOT NULL COMMENT '评估员',
  assess_date    DATE NOT NULL COMMENT '评估日期',
  expire_date    DATE NOT NULL COMMENT '有效期截止',
  CONSTRAINT fk_assess_elder FOREIGN KEY (elder_id) REFERENCES elder(elder_id),
  CONSTRAINT chk_score CHECK (score BETWEEN 0 AND 100),
  CONSTRAINT chk_assess_date CHECK (expire_date > assess_date),
  INDEX idx_assess_elder (elder_id, expire_date)
);

-- ------------------------- 5 照护计划 -------------------------
CREATE TABLE care_plan (
  plan_id      INT PRIMARY KEY AUTO_INCREMENT COMMENT '计划编号',
  elder_id     INT NOT NULL,
  package_name VARCHAR(50) NOT NULL COMMENT '服务包名称',
  frequency    VARCHAR(50) NOT NULL COMMENT '服务频次',
  start_date   DATE NOT NULL,
  end_date     DATE NOT NULL,
  caregiver_id INT NULL COMMENT '责任护工',
  status       ENUM('生效','暂停','结束') NOT NULL DEFAULT '生效',
  CONSTRAINT fk_plan_elder FOREIGN KEY (elder_id) REFERENCES elder(elder_id),
  CONSTRAINT fk_plan_caregiver FOREIGN KEY (caregiver_id) REFERENCES caregiver(caregiver_id),
  CONSTRAINT chk_plan_date CHECK (end_date >= start_date),
  INDEX idx_plan_elder (elder_id, status)
);

-- ------------------------- 6 服务项目 -------------------------
CREATE TABLE service_item (
  item_id     INT PRIMARY KEY AUTO_INCREMENT COMMENT '项目编号',
  name        VARCHAR(50) NOT NULL UNIQUE COMMENT '项目名称',
  type        ENUM('助餐','助浴','陪诊','家政','康复护理') NOT NULL COMMENT '服务类型',
  unit        ENUM('次','小时') NOT NULL COMMENT '计价单位',
  guide_price DECIMAL(8,2) NOT NULL COMMENT '指导价',
  std_hours   DECIMAL(3,1) NOT NULL COMMENT '标准时长(小时)',
  subsidizable TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否可补贴'
);

-- ------------------------- 7 服务订单 -------------------------
CREATE TABLE service_order (
  order_id     INT PRIMARY KEY AUTO_INCREMENT COMMENT '订单编号',
  elder_id     INT NOT NULL,
  item_id      INT NOT NULL,
  appoint_time DATETIME NOT NULL COMMENT '预约时间',
  address      VARCHAR(100) NOT NULL COMMENT '服务地址',
  channel      ENUM('电话','家属端','社区代下单') NOT NULL COMMENT '下单渠道',
  amount       DECIMAL(8,2) NOT NULL DEFAULT 0 COMMENT '订单金额',
  status       ENUM('待派单','已派单','服务中','已完成','已取消') NOT NULL DEFAULT '待派单',
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_order_elder FOREIGN KEY (elder_id) REFERENCES elder(elder_id),
  CONSTRAINT fk_order_item  FOREIGN KEY (item_id)  REFERENCES service_item(item_id),
  INDEX idx_order_status (status),
  INDEX idx_order_elder (elder_id),
  INDEX idx_order_time (appoint_time)
);

-- ------------------------- 8 派单记录 -------------------------
CREATE TABLE dispatch (
  dispatch_id    INT PRIMARY KEY AUTO_INCREMENT COMMENT '派单编号',
  order_id       INT NOT NULL,
  caregiver_id   INT NOT NULL,
  dispatch_time  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '接单/派单时间',
  arrive_time    DATETIME NULL COMMENT '上门时间',
  leave_time     DATETIME NULL COMMENT '离场时间',
  service_note   VARCHAR(200) NULL COMMENT '服务记录',
  confirmed      TINYINT(1) NOT NULL DEFAULT 0 COMMENT '家属确认(双方签字)',
  is_current     TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否当前派单(改派后置0)',
  reassign_reason VARCHAR(100) NULL COMMENT '改派原因',
  CONSTRAINT fk_disp_order FOREIGN KEY (order_id) REFERENCES service_order(order_id),
  CONSTRAINT fk_disp_caregiver FOREIGN KEY (caregiver_id) REFERENCES caregiver(caregiver_id),
  INDEX idx_disp_order (order_id, is_current),
  INDEX idx_disp_caregiver (caregiver_id)
);

-- ------------------------- 9 排班 -------------------------
CREATE TABLE schedule (
  schedule_id  INT PRIMARY KEY AUTO_INCREMENT COMMENT '排班编号',
  caregiver_id INT NOT NULL,
  work_date    DATE NOT NULL COMMENT '排班日期',
  shift        ENUM('上午','下午','全天') NOT NULL COMMENT '班次时段',
  capacity     INT NOT NULL DEFAULT 4 COMMENT '可接单量',
  booked       INT NOT NULL DEFAULT 0 COMMENT '已接单量',
  status       ENUM('开放','关闭') NOT NULL DEFAULT '开放',
  CONSTRAINT fk_sched_caregiver FOREIGN KEY (caregiver_id) REFERENCES caregiver(caregiver_id),
  CONSTRAINT uk_sched UNIQUE (caregiver_id, work_date, shift) COMMENT '排班不重复',
  CONSTRAINT chk_capacity CHECK (booked >= 0 AND booked <= capacity), -- 已接单量不得超过可接单量
  INDEX idx_sched_date (work_date, status)
);

-- ------------------------- 10 补贴政策 -------------------------
CREATE TABLE subsidy_policy (
  policy_id      INT PRIMARY KEY AUTO_INCREMENT COMMENT '政策编号',
  district       VARCHAR(50) NOT NULL COMMENT '适用区县',
  target_type    ENUM('低保','失能','高龄','独居') NOT NULL COMMENT '对象类别',
  item_id        INT NOT NULL COMMENT '补贴项目',
  standard       DECIMAL(8,2) NOT NULL COMMENT '补贴标准(元/单位)',
  period         VARCHAR(20) NOT NULL DEFAULT '月' COMMENT '结算周期',
  effective_from DATE NOT NULL,
  effective_to   DATE NOT NULL,
  CONSTRAINT fk_policy_item FOREIGN KEY (item_id) REFERENCES service_item(item_id),
  CONSTRAINT chk_policy_date CHECK (effective_to >= effective_from)
);

-- ------------------------- 11 补贴申报 -------------------------
CREATE TABLE subsidy_claim (
  claim_id     INT PRIMARY KEY AUTO_INCREMENT COMMENT '申报编号',
  elder_id     INT NOT NULL,
  policy_id    INT NOT NULL,
  claim_period CHAR(7) NOT NULL COMMENT '所属账期 YYYY-MM',
  order_ids    VARCHAR(200) NOT NULL COMMENT '关联订单集合(可追溯)',
  amount       DECIMAL(8,2) NOT NULL COMMENT '申报金额',
  status       ENUM('待审核','街道已审','已拨付','已驳回') NOT NULL DEFAULT '待审核',
  reviewer     VARCHAR(30) NULL COMMENT '审核人',
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_claim_elder  FOREIGN KEY (elder_id)  REFERENCES elder(elder_id),
  CONSTRAINT fk_claim_policy FOREIGN KEY (policy_id) REFERENCES subsidy_policy(policy_id),
  CONSTRAINT uk_claim_no_dup UNIQUE (elder_id, policy_id, claim_period) COMMENT '同一老人同期同项目不得重复申报',
  INDEX idx_claim_status (status)
);

-- ------------------------- 12 系统用户（登录与RBAC） -------------------------
CREATE TABLE sys_user (
  user_id        INT PRIMARY KEY AUTO_INCREMENT,
  username       VARCHAR(30) NOT NULL UNIQUE COMMENT '登录名',
  password_hash  CHAR(64) NOT NULL COMMENT 'SHA256(盐+密码) 十六进制',
  salt           CHAR(16) NOT NULL COMMENT '随机盐',
  real_name      VARCHAR(30) NOT NULL COMMENT '姓名',
  role           ENUM('家属','护工','社区管理员','机构负责人','监管人员') NOT NULL,
  elder_id       INT NULL COMMENT '家属绑定的老人档案',
  caregiver_id   INT NULL COMMENT '护工账号绑定的护工档案',
  failed_attempts INT NOT NULL DEFAULT 0 COMMENT '连续登录失败次数',
  locked_until   DATETIME NULL COMMENT '锁定截止时间(失败5次锁10分钟)',
  status         ENUM('启用','停用') NOT NULL DEFAULT '启用',
  last_login     DATETIME NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_elder FOREIGN KEY (elder_id) REFERENCES elder(elder_id),
  CONSTRAINT fk_user_caregiver FOREIGN KEY (caregiver_id) REFERENCES caregiver(caregiver_id),
  CONSTRAINT chk_role_bind CHECK (
    (role = '家属' AND elder_id IS NOT NULL)
    OR (role = '护工' AND caregiver_id IS NOT NULL)
    OR role IN ('社区管理员','机构负责人','监管人员')
  ),
  INDEX idx_user_role (role, status)
);
