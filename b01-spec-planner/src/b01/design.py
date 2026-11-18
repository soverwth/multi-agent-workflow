"""B01 参考实现使用的固定设计数据。

数据来源：桌面《项目实践》目录中两份以“第10组”开头的团队文档。
本模块只做只读转录和结构化，不生成新的业务规则。
"""

from __future__ import annotations

PROJECT_ID = "campus-lost-found"
SPEC_VERSION = "S1-v1.0"
CONTRACT_VERSION = "C1-v1.0"
PLAN_VERSION = "PLAN-v1.0"

REQUIRED_REQUIREMENTS = ["LR-01", "LR-02", "LR-03", "LR-04", "LR-05"]

SOURCE_DOC_1 = {
    "document": "第10组_第一部分_多智能体讨论与需求确认(1).docx",
    "sha256": "8F4A7F20B6F902EEAA99E15B42E58D32ED7C366955D407B9612DBBEF77CB4E34",
    "sections": ["9.1", "9.1.1", "9.2", "9.3", "10", "11", "14.1"],
}

SOURCE_DOC_2 = {
    "document": "第10组_第二部分_设计规格与开发任务编排(1).docx",
    "sha256": "E1567A68D6E5AB8111E4576E4296E4E001DBB62BF01A2F3534E92CFF2DC19974",
    "sections": ["2.1", "2.2.2", "2.2.3", "2.2.4", "4.2", "4.3", "4.3.1", "5.2", "9.1", "10.1"],
}

R1 = {
    "project_id": PROJECT_ID,
    "requirements_version": "R1-REFERENCE-v1.0",
    "status": "REFERENCE_BASELINE_NOT_HUMAN_CONFIRMED",
    "source": SOURCE_DOC_1,
    "human_confirmation": {
        "required": True,
        "status": "PENDING",
        "reviewers": {block: "PENDING" for block in ("B01", "B02", "B03", "B04", "B05", "B06")},
        "note": "团队文档明确说明示例不构成真实六人确认记录；参考实现不得声称已完成人类确认。",
    },
    "scope": [
        "LR-01 注册登录",
        "LR-02 发布失物",
        "LR-03 关键词及地点搜索",
        "LR-04 认领申请",
        "LR-05 本人资料及本人记录",
    ],
    "out_of_scope": [
        "举报",
        "过期清理",
        "校园统一身份认证",
        "实时聊天",
        "公开私人联系方式",
        "认领确认、驳回与完成状态",
    ],
    "requirements": [
        {
            "req_id": "LR-01",
            "description": "普通校内用户注册、登录和退出；受保护操作要求已登录；凭据不得明文保存或返回。",
            "priority": "必须",
            "source_decision": "DOC-EXAMPLE-9.3",
            "acceptance": ["重复账号拒绝", "错误凭据拒绝", "未登录不能发布或申请认领"],
            "constraints": ["password_hash 不得出现在任何公开响应"],
            "status": "REFERENCE_DRAFT",
        },
        {
            "req_id": "LR-02",
            "description": "用户填写名称、描述、丢失地点、丢失时间 lost_at；发布者取当前身份；初始状态为待认领。",
            "priority": "必须",
            "source_decision": "DOC-EXAMPLE-9.3",
            "acceptance": ["合法输入生成记录", "lost_at 缺失、空值或格式错误时拒绝且不写入"],
            "constraints": ["publisher_id 由会话取得，不接受客户端指定", "status 本轮仅取 waiting"],
            "status": "REFERENCE_DRAFT",
        },
        {
            "req_id": "LR-03",
            "description": "按关键词及丢失地点检索，支持分页；列表和详情不暴露登录凭据与私人联系方式。",
            "priority": "必须",
            "source_decision": "DOC-EXAMPLE-9.3",
            "acceptance": ["匹配项可检索", "无匹配返回空列表", "详情字段与发布结果一致"],
            "constraints": ["公开视图使用 LostView", "page_size 范围 1—100"],
            "status": "REFERENCE_DRAFT",
        },
        {
            "req_id": "LR-04",
            "description": "登录用户对待认领信息提交说明；禁止认领自己的信息及重复提交；本人可查看申请。",
            "priority": "必须",
            "source_decision": "DOC-EXAMPLE-9.3",
            "acceptance": ["有效申请生成 pending 记录", "本人信息、重复申请及无效对象均拒绝"],
            "constraints": ["(lost_item_id, applicant_id) 唯一", "状态检查、权限检查与插入同事务"],
            "status": "REFERENCE_DRAFT",
        },
        {
            "req_id": "LR-05",
            "description": "查看与修改本人昵称等允许字段；查看本人发布与认领记录；账号标识不由客户端任意改写。",
            "priority": "必须",
            "source_decision": "DOC-EXAMPLE-9.3",
            "acceptance": ["修改只影响本人", "不能越权查看或修改他人个人资料"],
            "constraints": ["update_me 仅接受 nickname", "本人列表使用统一分页规则"],
            "status": "REFERENCE_DRAFT",
        },
    ],
    "non_blocking_open_questions": [
        {
            "id": "OQ-UAA",
            "description": "是否接入校园统一身份认证",
            "owner": "六人共同确认",
            "impact": "不影响本轮基础注册登录",
        }
    ],
    "blocking_open_questions": [],
}

