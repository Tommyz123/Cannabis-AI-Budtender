# TODOLIST — AI Budtender 开发任务清单

**基于：** PROJECT_PLAN_v1.md (92/100)
**生成时间：** 2026-03-05
**总进度：** 100% ✅ — 2026-03-06 全部完成

---

## 进度追踪

| Task | 模块 | 状态 | 进度 |
|------|------|------|------|
| Task 1 | 项目初始化与配置 | ✅ 完成 | 100% |
| Task 2 | 产品数据管理模块 | ✅ 完成 | 100% |
| Task 3 | LLM 集成模块 | ✅ 完成 | 100% |
| Task 4 | API 路由层 | ✅ 完成 | 100% |
| Task 5 | 前端 Chat Widget | ✅ 完成 | 100% |
| Task 6 | 集成测试与端到端验证 | ✅ 完成 | 100% |

**总进度：100%** ✅

---

## 任务依赖关系

```
Task 1 (项目初始化)
  │
  ├──► Task 2 (产品数据管理)
  │       │
  │       ├──► Task 3 (LLM 集成)
  │       │       │
  │       │       └──► Task 4 (API 路由层)
  │       │               │
  │       │               └──► Task 5 (前端 Widget)
  │       │                       │
  │       └───────────────────────┘
  │                                 │
  └─────────────────────────────────► Task 6 (集成测试)
```

依赖说明：
- Task 1 无依赖，最先执行
- Task 2 依赖 Task 1（需要项目结构和配置）
- Task 3 依赖 Task 2（需要产品数据模块提供 compact JSON）
- Task 4 依赖 Task 2 + Task 3（需要产品管理和 LLM 服务）
- Task 5 依赖 Task 4（需要后端 API 端点可用）
- Task 6 依赖 Task 4 + Task 5（需要前后端均完成）

---

## 任务详情

---

### Task 1：项目初始化与配置管理

**前置条件：** 无

**功能要求：**
1. 创建项目目录结构（backend/、frontend/、data/、tests/）
2. 创建 backend/config.py 集中管理所有配置项（OPENAI_API_KEY、CSV_PATH、MAX_HISTORY_MESSAGES=20、BEGINNER_THC_LIMITS、MODEL_NAME）
3. 创建 backend/models.py 定义 Pydantic 请求/响应模型（ChatRequest、ChatResponse）
4. 创建 requirements.txt 列出所有 Python 依赖（fastapi、uvicorn、pandas、openai、python-dotenv、pytest、pytest-asyncio、httpx、pylint、bandit）
5. 创建 .env.example 环境变量模板和 .gitignore 文件

**实现位置：**
- 文件: backend/config.py, backend/models.py, requirements.txt, .env.example, .gitignore
- 测试: tests/test_config.py

**代码审核：**
```bash
pylint backend/config.py backend/models.py
bandit -r backend/
```

**测试验证：**
```bash
pytest tests/test_config.py -v
```
测试用例：
- test_config_defaults — 验证默认配置值正确
- test_config_env_override — 验证环境变量可覆盖配置
- test_chat_request_model — 验证 ChatRequest 模型字段和校验
- test_chat_response_model — 验证 ChatResponse 模型字段

**验收标准：**
- [ ] 目录结构按 PROJECT_PLAN 第 8 节创建
- [ ] config.py 包含所有 5 个配置项且从环境变量读取
- [ ] models.py 定义 ChatRequest 和 ChatResponse 模型
- [ ] requirements.txt 包含所有必要依赖
- [ ] .env.example 包含 OPENAI_API_KEY 占位
- [ ] 代码审核通过（pylint + bandit）
- [ ] 测试通过

**完成后必须执行：**
1. 确认代码审核通过
2. 确认测试通过
3. 更新进度
4. 检查 Task 2 前置条件（Task 1 完成）

---

### Task 2：产品数据管理模块

**前置条件：** Task 1 完成

