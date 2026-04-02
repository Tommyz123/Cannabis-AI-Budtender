# Context - 项目索引与状态

最后更新: 2026-04-02 | 项目阶段: 黄金数据集 23/23 通过，持续修正信息收集路由

## 项目简介
AI Budtender — 嵌入网页的 AI 大麻产品推荐助手，通过多轮对话理解顾客需求，为新手提供安全过滤，为所有用户推荐最合适的产品。

## 技术栈
Python 3.12.3 + FastAPI 0.135.1 + SQLite3 + Pandas 2.2.3 + OpenAI API 2.26.0 (gpt-4o-mini) + Pydantic 2.12.5 + 原生 HTML/CSS/JS 前端

## 关键配置参数
| 参数 | 当前值 | 文件位置 |
|------|--------|---------|
| OPENAI_API_KEY | 见 .env | .env |
| DB_PATH | data/products.db | backend/config.py |
| CSV_PATH | data/NYE4.0_v3.csv | backend/config.py（已退役，仅作迁移来源保留）|
| MAX_HISTORY_MESSAGES | 20 | backend/config.py |
| MODEL_NAME | gpt-4o-mini | backend/config.py |
| BEGINNER_THC_LIMITS | edibles_mg=5, flower_percent=20, vaporizers_percent=70 | backend/config.py |

> ⚠️ 禁止在此填写 API Key、密码等敏感值，敏感值只存放在 .env 文件中。

## 稳定区（禁止改动）
- `data/NYE4.0_v3.csv` — 原始产品数据（已退役为只读迁移来源，217 条记录）
- `data/products.db` — 主产品数据库（SQLite，217 条记录）
- `backend/config.py` — 配置已稳定，不要随意增删字段

## 数据库结构（data/products.db）

### products 表（主产品表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| product | TEXT | 产品名（原 Strain）|
| brand | TEXT | 品牌（原 Company）|
| category | TEXT | 品类（原 Categories）|
| sub_category | TEXT | 子分类 |
| strain_type | TEXT | 株型（原 Types：Hybrid/Indica/Sativa）|
| thc_level | REAL | THC 含量（单位由品类决定）|
| price | REAL | 价格 |
| price_range | TEXT | 价格区间 |
| effects | TEXT | 效果（原 Feelings）|
| flavor_profile | TEXT | 口味 |
| time_of_day | TEXT | 使用时段 |
| activity_scenario | TEXT | 使用场景 |
| experience_level | TEXT | 经验等级 |
| consumption_method | TEXT | 使用方式 |
| onset_time | TEXT | 起效时间 |
| duration | TEXT | 持续时间 |
| unit_weight | TEXT | 单位重量 |
| pack_size | INTEGER | 包装数量 |
| description | TEXT | 产品描述 |
| attributes | TEXT | JSON，品类专属字段 |

**THC 单位规则（代码常量，不存 DB）**：
- `%`：Flower / Pre-rolls / Vaporizers / Concentrates
- `mg`：Edibles（每颗）/ Beverages（每罐）/ Tincture（整瓶总量）/ Topicals（产品总量）

**attributes JSON 按品类结构**：
- Flower：terpenes, total_terpenes_pct, [infused], [other_cannabinoids]
- Pre-rolls：terpenes, total_terpenes_pct, pre_roll_config, [infused], [other_cannabinoids]
- Edibles：terpenes, [thc_total_mg], [dietary], [other_cannabinoids], [infused]
- Vaporizers：terpenes, total_terpenes_pct, hardware_type, oil_type, [other_cannabinoids]
- Beverages：terpenes, fast_acting, [dietary], [other_cannabinoids]
- Concentrates：terpenes, total_terpenes_pct, [other_cannabinoids]
- Tincture：terpenes, bottle_volume_ml, [dietary], [other_cannabinoids]
- Topicals：terpenes, [dietary], [other_cannabinoids]

### sessions 表（预留，暂未使用）
| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | TEXT PK | 会话 UUID |
| history | TEXT | 对话历史 JSON |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

## 迁移脚本（一次性工具）
- `scripts/setup_db.py` — 建表脚本（重新建库时使用）
- `scripts/migrate_csv_to_sqlite.py` — CSV → SQLite 全量迁移