DESIGN_ENTRIES = [
    {
        "design_id": "DS-AUTH-01",
        "module": "用户与身份",
        "req_refs": ["LR-01"],
        "contract_refs": ["register", "login", "logout"],
        "test_refs": ["TC-AUTH-01", "TC-AUTH-02"],
        "rule": "注册不自动登录；口令使用 Argon2id(19MiB,2,1)；会话 24 小时失效，logout 撤销当前令牌。",
    },
    {
        "design_id": "DS-USER-01",
        "module": "用户与身份",
        "req_refs": ["LR-05"],
        "contract_refs": ["get_me", "update_me", "list_my_posts", "list_my_claims"],
        "test_refs": ["TC-USER-01"],
        "rule": "身份从会话取得；update_me 仅接受 nickname；本人列表按 created_at/id 降序稳定分页。",
    },
    {
        "design_id": "DS-LOST-01",
        "module": "失物发布与搜索",
        "req_refs": ["LR-02"],
        "contract_refs": ["publish_lost"],
        "test_refs": ["TC-P01", "TC-P02", "TC-P03"],
        "rule": "lost_at 必填且带时区；缺失/空/非法值拒绝且不写入；发布者取自当前身份，status=waiting。",
    },
    {
        "design_id": "DS-LOST-02",
        "module": "失物发布与搜索",
        "req_refs": ["LR-03"],
        "contract_refs": ["search_lost", "get_lost"],
        "test_refs": ["TC-SEARCH-01", "TC-SEARCH-02"],
        "rule": "keyword 普通包含匹配，location 去空白后精确匹配；公开视图统一为 LostView。",
    },
    {
        "design_id": "DS-CLAIM-01",
        "module": "认领申请",
        "req_refs": ["LR-04"],
        "contract_refs": ["create_claim"],
        "test_refs": ["TC-CLAIM-01", "TC-CLAIM-02"],
        "rule": "禁止认领本人信息；对象状态、权限、重复性与插入在同一事务；重复申请转 DUPLICATE_CLAIM。",
    },
    {
        "design_id": "DS-COMMON-01",
        "module": "公共契约",
        "req_refs": REQUIRED_REQUIREMENTS,
        "contract_refs": ["response_envelope", "error_mapping"],
        "test_refs": ["TC-ERR-01"],
        "rule": "成功固定 {ok:true,data:值}；失败固定 {ok:false,error:{code,field,message}} 且不含 data。",
    },
    {
        "design_id": "DS-B03-01",
        "module": "黑板状态",
        "req_refs": REQUIRED_REQUIREMENTS,
        "contract_refs": ["task_store", "artifact_store"],
        "test_refs": ["TC-B03-01"],
        "rule": "黑板过程数据与校园业务数据分开管理，不为 Orchestrator 另建业务库。",
    },
    {
        "design_id": "DS-B03-02",
        "module": "黑板状态",
        "req_refs": REQUIRED_REQUIREMENTS,
        "contract_refs": ["task_store"],
        "test_refs": ["TC-B03-02"],
        "rule": "黑板公共约定采用 UUID、只追加和版本标记。",
    },
    {
        "design_id": "DS-B03-03",
        "module": "黑板状态",
        "req_refs": REQUIRED_REQUIREMENTS,
        "contract_refs": ["event_store"],
        "test_refs": ["TC-B03-03"],
        "rule": "事件去重与幂等：重复事件只记一次，过期回调不推进状态。",
    },
    {
        "design_id": "DS-B03-04",
        "module": "黑板状态",
        "req_refs": REQUIRED_REQUIREMENTS,
        "contract_refs": ["input_snapshot"],
        "test_refs": ["TC-B03-04"],
        "rule": "派发前冻结输入快照，验收前核对快照仍有效。",
    },
    {
        "design_id": "DS-B03-05",
        "module": "黑板状态",
        "req_refs": REQUIRED_REQUIREMENTS,
        "contract_refs": ["checkpoint"],
        "test_refs": ["TC-B03-05"],
        "rule": "检查点保存计划版本、任务状态、事件编号、产物清单和租约，中断后可恢复且不重复执行。",
    },
    {
        "design_id": "DS-B03-06",
        "module": "黑板状态",
        "req_refs": REQUIRED_REQUIREMENTS,
        "contract_refs": ["lease"],
        "test_refs": ["TC-B03-06"],
        "rule": "租约与原子操作保证并发写入不覆盖，写入范围冲突时拒绝派发。",
    },
    {
        "design_id": "DS-B03-07",
        "module": "数据约束",
        "req_refs": ["LR-01", "LR-02", "LR-03", "LR-05"],
        "contract_refs": ["field_bounds"],
        "test_refs": ["TC-B03-07"],
        "rule": "C1 字段边界落地为数据层约束，非法值拒绝且不写入。",
    },
    {
        "design_id": "DS-B03-08",
        "module": "数据约束",
        "req_refs": ["LR-04"],
        "contract_refs": ["create_claim"],
        "test_refs": ["TC-B03-08"],
        "rule": "事务与唯一约束防止部分写入和重复申请。",
    },
]

