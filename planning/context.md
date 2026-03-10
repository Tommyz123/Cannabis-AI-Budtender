# Context - 项目索引与状态

最后更新: 2026-03-09 | 项目阶段: Size 搜索与展示支持已完成

## 项目简介
AI Budtender — 嵌入网页的 AI 大麻产品推荐助手，通过多轮对话理解顾客需求，为新手提供安全过滤，为所有用户推荐最合适的产品。

## 技术栈
Python 3.12.3 + FastAPI 0.135.1 + Pandas 2.2.3 + OpenAI API 2.26.0 (gpt-4o-mini) + Pydantic 2.12.5 + 原生 HTML/CSS/JS 前端

## 关键配置参数
| 参数 | 当前值 | 文件位置 |
|------|--------|---------|
| OPENAI_API_KEY | 见 .env | .env |
| CSV_PATH | data/NYE4.0_v3.csv | backend/config.py:6 |
| MAX_HISTORY_MESSAGES | 20 | backend/config.py:7 |
| MODEL_NAME | gpt-4o-mini | backend/config.py:8 |
| BEGINNER_THC_LIMITS | edibles_mg=5, flower_percent=20, vaporizers_percent=70 | backend/config.py:10-14 |

> ⚠️ 禁止在此填写 API Key、密码等敏感值，敏感值只存放在 .env 文件中。

## 稳定区（禁止改动）
- `data/NYE4.0_v3.csv` — 原始产品数据，217 条记录
- `backend/config.py` — 配置已稳定，不要随意增删字段

## 模块索引

### backend/config.py — 全局配置
- `OPENAI_API_KEY: str` — 从环境变量读取
- `CSV_PATH: str` — 产品 CSV 文件路径
- `MAX_HISTORY_MESSAGES: int` — 对话历史上限（20）
- `MODEL_NAME: str` — OpenAI 模型名称
- `BEGINNER_THC_LIMITS: dict` — 新手 THC 上限配置

### backend/models.py — Pydantic 模型
- `Message(role, content)` — 单条消息
- `ChatRequest(session_id, messages, is_beginner, user_message)` — 请求体
- `ChatResponse(reply, session_id, response_time_ms)` — 响应体（含耗时字段，单位毫秒）

### backend/product_manager.py — 产品数据管理
- `ProductManager.load(csv_path) → None` — 加载 CSV，建立索引
- `ProductManager.get_all_compact_json() → str` — 全量产品 compact JSON
- `ProductManager.get_beginner_compact_json() → str` — 新手安全过滤产品 JSON（含降级策略）
- `ProductManager.search_products(query, category, effects, exclude_effects, exclude_categories, min_thc, max_price, budget_target, time_of_day, activity_scenario, unit_weight, list_sub_types, limit) → dict` — 多条件产品搜索，供 tool calling 调用；unit_weight 支持精确匹配过滤（如 '28g'=1oz）
- `ProductManager.get_product_by_id(product_id) → dict | None` — 按 ID 返回单个产品
- `ProductManager.total_count → int` — 已加载产品数
- `ProductManager.category_index → dict` — 品类 → DataFrame 映射

### backend/llm_service.py — LLM 集成（Agent Loop）
- `SYSTEM_PROMPT: str` — 完整 system prompt（医疗保护、Discovery-First、销售规则 A-E、语义映射）
- `TOOLS_SCHEMA: list` — OpenAI function calling 格式工具定义（smart_search + get_product_details）
- `get_simple_response(user_message) → str | None` — 简单消息快路径，返回预设回复或 None
- `is_medical_query(user_message) → bool` — 检测医疗查询
- `is_vague_query(user_message) → bool` — 检测模糊查询
- `is_form_unknown_query(user_message, history) → bool` — 检测有效果但无形式的查询
- `extract_profile_signals(user_message, history) → dict` — 从对话中提取会话 profile
- `serialize_profile(profile) → str` — 将 profile 序列化追加到 system prompt
- `build_messages(history, user_message, profile=None) → list[dict]` — 组装消息列表（不注入产品 JSON）
- `get_recommendation(history, user_message, product_manager) → str` — Agent Loop：LLM + tool calling

### backend/main.py — FastAPI 应用
- `GET /health` — 返回 {status, products_loaded}
- `POST /chat` — 接收 ChatRequest，返回 ChatResponse
- `lifespan` — 启动时加载 CSV（通过 ProductManager）

### frontend/ — Chat Widget
- `frontend/index.html` — 主页面，包含悬浮按钮 + 对话框 HTML
- `frontend/style.css` — Widget 样式
- `frontend/chat.js` — 会话管理、API 调用、消息渲染（已移除 beginner 标记解析）

## 依赖关系
```
frontend/chat.js
  │
  └──► POST /chat (backend/main.py)
         │
         ├── get_simple_response() → 快路径（hi/thanks/bye 等）
         │
         └──► get_recommendation(history, user_msg, product_manager)
                   │
                   ├──► OpenAI API (gpt-4o-mini) — 第一次调用
                   │         └── tool_calls? → smart_search / get_product_details
                   │
                   ├──► ProductManager.search_products() ←── tool 执行
                   │         └──► data/NYE4.0_v3.csv
                   │
                   └──► OpenAI API — 最终回复
```

## 已知限制（非代码问题）
- CORS 当前允许所有源（*），生产部署时需限制为实际域名
- 前端无单元测试框架（Task 5 使用手动测试）
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