## 模块索引

### backend/config.py — 全局配置
- `OPENAI_API_KEY: str` — 从环境变量读取
- `DB_PATH: str` — 产品 SQLite 数据库路径
- `CSV_PATH: str` — 原始 CSV 路径（只读，已退役）
- `MAX_HISTORY_MESSAGES: int` — 对话历史上限（20）
- `MODEL_NAME: str` — OpenAI 模型名称
- `BEGINNER_THC_LIMITS: dict` — 新手 THC 上限配置

### backend/models.py — Pydantic 模型
- `Message(role, content)` — 单条消息
- `ChatRequest(session_id, messages, user_message, is_beginner=False)` — 请求体
- `ChatResponse(reply, session_id, response_time_ms)` — 响应体（含耗时字段，单位毫秒）

### backend/product_manager.py — 产品数据管理
- `ProductManager.load(db_path) → None` — 从 SQLite 加载产品，建立索引
- `ProductManager.get_all_compact_json() → str` — 全量产品 compact JSON
- `ProductManager.get_beginner_compact_json() → str` — 新手安全过滤产品 JSON（含降级策略）
- `ProductManager.search_products(query, category, effects, exclude_effects, exclude_categories, min_thc, max_thc, max_price, budget_target, time_of_day, activity_scenario, unit_weight, list_sub_types, limit, is_beginner) → dict` — 多条件产品搜索；unit_weight 支持精确匹配；total 返回实际命中数；有 budget_target 时按价格距离升序；free-text query 覆盖 product/effects/flavor_profile/hardware_type/description；is_beginner=True 时套用新手安全过滤
- `ProductManager.get_category_summary_json() → str` — 返回品类数量统计 JSON
- `ProductManager.get_product_by_id(product_id) → dict | None` — 按 ID 返回单个产品
- `ProductManager.total_count → int` — 已加载产品数
- `ProductManager.category_index → dict` — 品类 → DataFrame 映射
- `THC_UNIT_BY_CATEGORY: dict` — 品类 → THC 单位映射常量

### backend/prompts.py — Prompt 模块（新增）
- `SYSTEM_PROMPT: str` — 完整 system prompt，由以下模块组装：
  - `MEDICAL_COMPLIANCE_PROMPT` — 医疗保护规则
  - `AGE_COMPLIANCE_PROMPT` — 年龄验证规则
  - `NON_CONSENSUAL_USE_PROMPT` — 非自愿用药拦截
  - `BEGINNER_SAFETY_PROMPT` — 新手安全规则
  - `INFORMATION_GATHERING_PROMPT` — 信息收集规则
  - `OCCASION_READY_SEARCH_PROMPT` — “date night / social”等场景 + vibe/guardrail 已完整时，禁止继续追问 form，要求立即搜索
  - `RECOMMENDATION_REFINEMENT_PROMPT` 中 Price Feedback 规则 — 已区分“首次预算澄清”和“已有推荐后的 cheaper refinement”；后者需直接给更便宜选项，并在结尾软性邀请用户补充 price range
  - `RECOMMENDATION_REFINEMENT_PROMPT` — 推荐优化规则
  - `FALLBACK_SEARCH_PROMPT` — 搜索降级规则
  - `_SALES_PROMPT` — 销售流程主规则