S1 = {
    "spec_version": SPEC_VERSION,
    "project_id": PROJECT_ID,
    "source": SOURCE_DOC_2,
    "status": "REFERENCE_APPROVED_ASSUMED",
    "approval_note": "文档以“已取得 R1”为推演前提；本参考包不声称已完成真实六人批准。",
    "modules": [
        {
            "module": "用户与身份",
            "req_refs": ["LR-01", "LR-05"],
            "design_refs": ["DS-AUTH-01", "DS-USER-01"],
            "entities": ["User", "Session"],
        },
        {
            "module": "失物发布与搜索",
            "req_refs": ["LR-02", "LR-03"],
            "design_refs": ["DS-LOST-01", "DS-LOST-02"],
            "entities": ["LostItem"],
        },
        {
            "module": "认领申请",
            "req_refs": ["LR-04"],
            "design_refs": ["DS-CLAIM-01"],
            "entities": ["ClaimApplication"],
        },
        {
            "module": "黑板状态",
            "req_refs": REQUIRED_REQUIREMENTS,
            "design_refs": [entry["design_id"] for entry in DESIGN_ENTRIES if entry["design_id"].startswith("DS-B03")],
            "entities": ["Task", "Event", "Artifact", "Checkpoint", "Lease"],
        },
    ],
    "data_model": {
        "User": {
            "fields": ["id", "account", "password_hash", "nickname", "created_at"],
            "constraints": ["account 唯一且按小写存储", "password_hash 不得出现在公开响应"],
        },
        "LostItem": {
            "fields": ["id", "publisher_id", "name", "description", "location", "lost_at", "status", "created_at"],
            "constraints": ["publisher_id 关联 User", "lost_at 带时区且必填", "status 仅 waiting"],
        },
        "ClaimApplication": {
            "fields": ["id", "lost_item_id", "applicant_id", "statement", "status", "created_at"],
            "constraints": ["对象与申请人必须存在", "(lost_item_id, applicant_id) 唯一", "status 仅 pending"],
        },
    },
    "environment_constraints": [
        "HTTP JSON，统一前缀 /api/v1",
        "所有 id 为服务端生成的 UUID 字符串",
        "时间统一输出 UTC ISO 8601 三位毫秒",
        "演示使用虚构或脱敏数据",
    ],
    "open_questions": ["OQ-UAA"],
}

