# 变更日志

> 按时间倒序记录每次代码修改、优化、评估。只追加，不修改历史记录。
> 格式：`## [YYYY-MM-DD] 类型 | 简述`

## [2026-03-06] 重构 | Agent 架构重构 + System Prompt 全面升级

**变更内容：**
- `backend/llm_service.py` — 全面重写：
  - System Prompt 重写：医疗保护、反幻觉、Discovery-First 工作流、销售规则 A-E（Upsell/Cross-sell/Closing）、缺货替代逻辑
  - 新增辅助函数：`get_simple_response`、`is_medical_query`、`is_vague_query`、`is_form_unknown_query`、`extract_profile_signals`、`serialize_profile`
  - 新增 `TOOLS_SCHEMA`（OpenAI function calling 格式，含 smart_search + get_product_details）
  - `build_messages()` 重构：不再注入产品 JSON，改为注入会话 profile
  - `get_recommendation()` 重构为 Agent Loop：LLM → tool call → 工具执行 → LLM 最终回复
- `backend/product_manager.py` — 新增：
  - `search_products()` — 多条件产品搜索（category/effects/THC/price/time_of_day 等过滤）
  - `get_product_by_id()` — 按 ID 返回单个产品
- `backend/main.py` — 简化 `/chat` endpoint：
  - 新增简单消息快路径（hi/thanks/bye → 直接返回，跳过 LLM）
  - 移除产品 JSON 预选择逻辑，改为传入 product_manager 实例
- `frontend/chat.js` — 移除 `beginner:true` 标记解析逻辑和 `isBeginner` 状态
- `tests/` — 更新全部测试以匹配新架构（新增 15 个测试，覆盖 Agent Loop、快路径、查询分类）

**涉及文件：** backend/llm_service.py, backend/product_manager.py, backend/main.py, frontend/chat.js, tests/test_llm_service.py, tests/test_api.py, tests/test_integration.py, tests/test_config.py

**测试结果：** 50/50 通过（pytest tests/ -v）

## [2026-03-06] 优化 | 配置 logging 级别使终端显示响应耗时

- **变更内容**：在 `backend/main.py` 的 `logger = logging.getLogger(__name__)` 之前添加 `logging.basicConfig(level=logging.INFO, ...)`，使已有的 `logger.info("session=%s response_time_ms=%.1f", ...)` 日志能在终端正常显示
- **涉及文件**：`backend/main.py`（仅添加 3 行 basicConfig 配置）
- **测试结果**：`pytest tests/test_api.py -v` → 6 passed，无回归

## [2026-03-06] 优化 | 修复 System Prompt 过度提问逻辑

- **变更内容**：在 `SYSTEM_PROMPT` 规则列表末尾新增规则 12 和 13
  - 规则 12：Indica/Sativa/Hybrid 已隐含 effect 意图，不得再追问 desired effect
  - 规则 13：用户同时指定 strain type + category 时，直接推荐，不得再问子格式（jar/pre-roll 等）
- **涉及文件**：`backend/llm_service.py`（仅修改 SYSTEM_PROMPT 字符串）
- **测试结果**：`pytest tests/test_api.py -v` → 6 passed，无回归

## [2026-03-06] 新增 | /chat 接口添加响应时间监控
- 变更内容：在 `ChatResponse` 新增 `response_time_ms: float` 字段；`/chat` 路由用 `time.perf_counter()` 计时 LLM 调用耗时并注入响应，同时用 `logging.info` 记录；测试新增对 `response_time_ms` 字段存在性和合法性的断言
- 涉及文件：`backend/models.py`、`backend/main.py`、`tests/test_api.py`
- 测试结果：6/6 passed

---

## [2026-03-06] 新增 | MVP 全量开发完成（Task 1-6）

**变更内容：**
- Task 1：创建项目目录结构（backend/ frontend/ data/ tests/），config.py，models.py，requirements.txt，.env.example，.gitignore
- Task 2：实现 ProductManager（CSV 加载、品类索引、compact JSON、新手过滤 + 降级策略）
- Task 3：实现 llm_service（system prompt、消息组装、OpenAI API 调用、错误处理）
- Task 4：实现 FastAPI 应用（/health、/chat、CORS、lifespan startup）
- Task 5：实现前端 Chat Widget（HTML/CSS/JS，悬浮按钮、对话框、is_beginner 追踪）
- Task 6：集成测试 + conftest.py（7 条对话路径验证、新手安全规则验证）

**涉及文件：**
- `backend/config.py`（新建）
- `backend/models.py`（新建）
- `backend/product_manager.py`（新建）
- `backend/llm_service.py`（新建）
- `backend/main.py`（新建）
- `frontend/index.html`（新建）
- `frontend/style.css`（新建）
- `frontend/chat.js`（新建）
- `tests/conftest.py`（新建）
- `tests/test_config.py`（新建）
- `tests/test_product_manager.py`（新建）
- `tests/test_llm_service.py`（新建）
- `tests/test_api.py`（新建）
- `tests/test_integration.py`（新建）
- `requirements.txt`（新建）
- `data/NYE4.0_v3.csv`（复制）

**测试结果：**
- `pytest tests/ -v --cov=backend` → 35/35 通过，覆盖率 89%
- pylint backend/ → 10.00/10
- bandit -r backend/ → 无高危问题

---

## [2026-03-05] 新增 | 项目环境初始化

**变更内容：**
- 创建 Python 虚拟环境（venv/，Python 3.12.3）
- 创建 planning/ 和 reports/ 目录
- 移动 context.md 和 logging.md 到 planning/
- 更新 CLAUDE.md 和 agents.md：填写常用命令、开发环境、语言规范区块
- 更新 planning/context.md 环境配置区块

**涉及文件：**
- `venv/`（新建）
- `planning/`（新建）
- `reports/`（新建）
- `planning/context.md`（从根目录移动 + 修改）
- `planning/logging.md`（从根目录移动）
- `CLAUDE.md`（修改）
- `agents.md`（修改）

**测试结果：**
- `source venv/bin/activate && python --version` → Python 3.12.3，正常

---

<!-- 每次完成代码修改后，在此处顶部追加一条记录，格式如下： -->

<!--
## [YYYY-MM-DD] 类型 | 简述

**变更内容：**
- [具体改了什么，为什么改]

**涉及文件：**
- `文件路径`（新建 / 修改 / 删除）

**测试结果：**
- [测试命令及结果，或说明"未运行测试"]
-->