### backend/router.py — 请求路由与分类（新增）
- `get_simple_response(user_message) → str | None` — 快路径，返回预设回复或 None
- `is_medical_query(user_message) → bool` — 检测医疗查询
- `is_vague_query(user_message) → bool` — 检测模糊查询
- `is_form_unknown_query(user_message, history) → bool` — 检测有效果但无形式的查询
- `is_price_feedback_query(user_message) → bool` — 检测价格反馈查询
- `is_price_refinement_query(user_message, history) → bool` — 检测“已有具体推荐后，用户要求更便宜替代”的追问
- `is_generic_rejection_query(user_message) → bool` — 检测通用拒绝查询
- `is_vape_hardware_unknown_query(user_message, history) → bool` — 检测 vape 硬件类型未知查询
- `is_vape_flower_alternative(message) → bool` — 检测 "vape or flower" 混合意图
- `is_product_comparison(message) → bool` — 检测产品对比请求
- `is_negative_strength_constraint(message) → bool` — 检测负面强度约束
- `is_occasion_ready_query(user_message, history) → bool` — 检测“date night / social”等场景 + vibe/guardrail 已完整、可直接搜索的请求
- `has_form_keyword(text) → bool` — 检测产品形式关键词
- `determine_tool_choice(user_message, history) → str` — 决定 tool_choice（none/auto/required）；当 `is_occasion_ready_query=True` 时强制 `required`
- `derive_cheaper_price_cap(history) → float | None` — 从历史 assistant 推荐价格中提取最便宜项，并推导更低的价格上限供 cheaper follow-up 使用
- `extract_profile_signals(user_message, history) → dict` — 从对话中提取会话 profile
- `serialize_profile(profile) → str` — 将 profile 序列化追加到 system prompt
- `try_extract_search_params(user_message, history, is_beginner) → dict | None` — fast-path 参数提取；已支持从历史 user intent 继承 category/effects，并在 cheaper follow-up 时自动带入更低价格上限

### backend/tool_executor.py — Tool 定义与执行（新增）
- `TOOLS_SCHEMA: list` — OpenAI function calling 格式工具定义（smart_search + get_product_details）
- `execute_tool_call(tool_call, product_manager) → dict` — 工具调用分发器

### backend/llm_service.py — LLM 集成（Agent Loop）
- `build_messages(history, user_message, profile=None) → list[dict]` — 组装消息列表
- `get_recommendation(history, user_message, product_manager, is_beginner=False) → str` — Agent Loop 入口
- `_prepare_messages(...)` 仍保留价格反馈、价格 refinement、vape/flower 二选一、产品对比、负面强度约束等临时注入；`occasion-ready` 规则已迁移至 `prompts.py` 独立模块

### backend/main.py — FastAPI 应用
- `GET /health` — 返回 {status, products_loaded}
- `POST /chat` — 接收 ChatRequest，返回 ChatResponse
- `lifespan` — 启动时从 SQLite 加载产品（通过 ProductManager）

### frontend/ — Chat Widget
- `frontend/index.html` — 主页面，包含悬浮按钮 + 对话框 HTML
- `frontend/style.css` — Widget 样式
- `frontend/chat.js` — 会话管理、API 调用、消息渲染

## 依赖关系
```
frontend/chat.js
  │
  └──► POST /chat (backend/main.py)
         │
         ├── router.get_simple_response() → 快路径（hi/thanks/bye 等）
         │
         └──► llm_service.get_recommendation(history, user_msg, product_manager)
                   │
                   ├──► router.extract_profile_signals()   会话 profile 提取
                   ├──► router.determine_tool_choice()     路由决策
                   ├──► router.try_extract_search_params() fast-path 参数提取
                   ├──► prompts.SYSTEM_PROMPT              系统 prompt
                   │
                   ├──► OpenAI API (gpt-4o-mini) — 第一次调用（或 fast-path 跳过）
                   │         └── tool_calls? → smart_search / get_product_details
                   │
                   ├──► tool_executor.execute_tool_call()
                   │         └──► ProductManager.search_products()
                   │                   └──► data/products.db（SQLite）
                   │
                   └──► OpenAI API — 最终回复
```

## 已知限制（非代码问题）
- CORS 当前允许所有源（*），生产部署时需限制为实际域名
- 前端无单元测试框架（使用手动测试）
- sessions 表已建，服务端会话持久化功能预留待后期实现
- openai 2.x 为较新版本，API 接口未来可能变更

## 环境配置
- OS: Linux (WSL2 - Ubuntu on Windows)
- 虚拟环境路径: `venv/`（项目根目录）
- 激活（Linux/WSL）: `source venv/bin/activate`
- 激活（Windows CMD）: `venv\Scripts\activate`
- Python 直接调用: `venv/bin/python`
- 测试命令: `venv/bin/python -m pytest tests/ -v --cov=backend --cov-report=term-missing`
- Python 版本: 3.12.3
- 禁止使用系统 Python