**功能要求：**
1. 实现 CSV 加载功能：使用 pandas read_csv 加载 NYE4.0_v3.csv，解析所有字段（Strain、Company、Categories、THCLevel、THCUnit、Price 等 20+ 字段）
2. 实现品类索引：按 Categories 字段建立 Dict[str, DataFrame] 索引，支持快速品类过滤
3. 实现 compact JSON 生成：将产品数据转为缩写 key 格式（id/s/c/cat/sub/t/thc/p/pr/f/sc/tod/xl/cm/on/dur），可选字段 flv/hw 非空时包含
4. 实现新手安全过滤：排除 Concentrates 品类、限制 ExperienceLevel 为 Beginner/All Levels、Edibles THC≤5mg、Flower/Pre-rolls THC≤20%、Vaporizers THC≤70%
5. 实现降级策略：过滤后 <3 条时，第一级扩展经验等级到 Intermediate，第二级完全放开经验等级（保留 THC 上限和排除浓缩品）

**实现位置：**
- 文件: backend/product_manager.py
- 测试: tests/test_product_manager.py

**代码审核：**
```bash
pylint backend/product_manager.py
bandit -r backend/product_manager.py
```

**测试验证：**
```bash
pytest tests/test_product_manager.py -v
```
测试用例：
- test_load_products — 验证 CSV 加载正确解析所有字段和行数
- test_category_index — 验证品类索引包含所有品类
- test_compact_json_format — 验证 compact JSON 包含必需的 14 个核心字段
- test_compact_json_optional_fields — 验证可选字段 flv/hw 在非空时包含
- test_beginner_filter_excludes_concentrates — 验证排除浓缩品
- test_beginner_filter_thc_edibles — 验证 Edibles THC≤5mg
- test_beginner_filter_thc_flower — 验证 Flower/Pre-rolls THC≤20%
- test_beginner_filter_thc_vaporizers — 验证 Vaporizers THC≤70%
- test_beginner_filter_experience_level — 验证经验等级过滤
- test_fallback_level1 — 验证第一级降级扩展到 Intermediate
- test_fallback_level2 — 验证第二级降级完全放开经验等级

**验收标准：**
- [ ] CSV 加载后产品数量为 217 条（或与实际 CSV 一致）
- [ ] 品类索引覆盖 CSV 中所有 Categories 值
- [ ] compact JSON 格式与 PRD 第 11 节一致
- [ ] 新手过滤排除所有 Concentrates 品类产品
- [ ] 新手过滤后 Edibles 产品 THCLevel 均 ≤5
- [ ] 新手过滤后 Flower/Pre-rolls 产品 THCLevel 均 ≤20
- [ ] 新手过滤后 Vaporizers 产品 THCLevel 均 ≤70
- [ ] 降级策略在产品不足 3 条时正确触发
- [ ] 代码审核通过
- [ ] 所有 11 个测试通过

**完成后必须执行：**
1. 确认代码审核通过
2. 确认测试通过
3. 更新进度
4. 检查 Task 3 前置条件（Task 2 完成）

---

### Task 3：LLM 集成模块

**前置条件：** Task 2 完成

**功能要求：**
1. 实现 System Prompt 构建：按 PRD 第 10 节完整构建 system prompt，包含角色定义、11 条规则、数据格式说明、语义映射示例
2. 实现消息列表构建：组装 system prompt + 对话历史 + 产品 compact JSON 为 OpenAI API 所需的 messages 格式
3. 实现 OpenAI API 调用：使用 openai SDK 调用 gpt-4o-mini，传入构建好的 messages，返回 AI 回复文本
4. 实现错误处理：处理 API 超时、rate limit、无效响应等异常情况

**实现位置：**
- 文件: backend/llm_service.py
- 测试: tests/test_llm_service.py

**代码审核：**
```bash
pylint backend/llm_service.py
bandit -r backend/llm_service.py
```

**测试验证：**
```bash
pytest tests/test_llm_service.py -v
```
测试用例：
- test_build_system_prompt — 验证 system prompt 包含角色定义和所有 11 条规则
- test_build_system_prompt_contains_mappings — 验证 system prompt 包含语义映射示例
- test_build_messages — 验证消息列表结构（system + history + user）
- test_build_messages_with_products — 验证产品 JSON 正确嵌入消息
- test_get_recommendation_success — 验证 API 调用成功返回回复（mock OpenAI）
- test_get_recommendation_error — 验证 API 异常时的错误处理（mock OpenAI）

**验收标准：**
- [ ] System prompt 完整包含 PRD 第 10 节的全部内容
- [ ] 消息列表格式符合 OpenAI API 要求（role + content）
- [ ] API 调用使用 gpt-4o-mini 模型
- [ ] API 异常（超时、rate limit）有合理的错误处理
- [ ] 代码审核通过
- [ ] 所有 6 个测试通过

