# 变更日志

> 按时间倒序记录每次代码修改、优化、评估。只追加，不修改历史记录。
> 格式：`## [YYYY-MM-DD] 类型 | 简述`

## [2026-03-09] 优化 | 产品推荐格式 — 品种类型单独行 + 标签化字段

**变更内容：**
- `SYSTEM_PROMPT` MANDATORY format 更新：Flower/Pre-rolls 品种类型（Sativa/Indica/Hybrid）单独一行显示
- Size / Price / THC 改为标签格式：`Size: 28g | Price: $270 | THC: 29%`
- Edibles / Vaporizers 不显示 strain type 行
- 更新示例（CORRECT / WRONG）

**涉及文件：** `backend/llm_service.py`（SYSTEM_PROMPT MANDATORY format 段落）

**测试结果：** 待手动验证

---

## [2026-03-09] 修复 | Flower 类目询问策略 — 问品种类型而非效果

**变更内容：**
- `SYSTEM_PROMPT` DISCOVERY-FIRST WORKFLOW Step 2 末尾新增 Flower exception 规则：form=Flower（或 Pre-rolls）且无品种类型（indica/sativa/hybrid）→ 问 "Are you looking for Sativa, Indica, or Hybrid?"，禁止问体验/效果
- 解决用户说 "do you have 1oz flower" 时 AI 错误走 NO SIGNAL 分支、询问体验的问题

**涉及文件：** `backend/llm_service.py`（SYSTEM_PROMPT Step 2）

**测试结果：** 待手动验证

---

## [2026-03-09] 新增 | 产品 Size 展示与搜索支持

**变更内容：**
1. `_row_to_compact()` 新增 `wt`（UnitWeight）和 `pk`（PackSize）可选字段
2. `search_products()` 新增 `unit_weight` 参数，支持精确匹配过滤；free-text query 新增 UnitWeight 列搜索
3. `TOOLS_SCHEMA` 新增 `unit_weight` 参数（含 oz → g 映射说明）
4. `SYSTEM_PROMPT` 字段说明补充 `wt`/`pk`；展示格式加入 size（含 wt/pk 组合规则）；NATURAL LANGUAGE INTERPRETATION 新增 1oz/half oz/quarter/eighth 映射规则

**涉及文件：** `backend/product_manager.py`、`backend/llm_service.py`

**测试结果：** 50/50 passed（pytest tests/ -v）

## [2026-03-09] 优化 | 修复品牌未展示 + 修复 effect intent 多余询问问题

- **变更内容**：
  1. 产品展示格式强化：明确 MANDATORY 标签，加入 CORRECT/WRONG 对比示例，强制"by [brand]"不可省略
  2. 字段说明补充：`c` = brand/company，解决 LLM 不识别字段的问题
  3. Discovery-First：flower + effect intent 已明确时（如 sleep/relax/energy），直接用 effect 搜索，跳过 strain type 询问；strain type 只在无任何 effect intent 时才问
  4. 自然语言映射：扩展 sleep 关键词覆盖，移除硬编码 query='indica'，让系统通过 effect 自然找到对应产品
- **涉及文件**：`backend/llm_service.py`
- **测试结果**：待测试

## [2026-03-09] 优化 | 产品展示加入品牌信息

- **变更内容**：`backend/llm_service.py` 产品展示格式加入品牌（Company 字段），格式改为 `**产品名** by 品牌 — $价格 | THC%`；同时新增字段索引说明，告知 LLM 搜索结果中 `c` = 品牌/公司名
- **涉及文件**：`backend/llm_service.py`
- **测试结果**：待测试

## [2026-03-09] 优化 | 产品推荐格式与展示逻辑升级

**变更内容：**
- `backend/llm_service.py` — System Prompt 多处升级：
  - Discovery-First：Flower/Pre-rolls 专业入口改为先问 strain type（Sativa/Indica/Hybrid），而非 effect
  - 新增 Rule F：Premium-first，不主动询问预算，先推优质选项，客户表示价格顾虑才降档
  - 新增 PROFESSIONAL SERVICE MINDSET 区块：单问原则、读上下文、高锚点、匹配客户能量、解读意图
  - 产品展示格式重写：从原始字段罗列改为自然语言描述（Good/Bad 示例），限制 2-4 个推荐
  - Tool call 规则更新：category 参数从当前消息或历史对话中读取 product form（非仅当前消息）
  - 移除 "no/nope/nah" 简单快路径（改由 LLM 根据上下文智能处理）
- `frontend/chat.js` — 前端渲染升级：
  - 新增 `renderMarkdown()` 函数，支持 `**bold**` → `<strong>` 和换行 → `<br>` 转换
  - AI 消息改用 `innerHTML` 渲染，用户消息仍用 `textContent`（安全隔离）

**涉及文件：** `backend/llm_service.py`, `frontend/chat.js`
**测试结果：** 待测试

## [2026-03-09] 修复 | 修复前端 isBeginner 未定义导致聊天报错

- **变更内容**：`frontend/chat.js` 第 99 行，将 `is_beginner: isBeginner` 改为 `is_beginner: false`。2026-03-06 重构时移除了 `isBeginner` 变量定义，但未同步清理引用，导致前端报 `ReferenceError: isBeginner is not defined`，所有 /chat 请求失败。新手判断逻辑由后端 LLM 通过对话自动识别，前端无需追踪。
- **涉及文件**：`frontend/chat.js`
- **测试结果**：前端发送消息正常，后端返回 AI 回复，连接验证通过

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
