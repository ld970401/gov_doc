# GovDoc Agent 项目详细文档

111

## 一、项目概述

GovDoc Agent 是一个基于 FastAPI 的智慧公文处理后端服务，负责理解用户意图并调度专业 Sub Agent 完成公文相关任务（检索、写作、审核、查重、排版等）。

项目根目录：`d:\Code\gov_doc\govdoc-agent`

---

## 二、项目依赖

**配置文件**: [requirements.txt](file:///d:/Code/gov_doc/govdoc-agent/requirements.txt)

| 依赖库           | 版本    | 用途          |
| ---------------- | ------- | ------------- |
| fastapi          | 0.115.0 | Web 框架      |
| uvicorn          | 0.30.6  | ASGI 服务器   |
| sqlalchemy       | 2.0.49  | ORM（数据库） |
| requests         | 2.32.3  | HTTP 客户端   |
| python-multipart | 0.0.12  | 文件上传解析  |
| python-dotenv    | 1.0.1   | 环境变量加载  |
| python-docx      | 1.1.2   | DOCX 文件解析 |
| pdfplumber       | 0.11.4  | PDF 文件解析  |

---

## 三、架构总览

```
govdoc-agent/
├── app/                          # 核心应用模块
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # 配置管理（从 model.json 读取 LLM 配置）
│   ├── db.py                     # SQLAlchemy 数据库初始化
│   ├── models.py                 # 数据库表模型定义
│   ├── schemas.py                # Pydantic 请求/响应模型
│   ├── auth.py                   # 鉴权模块（Legacy/Cookie/Mock）
│   ├── auth_schemas.py           # 鉴权相关数据模型
│   ├── llm.py                    # LLM 调用封装
│   ├── planner.py                # 执行计划构建（调用 MainAgent）
│   ├── runtime.py                # 核心运行时（Agentic Loop）
│   ├── a2a_runtime.py            # A2A 任务注册与执行计划
│   ├── agent_capability_adapter.py  # Skill 执行适配器
│   ├── compression.py            # 上下文压缩与摘要
│   ├── storage.py                # 文件系统存储抽象
│   ├── file_parser.py            # 文件解析（docx/pdf/txt）
│   ├── debug_log.py              # 调试日志
│   ├── skills.py                 # 向后兼容导出
│   ├── model_catalog.py          # 模型目录与可用模型
│   ├── routes/                   # API 路由
│   │   ├── conversations.py      # 会话 CRUD + SSE 事件流
│   │   ├── workspace.py          # 工作区（云盘）API
│   │   ├── settings.py           # 用户设置/记忆/词库
│   │   ├── models.py             # 可用模型列表
│   │   ├── me.py                 # 当前用户/健康检查
│   │   └── skills.py             # Skill 相关
│   └── __pycache__/
├── agents/                       # Agent 核心模块
│   ├── base_agent.py             # BaseAgent 基类
│   ├── main_agent.py             # MainAgent（主 Agent，负责规划调度）
│   ├── registry.py               # AgentRegistry（注册/管理 sub agents）
│   ├── sub/                      # Sub Agent 实现
│   │   ├── __init__.py           # 注册 5 个内置 Sub Agent
│   │   ├── writing_agent.py       # 写作 Agent
│   │   ├── retrieval_agent.py     # 检索 Agent
│   │   ├── review_agent.py        # 审核 Agent
│   │   ├── dedup_agent.py         # 查重 Agent
│   │   └── layout_agent.py        # 排版 Agent
│   └── __pycache__/
├── tools/
│   ├── agent_tool.py             # dispatch_sub_agent 工具定义
│   └── __init__.py
├── prompts/                      # 系统提示词
│   ├── main_system.md            # 主 Agent 系统提示
│   └── sub/                      # Sub Agent 提示词
│       ├── general.md            # 主 Agent 直接回复场景
│       ├── writing.md            # 写作
│       ├── retrieval.md          # 检索
│       ├── review.md             # 审核
│       ├── dedup.md              # 查重
│       └── layout.md             # 排版
├── config/
│   └── model.json                # LLM 配置（base_url/api_key/模型列表）
├── tests/
│   └── test_agentic_loop.py
├── runtime_logs/                 # 运行时日志
└── manage_govdoc_agent.sh        # 一键启停脚本
```

---

## 四、核心模块详解

### 4.1 应用入口 [main.py](file:///d:/Code/gov_doc/govdoc-agent/app/main.py)

```python
app = FastAPI(title="govdoc-agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)              # /api/agentloop
app.include_router(conversations.router)   # /api/agentloop/conversations
app.include_router(workspace.router)       # /api/agentloop/workspace
app.include_router(settings.router)        # /api/agentloop/settings
app.include_router(skills.router)          # /api/agentloop/skills
app.include_router(model_routes.router)    # /api/agentloop/models
```

**关键中间件**: CORS（跨域资源共享）

---

### 4.2 配置管理 [config.py](file:///d:/Code/gov_doc/govdoc-agent/app/config.py)

`Settings` 类从以下优先级加载配置：

1. 项目根目录 `.env` 文件（通过 `python-dotenv` 加载）
2. `config/model.json` 的 `llm` 段（仅限 LLM 相关配置）

**关键配置项**:

| 配置项                     | 来源       | 说明                                  |
| -------------------------- | ---------- | ------------------------------------- |
| `llm_base_url`             | model.json | LLM 网关地址                          |
| `llm_chat_completions_url` | model.json | 完整 chat completions URL（优先使用） |
| `llm_api_key`              | model.json | API Key                               |
| `llm_default_model`        | model.json | 默认模型                              |
| `llm_timeout_seconds`      | model.json | 超时时间（默认90秒）                  |
| `enable_model_planner`     | model.json | 是否启用 Planner（默认 true）         |
| `planner_model`            | model.json | Planner 模型                          |
| `planner_temperature`      | model.json | Planner 温度（默认 0.1）              |
| `database_url`             | 环境变量   | SQLite 数据库路径                     |
| `cors_origins`             | 环境变量   | 允许的跨域来源                        |
| `debug_runtime_logs`       | 环境变量   | 是否开启详细日志                      |

---

### 4.3 数据库 [db.py](file:///d:/Code/gov_doc/govdoc-agent/app/db.py) + [models.py](file:///d:/Code/gov_doc/govdoc-agent/app/models.py)

**数据库**: SQLite（默认路径：`govdoc_agent.db`），使用 WAL 模式

**数据库表结构**:

| 表名                       | 说明                | 关键字段                                                                       |
| -------------------------- | ------------------- | ------------------------------------------------------------------------------ |
| `v4_conversation`          | 对话会话            | id, user_id, title, pinned, is_deleted, running_context_json                   |
| `v4_conversation_message`  | 对话消息            | id, conversation_id, role, skill_name, content, content_html, annotations_json |
| `v4_conversation_run`      | 对话运行记录        | id, conversation_id, task_id, objective, status                                |
| `v4_task_event`            | 任务事件（SSE推送） | id, run_id, event_type, status, title, payload_json                            |
| `v4_conversation_artifact` | 会话产物            | id, artifact_type, title, content_html, workspace_node_id                      |
| `v4_workspace_node`        | 工作区节点（云盘）  | id, node_type, name, owner_user_id                                             |
| `v4_workspace_version`     | 文档版本            | id, node_id, version_no, content_html                                          |
| `v4_compression_snapshot`  | 压缩快照            | id, summary_markdown, stats_json                                               |
| `v4_user_profile`          | 用户画像            | user_id, default_model, memory_json, identify_md_path                          |
| `v4_dictionary_entry`      | 词库条目            | user_id, dict_type, word                                                       |
| `v4_template_item`         | 模板文件            | user_id, title, document_type, relative_path                                   |

---

### 4.4 鉴权 [auth.py](file:///d:/Code/gov_doc/govdoc-agent/app/auth.py)

**鉴权优先级**（`get_current_user` 函数）：

1. **Header 优先**: `X-Legacy-User-Id` + `X-Legacy-Account` + `X-Legacy-Name` 同时存在
2. **Cookie 鉴权**: 请求旧系统 `/report-agent/v3/auth/me`
3. **开发 Mock**: `ENABLE_DEV_AUTH_MOCK=true` 时返回固定测试用户

**Mock 用户默认**:

- user_id: `66666666666666666666666666666666`
- account: `liwenjing`
- name: `李文静`
- org_name: `党组秘书处`

---

### 4.5 Agent 核心 [agents/](file:///d:/Code/gov_doc/govdoc-agent/agents/)

#### 4.5.1 AgentRegistry [registry.py](file:///d:/Code/gov_doc/govdoc-agent/agents/registry.py)

`AgentRegistry` 是 Sub Agent 的注册中心，管理以下内置 Agent：

| Agent 名称  | 显示名        | 职责                         |
| ----------- | ------------- | ---------------------------- |
| `general`   | 主 Agent 对话 | 直接回复用户、调度 sub agent |
| `retrieval` | 检索          | 知识库/法规/历史公文检索     |
| `writing`   | 写作          | 公文起草/续写/改写           |
| `review`    | 审核          | 合规性/语义/措辞审核         |
| `dedup`     | 查重          | 相似度检测与重复标注         |
| `layout`    | 排版          | 党政机关公文格式排版         |

**关键函数**:

```python
AgentRegistry.register(agent_def)           # 注册 Agent
AgentRegistry.get(name)                    # 获取 Agent 定义
AgentRegistry.list_selectable()            # 获取可选 Agent 列表
system_prompt_for_agent(name)              # 获取 Agent 系统提示
canonical_agent_name(name)                  # 规范化 Agent 名称（支持别名）
```

#### 4.5.2 BaseAgent [base_agent.py](file:///d:/Code/gov_doc/govdoc-agent/agents/base_agent.py)

```python
class BaseAgent:
    definition: AgentDefinition

    def build_system_prompt(self, context: dict | None = None) -> str:
        # 拼接系统提示 + 当前上下文（doc_content/doc_type/user_intent）
```

#### 4.5.3 MainAgent [main_agent.py](file:///d:/Code/gov_doc/govdoc-agent/agents/main_agent.py)

主 Agent 是整个系统的调度核心，负责：

1. **`plan()` 方法**:
   - 构建 Planner 消息
   - 调用 LLM 生成执行计划
   - 解析 tool_calls 生成 `ExecutionPlan`
   - 失败时降级到 `build_fallback_execution_plan`

2. **`leader_step()` 方法**:
   - Leader 闭环：在完整 messages（含 tool 结果）上再调 Planner 模型决策下一步

3. **Planner 响应处理**:
   - 若返回 `dispatch_sub_agent` tool calls：生成 `ExecutionPlan` 分发 sub agent
   - 若直接回复：返回 `direct_answer` 类型的 plan

---

### 4.6 A2A 运行时 [a2a_runtime.py](file:///d:/Code/gov_doc/govdoc-agent/app/a2a_runtime.py)

```python
@dataclass
class ExecutionStep:
    index: int                           # 执行顺序
    skill_name: str                     # 调用的 skill
    title: str                          # 步骤标题
    objective: str                      # 任务目标
    scope: str                          # 任务范围
    depends_on: list[str]               # 依赖的前置步骤 ID
    subtask_role: str = "skill_worker"  # 角色

@dataclass
class ExecutionPlan:
    intent: str                         # 意图类型
    summary: str                        # 执行计划摘要
    steps: list[ExecutionStep]         # 执行步骤列表
    requires_user_input: bool = False   # 是否需要用户输入
    clarification_question: str | None = None
```

**A2ATaskRegistry**: 管理任务注册、状态更新、消息记录

---

### 4.7 LLM 调用 [llm.py](file:///d:/Code/gov_doc/govdoc-agent/app/llm.py)

**关键函数**:

```python
resolve_model_name(requested_model)     # 解析模型名称（支持别名）
chat_completions_post_url()              # 获取完整 POST URL
build_messages(content, skill, ...)     # 构建消息列表
call_chat_model_with_messages_raw(...)  # 核心调用（支持流式）
extract_json_object(text)                # 从响应中提取 JSON
text_to_html(text)                       # 文本转 HTML
```

**流式处理**:

- 支持 SSE 流式响应
- 合并断断续续的 tool_call chunks
- 自动修复编码问题（ISO-8859-1 → UTF-8）

**模型别名映射**:

```python
MODEL_ALIASES = {
    "minimax": <default_model>,
    "qwen 3.5": <default_model>,
    "qwen3-max": <default_model>,
    "deepseek": <default_model>,
}
```

---

### 4.8 Skill 执行适配器 [agent_capability_adapter.py](file:///d:/Code/gov_doc/govdoc-agent/app/agent_capability_adapter.py)

```python
@dataclass
class SkillExecutionResult:
    normalized_result: dict             # 标准化结果
    render_blocks: list[dict]           # 渲染块
    artifact_refs: list[dict]           # 产物引用
    editor_annotations: list[dict]      # 编辑器批注
    retryable: bool                     # 是否可重试
    source_state: str = "model_success"
    error_detail: str | None = None
    prompt_menu: dict | None = None     # 提示菜单
    reasoning_content: str | None = None
```

**执行流程**:

1. 调用 LLM 生成结果
2. 尝试调用旧系统 API（`_try_legacy_json` / `_try_legacy_stream`）
3. 渲染 HTML 输出
4. 返回 `SkillExecutionResult`

---

### 4.9 工具定义 [tools/agent_tool.py](file:///d:/Code/gov_doc/govdoc-agent/tools/agent_tool.py)

`dispatch_sub_agent` 工具 schema:

```python
{
    "type": "function",
    "function": {
        "name": "dispatch_sub_agent",
        "description": "调度指定的 Sub Agent 执行子任务",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "enum": [<所有注册agent>]},
                "task_prompt": {"type": "string", "description": "子任务描述"},
                "context": {
                    "type": "object",
                    "properties": {
                        "doc_content": {"type": "string"},
                        "doc_type": {"type": "string"},
                        "user_intent": {"type": "string"}
                    }
                },
                "run_in_background": {"type": "boolean", "default": False}
            },
            "required": ["agent_name", "task_prompt"]
        }
    }
}
```

---

### 4.10 上下文压缩 [compression.py](file:///d:/Code/gov_doc/govdoc-agent/app/compression.py)

**Token 估算**: 约 4 字符/token（中英混合）

**压缩策略**:

1. **去重行**: `dedupe_lines()` - 去除完全相同的行
2. **行截断**: `truncate_line()` - 超过 `max_line_chars` 的行截断
3. **选择性保留**: 保留摘要、pending work、tool 结果
4. **Tool 结果截断**: `truncate_tool_results()` - 超过 4000 字符的工具结果截断
5. **最老 exchange 修剪**: `prune_oldest_tool_exchange()` - 保留最近 6 对 tool exchange

---

### 4.11 存储抽象 [storage.py](file:///d:/Code/gov_doc/govdoc-agent/app/storage.py)

**目录结构**:

```
{workspace_root}/{user_id}/
├── workspace/
│   └── {node_id}/
│       └── v{version_no:04d}/
│           ├── title.txt
│           ├── content.html
│           ├── content.txt
│           └── annotations.json
├── memory/
│   ├── identify.md
│   ├── memory.md
│   ├── session_summary.md
│   ├── topics/
│   │   ├── habits.md
│   │   ├── skill_preferences.md
│   │   ├── style_preferences.md
│   │   ├── recent_focus.md
│   │   └── common_feedback.md
│   └── sessions/
│       └── {session_id}.md
└── templates/
```

---

## 五、API 路由详解

### 5.1 会话路由 [routes/conversations.py](file:///d:/Code/gov_doc/govdoc-agent/app/routes/conversations.py)

| 方法   | 路径                                       | 功能                                 |
| ------ | ------------------------------------------ | ------------------------------------ |
| GET    | `/api/agentloop/conversations`             | 列出用户所有会话                     |
| POST   | `/api/agentloop/conversations`             | 创建新会话                           |
| GET    | `/api/agentloop/conversations/{id}`        | 获取会话详情（含消息/产物/压缩快照） |
| PUT    | `/api/agentloop/conversations/{id}`        | 重命名/置顶会话                      |
| DELETE | `/api/agentloop/conversations/{id}`        | 删除会话                             |
| POST   | `/api/agentloop/conversations/{id}/run`    | 运行会话（后台任务）                 |
| GET    | `/api/agentloop/conversations/{id}/events` | SSE 事件流                           |

### 5.2 工作区路由 [routes/workspace.py](file:///d:/Code/gov_doc/govdoc-agent/app/routes/workspace.py)

| 方法 | 路径                                                       | 功能                                       |
| ---- | ---------------------------------------------------------- | ------------------------------------------ |
| GET  | `/api/agentloop/workspace`                                 | 列出工作区文档（支持 view=recent/mine/ai） |
| GET  | `/api/agentloop/workspace/tree`                            | 获取目录树                                 |
| POST | `/api/agentloop/workspace/folders`                         | 创建文件夹                                 |
| POST | `/api/agentloop/workspace/documents`                       | 创建文档                                   |
| PUT  | `/api/agentloop/workspace/nodes/{id}`                      | 更新文档                                   |
| POST | `/api/agentloop/workspace/nodes/{id}/upload`               | 上传新版本                                 |
| POST | `/api/agentloop/workspace/nodes/{id}/send-to-conversation` | 发送到会话                                 |

### 5.3 设置路由 [routes/settings.py](file:///d:/Code/gov_doc/govdoc-agent/app/routes/settings.py)

| 方法 | 路径                                   | 功能         |
| ---- | -------------------------------------- | ------------ |
| GET  | `/api/agentloop/settings/profile`      | 获取用户资料 |
| PUT  | `/api/agentloop/settings/profile`      | 更新用户资料 |
| GET  | `/api/agentloop/settings/memory`       | 获取记忆     |
| PUT  | `/api/agentloop/settings/memory`       | 更新记忆     |
| GET  | `/api/agentloop/settings/dictionaries` | 获取词库     |
| POST | `/api/agentloop/settings/dictionaries` | 添加词条     |
| GET  | `/api/agentloop/settings/templates`    | 获取模板列表 |
| POST | `/api/agentloop/settings/templates`    | 上传模板     |

### 5.4 用户/健康检查 [routes/me.py](file:///d:/Code/gov_doc/govdoc-agent/app/routes/me.py)

| 方法 | 路径                    | 功能             |
| ---- | ----------------------- | ---------------- |
| GET  | `/api/agentloop/health` | 健康检查（匿名） |
| GET  | `/api/agentloop/me`     | 获取当前用户信息 |

---

## 六、中间件及其使用

### 6.1 CORS 中间件

**配置位置**: [main.py](file:///d:/Code/gov_doc/govdoc-agent/app/main.py#L19-L24)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # 从环境变量读取
    allow_credentials=True,                # 允许携带 Cookie
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**默认允许的来源**:

```
http://127.0.0.1:4173, http://localhost:4173,
http://127.0.0.1:5173, http://localhost:5173,
http://127.0.0.1:3000, http://localhost:3000
```

---

## 七、Agentic Loop 执行流程

```
用户输入
    ↓
MainAgent.plan()                    # 规划阶段
    ├── 启用 Planner → 调用 LLM → 解析 tool_calls → 生成 ExecutionPlan
    └── 禁用 Planner → build_fallback_execution_plan
    ↓
ExecutionPlan.steps                  # 执行步骤列表
    ↓
遍历每个 ExecutionStep
    ↓
AgentTool.call(agent_name, task_prompt, ...)
    ↓
execute_skill()                      # Skill 执行适配器
    ├── _invoke_llm()               # 调用 LLM
    ├── _try_legacy_json/stream()  # 尝试旧系统 API
    └── 返回 SkillExecutionResult
    ↓
生成 V4TaskEvent（running/completed/failed）
    ↓
SSE 推送事件到前端
    ↓
所有步骤完成 → 生成最终响应
```

---

## 八、关键函数索引

| 模块                        | 函数                                  | 功能                     |
| --------------------------- | ------------------------------------- | ------------------------ |
| config.py                   | `Settings` 类                         | 配置管理                 |
| db.py                       | `get_db()`                            | 数据库会话依赖           |
| auth.py                     | `get_current_user()`                  | 鉴权与当前用户解析       |
| agents/registry.py          | `AgentRegistry.register()`            | 注册 Sub Agent           |
| agents/registry.py          | `system_prompt_for_agent()`           | 获取 Agent 系统提示      |
| agents/main_agent.py        | `MainAgent.plan()`                    | 规划执行计划             |
| agents/main_agent.py        | `MainAgent.leader_step()`             | Leader 闭环决策          |
| a2a_runtime.py              | `build_execution_plan()`              | 构建执行计划             |
| a2a_runtime.py              | `A2ATaskRegistry`                     | 任务注册管理             |
| llm.py                      | `call_chat_model_with_messages_raw()` | LLM 调用核心             |
| llm.py                      | `resolve_model_name()`                | 模型名称解析             |
| agent_capability_adapter.py | `execute_skill()`                     | Skill 执行入口           |
| agent_capability_adapter.py | `_invoke_llm()`                       | LLM 调用封装             |
| tools/agent_tool.py         | `AgentTool.get_tool_schema()`         | 获取工具 schema          |
| tools/agent_tool.py         | `AgentTool.call()`                    | 调用工具执行             |
| runtime.py                  | `prepare_run_conversation()`          | 准备运行会话             |
| runtime.py                  | `execute_prepared_run()`              | 执行准备好的运行         |
| compression.py              | `compress_summary_text()`             | 压缩摘要文本             |
| compression.py              | `estimate_tokens()`                   | Token 数量估算           |
| compression.py              | `prune_oldest_tool_exchange()`        | 修剪最老的 tool exchange |
| storage.py                  | `write_workspace_version()`           | 写入工作区版本           |
| storage.py                  | `read_user_doc()`                     | 读取用户文档             |
| file_parser.py              | `parse_uploaded_file()`               | 解析上传文件             |
| debug_log.py                | `log_stage()`                         | 调试日志记录             |
| model_catalog.py            | `effective_auth_models()`             | 获取有效模型列表         |
| planner.py                  | `build_model_execution_plan()`        | 构建模型执行计划         |

---

## 九、启动方式

```bash
# 进入目录
cd govdoc-agent

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn app.main:app --reload --port 8000

# 或使用管理脚本
chmod +x manage_govdoc_agent.sh
./manage_govdoc_agent.sh start    # 启动
./manage_govdoc_agent.sh dev      # 开发模式（前台）
./manage_govdoc_agent.sh status  # 查看状态
./manage_govdoc_agent.sh logs    # 查看日志
./manage_govdoc_agent.sh stop    # 停止
```

---

## 十、模型配置示例

**配置文件**: [config/model.json](file:///d:/Code/gov_doc/govdoc-agent/config/model.json)

```json
{
  "llm": {
    "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "chat_completions_url": "",
    "api_key": "<your-api-key>",
    "default_model": "MiniMax-M2.5",
    "available_models": [
      { "id": "MiniMax-M2.5", "label": "MiniMax M2.5" },
      { "id": "qwen3.5-397b-a17b", "label": "通义 Qwen3.5 397B" }
    ],
    "timeout_seconds": 90,
    "enable_planner": true,
    "planner_model": "",
    "planner_temperature": 0.1,
    "planner_max_steps": 5
  }
}
```