**完成后必须执行：**
1. 确认代码审核通过
2. 确认测试通过
3. 更新进度
4. 检查 Task 4 前置条件（Task 2 + Task 3 完成）

---

### Task 4：API 路由层

**前置条件：** Task 2 + Task 3 完成

**功能要求：**
1. 实现 FastAPI 应用入口：创建 FastAPI app 实例，配置 CORS 中间件（允许所有源，支持 iframe 嵌入）
2. 实现 POST /chat 端点：接收 ChatRequest（session_id + messages + is_beginner + user_message），根据 is_beginner 调用产品管理模块获取对应产品集，调用 LLM 模块生成回复，返回 ChatResponse
3. 实现 GET /health 端点：返回服务状态和已加载产品数量
4. 实现应用启动事件：在 startup 事件中加载 CSV 数据并初始化产品索引

**实现位置：**
- 文件: backend/main.py
- 测试: tests/test_api.py

**代码审核：**
```bash
pylint backend/main.py
bandit -r backend/main.py
```

**测试验证：**
```bash
pytest tests/test_api.py -v
```
测试用例：
- test_health_endpoint — 验证 GET /health 返回 ok 和产品数量
- test_chat_endpoint_normal — 验证 POST /chat 非新手请求返回正确响应
- test_chat_endpoint_beginner — 验证 POST /chat 新手请求触发安全过滤
- test_chat_endpoint_invalid_request — 验证无效请求返回 400
- test_chat_endpoint_with_history — 验证带历史消息的请求正确处理
- test_cors_headers — 验证 CORS 头正确设置

**验收标准：**
- [ ] FastAPI 应用可通过 uvicorn 正常启动
- [ ] POST /chat 正确区分新手/非新手路径
- [ ] POST /chat 将正确的产品集传给 LLM
- [ ] GET /health 返回正确的状态和产品数
- [ ] CORS 配置允许跨域请求
- [ ] 启动时自动加载 CSV 数据
- [ ] 代码审核通过
- [ ] 所有 6 个测试通过

**完成后必须执行：**
1. 确认代码审核通过
2. 确认测试通过
3. 更新进度
4. 检查 Task 5 前置条件（Task 4 完成）

---

### Task 5：前端 Chat Widget

**前置条件：** Task 4 完成

**功能要求：**
1. 实现对话界面：创建 HTML/CSS 聊天 Widget（悬浮按钮 + 展开式对话框），包含消息气泡（用户/AI 区分样式）、输入框、发送按钮
2. 实现会话管理：生成 UUID session_id（页面刷新后重新生成），维护对话历史数组，超过 20 条消息时丢弃最旧的消息对
3. 实现 API 通信：通过 fetch 调用 POST /chat，发送 session_id + messages + is_beginner + user_message，处理响应并展示
4. 实现 is_beginner 标志追踪：解析 AI 回复中的 `<!-- beginner:true -->` 标记，更新 is_beginner 状态（初始 false），从显示文本中移除隐藏标记
5. 实现 UI 交互细节：发送中禁用输入、加载动画、自动滚动到最新消息、Enter 键发送

**实现位置：**
- 文件: frontend/index.html, frontend/style.css, frontend/chat.js
- 测试: 手动测试（浏览器）

**代码审核：**
```bash
# 前端无 pylint，检查 JS 基本规范
cat frontend/chat.js | head -5  # 确认无硬编码 API key
```

**测试验证：**
手动测试步骤：
1. 打开 index.html，确认悬浮按钮显示
2. 点击按钮展开对话框
3. 发送消息，确认显示用户气泡和 AI 回复气泡
4. 验证 session_id 在刷新后重新生成
5. 模拟新手对话，确认 is_beginner 标志更新

测试用例：
- test_widget_renders — 确认 Widget 在浏览器中正常渲染
- test_message_send_receive — 确认消息发送和接收流程
- test_beginner_tag_parsing — 确认 `<!-- beginner:true -->` 标记被正确解析和移除
- test_history_trim — 确认超过 20 条消息时正确裁剪
- test_session_id_regeneration — 确认刷新后生成新 session_id

