# 社区居家养老智慧服务平台全局 E-R 图

本图合并五条业务线的局部 E-R 设计，并以 `sql/01_schema.sql` 中实际建表的外键为准。共覆盖 18 张表；图中展示主键、外键及主要业务字段。

<!-- mermaid-checked: every attribute is `<type> <name> [<key>] ["<description>"]` with at most one of PK/FK/UK, no \n in descriptions, no {} in descriptions, every relationship label is double-quoted -->
```mermaid
erDiagram
    COMMUNITY ||--o{ ELDER : "has elders"
    ELDER ||--o{ ASSESSMENT : "has assessments"
    ELDER ||--o{ CARE_PLAN : "has care plans"
    CAREGIVER |o--o{ CARE_PLAN : "assigned caregiver"
    ELDER ||--o{ SERVICE_ORDER : "places orders"
    SERVICE_ITEM ||--o{ SERVICE_ORDER : "ordered item"
    SERVICE_ORDER ||--o{ DISPATCH : "dispatch history"
    CAREGIVER ||--o{ DISPATCH : "accepts dispatch"
    CAREGIVER ||--o{ SCHEDULE : "has schedules"
    CAREGIVER ||--o{ WORK_HOUR : "records work hours"
    DISPATCH ||--o| WORK_HOUR : "may have work record"
    CAREGIVER ||--o{ CAREGIVER_ITEM : "has qualifications"
    SERVICE_ITEM ||--o{ CAREGIVER_ITEM : "qualified service"
    ELDER ||--o{ SUBSIDY_CLAIM : "has claims"
    SUBSIDY_POLICY ||--o{ SUBSIDY_CLAIM : "applied policy"
    SERVICE_ITEM ||--o{ SUBSIDY_POLICY : "covered service"
    SERVICE_ORDER |o--o{ QUALITY_INSPECTION : "inspected order"
    CAREGIVER |o--o{ QUALITY_INSPECTION : "inspected caregiver"
    ELDER ||--o{ DEVICE : "has devices"
    DEVICE ||--o{ VITAL_SIGN : "collects readings"
    ELDER ||--o{ VITAL_SIGN : "reading owner snapshot"
    ELDER ||--o{ EMERGENCY : "has emergency events"
    ELDER |o--o{ SYS_USER : "family account binding"
    CAREGIVER |o--o{ SYS_USER : "caregiver account binding"
    SUBSIDY_CLAIM }o--o{ SERVICE_ORDER : "order ids text reference"

    COMMUNITY {
        int community_id PK
        varchar name UK
        varchar district
        decimal service_radius_km
    }
    CAREGIVER {
        int caregiver_id PK
        varchar name
        varchar agency
        date cert_expire
        enum on_duty
        decimal rating
        decimal total_hours
    }
    ELDER {
        int elder_id PK
        char id_card UK
        varchar name
        date birth_date
        int community_id FK
        varchar guardian_phone
        set special_tag
        enum status
    }
    ASSESSMENT {
        int assessment_id PK
        int elder_id FK
        int score
        enum ability_level
        date assess_date
        date expire_date
    }
    CARE_PLAN {
        int plan_id PK
        int elder_id FK
        int caregiver_id FK
        varchar package_name
        date start_date
        date end_date
        enum status
    }
    SERVICE_ITEM {
        int item_id PK
        varchar name UK
        enum type
        decimal guide_price
        decimal std_hours
        tinyint subsidizable
    }
    SERVICE_ORDER {
        int order_id PK
        int elder_id FK
        int item_id FK
        datetime appoint_time
        decimal amount
        enum channel
        enum status
    }
    DISPATCH {
        int dispatch_id PK
        int order_id FK
        int caregiver_id FK
        datetime dispatch_time
        tinyint confirmed
        tinyint is_current
    }
    SCHEDULE {
        int schedule_id PK
        int caregiver_id FK
        date work_date
        enum shift
        int capacity
        int booked
        enum status
    }
    WORK_HOUR {
        int work_hour_id PK
        int caregiver_id FK
        int dispatch_id UK "unique FK to dispatch"
        datetime checkin_time
        datetime checkout_time
        decimal valid_hours
        enum review_status
    }
    CAREGIVER_ITEM {
        int caregiver_id PK "also FK to caregiver"
        int item_id PK "also FK to service item"
        tinyint cert_verified
    }
    SUBSIDY_POLICY {
        int policy_id PK
        int item_id FK
        varchar district
        enum target_type
        decimal standard
        date effective_from
        date effective_to
    }
    SUBSIDY_CLAIM {
        int claim_id PK
        int elder_id FK
        int policy_id FK
        char claim_period
        varchar order_ids
        decimal amount
        enum audit_status
        enum pay_status
    }
    QUALITY_INSPECTION {
        int inspection_id PK
        int order_id FK
        int caregiver_id FK
        tinyint score
        enum inspection_status
        enum rectification_status
    }
    DEVICE {
        int device_id PK
        int elder_id FK
        enum device_type
        datetime bind_time
        datetime unbind_time
        enum status
    }
    VITAL_SIGN {
        int vital_id PK
        int device_id FK
        int elder_id FK
        datetime collect_time
        enum metric_type
        decimal metric_value
        enum abnormal_flag
    }
    EMERGENCY {
        int event_id PK
        int elder_id FK
        enum trigger_source
        enum event_level
        datetime occur_time
        varchar responder
        enum status
        tinyint escalated
    }
    SYS_USER {
        int user_id PK
        varchar username UK
        char password_hash
        enum role
        int elder_id FK
        int caregiver_id FK
        enum status
    }
```

## 关系说明

- `caregiver_item` 是护工与服务项目的多对多关联表，联合主键同时承担外键作用。
- `dispatch` 与 `work_hour` 是一对零或一关系：工时表中的 `dispatch_id` 唯一且非空，但尚未完成的派单可以没有工时记录。
- `care_plan.caregiver_id`、`quality_inspection.order_id`、`quality_inspection.caregiver_id` 允许为空，因此对应关系按可选关联表示。
- `quality_inspection` 至少要关联一个订单或护工，该规则由检查约束保证。
- `subsidy_claim.order_ids` 是逗号分隔的订单编号文本，不是外键。图中的申报与订单连线仅表示业务追溯关系，不受数据库外键约束。
- `sys_user` 通过可空外键关联老人或护工；用户角色与绑定对象的限制由 `sys_user` 上的检查约束控制。
- `caregiver.agency` 是文本字段，当前没有单独的机构实体表。