C1_OPERATIONS = [
    {"name": "register", "method": "POST", "path": "/api/v1/auth/register", "authenticated": False, "required": ["account", "password", "nickname"], "status": 201, "data": "UserView"},
    {"name": "login", "method": "POST", "path": "/api/v1/auth/login", "authenticated": False, "required": ["account", "password"], "status": 200, "data": "LoginView"},
    {"name": "logout", "method": "POST", "path": "/api/v1/auth/logout", "authenticated": True, "required": [], "status": 200, "data": "Null"},
    {"name": "get_me", "method": "GET", "path": "/api/v1/me", "authenticated": True, "required": [], "status": 200, "data": "UserView"},
    {"name": "update_me", "method": "PATCH", "path": "/api/v1/me", "authenticated": True, "required": ["nickname"], "status": 200, "data": "UserView"},
    {"name": "list_my_posts", "method": "GET", "path": "/api/v1/me/lost-items", "authenticated": True, "query": ["page", "page_size"], "status": 200, "data": "LostPage"},
    {"name": "list_my_claims", "method": "GET", "path": "/api/v1/me/claims", "authenticated": True, "query": ["page", "page_size"], "status": 200, "data": "ClaimPage"},
    {"name": "publish_lost", "method": "POST", "path": "/api/v1/lost-items", "authenticated": True, "required": ["name", "description", "location", "lost_at"], "status": 201, "data": "LostView"},
    {"name": "search_lost", "method": "GET", "path": "/api/v1/lost-items", "authenticated": False, "query": ["keyword", "location", "page", "page_size"], "status": 200, "data": "LostPage"},
    {"name": "get_lost", "method": "GET", "path": "/api/v1/lost-items/{id}", "authenticated": False, "required": [], "status": 200, "data": "LostView"},
    {"name": "create_claim", "method": "POST", "path": "/api/v1/lost-items/{id}/claims", "authenticated": True, "required": ["statement"], "status": 201, "data": "ClaimView"},
]

C1_CONTRACT = {
    "contract_version": CONTRACT_VERSION,
    "base_contract": "C1",
    "prefix": "/api/v1",
    "source": SOURCE_DOC_2,
    "owner": "B01 SpecPlannerAgent",
    "operations": C1_OPERATIONS,
    "errors": {
        "REQUIRED_FIELD": 400,
        "INVALID_FIELD": 400,
        "UNAUTHENTICATED": 401,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "DUPLICATE_ACCOUNT": 409,
        "DUPLICATE_CLAIM": 409,
        "INVALID_STATE": 409,
        "INTERNAL_ERROR": 500,
    },
    "response_envelope": {
        "success": {"ok": True, "data": "值"},
        "failure": {"ok": False, "error": {"code": "字符串", "field": "字符串或 null", "message": "字符串"}},
        "rule": "失败响应不含 data；field 在权限、凭据、对象不存在及内部错误时为 null。",
    },
    "field_bounds": {
        "account": {"min": 3, "max": 64, "pattern": "^[a-z0-9_]+$", "storage": "小写存储与查重"},
        "password": {"min": 8, "max": 128, "trim": False, "hash": "Argon2id(m=19456KiB,t=2,p=1,salt>=16B)"},
        "nickname": {"min": 1, "max": 30},
        "name": {"min": 1, "max": 80},
        "description": {"min": 1, "max": 1000},
        "location": {"min": 1, "max": 120},
        "statement": {"min": 1, "max": 500},
        "id": "服务端生成的 UUID 字符串",
        "lost_at": "ISO 8601 带时区；输出 UTC 三位毫秒",
        "pagination": {"page_default": 1, "page_size_default": 20, "page_size_range": [1, 100]},
    },
    "$defs": {
        "Uuid": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
        "Time": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"},
        "UserView": {"type": "object", "additionalProperties": False, "required": ["id", "account", "nickname", "created_at"]},
        "LostView": {"type": "object", "additionalProperties": False, "required": ["id", "name", "description", "location", "lost_at", "status", "created_at"]},
        "ClaimView": {"type": "object", "additionalProperties": False, "required": ["id", "lost_item_id", "statement", "status", "created_at"]},
        "LoginView": {"type": "object", "additionalProperties": False, "required": ["token", "expires_at", "user"]},
        "Null": {"type": "null"},
        "LostPage": {"type": "object", "additionalProperties": False, "required": ["items", "page", "page_size", "total"]},
        "ClaimPage": {"type": "object", "additionalProperties": False, "required": ["items", "page", "page_size", "total"]},
    },
}