**验收标准：**
- [ ] Widget 以悬浮按钮形式展示，点击可展开对话框
- [ ] 用户消息和 AI 回复使用不同样式气泡
- [ ] 消息发送时有加载状态指示
- [ ] session_id 为 UUID 格式，刷新后重新生成
- [ ] 对话历史超过 20 条时自动裁剪最旧消息对
- [ ] `<!-- beginner:true -->` 标记被正确解析且不显示在界面
- [ ] Enter 键可发送消息，发送中禁用输入框
- [ ] 新消息出现时自动滚动到底部

**完成后必须执行：**
1. 确认手动测试全部通过
2. 更新进度
3. 检查 Task 6 前置条件（Task 4 + Task 5 完成）

---

### Task 6：集成测试与端到端验证

**前置条件：** Task 4 + Task 5 完成

**功能要求：**
1. 编写集成测试：测试完整的请求链路（前端请求 → 后端处理 → LLM 调用 → 响应返回），使用 mock OpenAI API
2. 验证 7 种对话路径：模拟路径 A-G 的典型开场语，验证 LLM 收到正确的产品集和 prompt
3. 验证新手安全规则端到端：模拟新手对话流程，确认 is_beginner=true 时后端只传安全产品
4. 创建 conftest.py：定义共享 fixtures（测试用 FastAPI 客户端、mock 产品数据、mock OpenAI 响应）

**实现位置：**
- 文件: tests/test_api.py（扩展）, tests/conftest.py
- 测试: tests/

**代码审核：**
```bash
pylint backend/
bandit -r backend/
```

**测试验证：**
```bash
pytest tests/ -v --cov=backend --cov-report=term-missing
```
测试用例：
- test_full_chat_flow_normal — 完整非新手对话流程
- test_full_chat_flow_beginner — 完整新手对话流程（安全过滤验证）
- test_path_a_unclear — 路径A（需求不明确）产品传递验证
- test_path_d_beginner — 路径D（初次尝试）安全规则验证
- test_path_e_price — 路径E（价格优先）产品传递验证
- test_history_limit — 验证超过20条消息时的处理

**验收标准：**
- [ ] 所有集成测试通过
- [ ] 新手路径不包含任何 Concentrates 产品
- [ ] 新手路径所有产品 THC 在安全范围内
- [ ] 后端代码测试覆盖率 ≥ 80%
- [ ] pylint 评分 ≥ 8.0
- [ ] bandit 无高危问题
- [ ] 前端 Widget 可正常与后端通信

**完成后必须执行：**
1. 确认代码审核通过
2. 确认所有测试通过
3. 确认测试覆盖率 ≥ 80%
4. 更新进度为 100%

---

## 首次执行指令

```bash
# 1. 创建项目目录结构
mkdir -p backend frontend data tests

# 2. 将产品数据文件放入 data/ 目录
cp NYE4.0_v3.csv data/

# 3. 创建 Python 虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 4. 安装依赖（Task 1 完成后）
pip install -r requirements.txt

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY

# 6. 开始 Task 1
```

---

## 工具说明

| 工具 | 用途 | 安装 |
|------|------|------|
| Python 3.10+ | 后端运行环境 | 系统安装 |
| pip | 包管理 | Python 自带 |
| pytest | 测试框架 | `pip install pytest` |
| pytest-asyncio | 异步测试支持 | `pip install pytest-asyncio` |
| httpx | 异步 HTTP 客户端 / API 测试 | `pip install httpx` |
| pylint | 代码质量检查 | `pip install pylint` |
| bandit | 安全漏洞扫描 | `pip install bandit` |
| uvicorn | ASGI 服务器 | `pip install uvicorn` |

---

## 注意事项

1. **OPENAI_API_KEY 安全**：绝不将 API Key 硬编码到代码中，始终从环境变量读取，.env 文件必须在 .gitignore 中
2. **CSV 数据文件**：NYE4.0_v3.csv 必须放在 data/ 目录下，服务启动前确认文件存在
3. **新手安全规则**：这是 P0 硬约束，新手过滤在 Python 后端执行，LLM 无法绕过
4. **语义判断边界**：Python 后端禁止对效果、场景、情绪做关键词匹配，这些由 LLM 独占处理
5. **对话历史上限**：前端最多保留 20 条消息（10 轮），超出时丢弃最旧的消息对
6. **测试隔离**：LLM 相关测试必须 mock OpenAI API，不能在测试中产生真实 API 调用
7. **CORS 配置**：开发阶段允许所有源，生产环境需限制为实际部署域名
