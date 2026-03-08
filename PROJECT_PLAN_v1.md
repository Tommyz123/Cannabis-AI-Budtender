# PROJECT_PLAN — AI Budtender

**版本：** v1
**项目阶段：** MVP期
**维度数：** 9

---

## 1. 项目概述

### 产品愿景
AI Budtender 是一个嵌入网页的 AI 对话助手，帮助大麻零售店顾客通过自然对话找到最适合自己的产品。它模拟一位经验丰富、有温度的销售员——先理解需求，再给出推荐。

### 目标用户
- 探索型顾客（不知道想要什么）
- 品类浏览型顾客（知道产品形式）
- 效果导向型顾客（有明确目标）
- 初次尝试型顾客（新手）
- 价格优先型顾客
- 求知型顾客（想了解后再购买）
- 场景规划型顾客（有具体活动或场合）

### 核心价值
- 3 轮对话内完成产品推荐
- 为新手提供安全保守的推荐路径
- 以需求为导向，而非价格导向
- 给顾客"信任的专家"而非"搜索过滤器"的体验

### 项目类型
Web 应用（前端对话 Widget + Python 后端 API + LLM 集成）

---

## 2. 需求分析

### 功能需求

**P0（必须实现）：**
1. 对话 Widget — 可嵌入网页的聊天界面（iframe 或悬浮按钮）
2. 多路径对话引擎 — 支持 7 种用户意图路径（A-G）的对话流
3. 新手安全过滤 — Python 后端硬规则过滤（排除浓缩品、THC 上限、经验等级限制）
4. LLM 语义匹配 — 调用 OpenAI API 理解用户意图并匹配产品
5. CSV 产品加载 — 启动时加载 NYE4.0_v3.csv 到内存并建立索引
6. 产品推荐输出 — 按规定格式输出 1 个主推 + 1 个备选产品
7. 会话管理 — 前端维护 session_id 和对话历史（最多 10 轮 / 20 条消息）
8. is_beginner 标志机制 — LLM 输出隐藏标记，前端解析并传回后端

**P1（应该实现）：**
1. 降级策略 — 新手过滤后产品不足 3 条时逐步放宽条件
2. 可选预过滤 — 品类硬约束和价格上限约束的预过滤扩展

### 非功能需求
- 响应延迟：用户发送消息到收到回复 < 5 秒
- 对话质量：每轮只问一个问题，最多 3 轮给推荐
- 安全性：新手路径绝不推荐高 THC 或浓缩品
- 兼容性：Widget 可通过 iframe 嵌入任意网页

### 业务规则
- 绝不以价格开场，始终以需求开场
- 先共鸣再给信息
- 新手只能看到保守选项
- 教育型回答最多 2-4 句话
- 推荐时必须附上起效时间和持续时间

---

## 3. 系统架构

### 架构模式
前后端分离的 Client-Server 架构。前端为轻量级原生 HTML/CSS/JS Widget，后端为 Python FastAPI 无状态 API 服务。

### 架构图

```
┌─────────────────────────────────┐
│         宿主网页                 │
│  ┌───────────────────────────┐  │
│  │   Chat Widget (iframe)    │  │
│  │  ┌─────────────────────┐  │  │
│  │  │  对话界面 (HTML/CSS) │  │  │
│  │  │  会话管理 (JS)       │  │  │
│  │  │  is_beginner 追踪    │  │  │
│  │  │  历史消息管理        │  │  │
│  │  └─────────────────────┘  │  │
│  └───────────┬───────────────┘  │
└──────────────┼──────────────────┘
               │ HTTP POST /chat
               ▼
┌──────────────────────────────────┐
│      Python FastAPI 后端          │
│  ┌────────────────────────────┐  │
│  │  API 路由层                │  │
│  │  ├─ POST /chat             │  │
│  │  └─ GET /health            │  │
│  ├────────────────────────────┤  │
│  │  新手安全过滤层            │  │
│  │  ├─ 排除浓缩品             │  │
│  │  ├─ THC 上限检查           │  │
│  │  ├─ 经验等级过滤           │  │
│  │  └─ 降级策略               │  │
│  ├────────────────────────────┤  │
│  │  产品数据层                │  │
│  │  ├─ CSV 加载 (pandas)      │  │
│  │  ├─ 品类索引               │  │
│  │  └─ Compact JSON 缓存     │  │
│  ├────────────────────────────┤  │
│  │  LLM 集成层               │  │
│  │  ├─ System Prompt 管理     │  │
│  │  ├─ OpenAI API 调用        │  │
│  │  └─ 响应处理               │  │
│  └────────────────────────────┘  │
└──────────────┬───────────────────┘
               │ API Call
               ▼
┌──────────────────────────────────┐
│      OpenAI API (gpt-4o-mini)    │
│  ├─ System Prompt + 产品数据     │
│  ├─ 对话历史                     │
│  └─ 语义匹配 + 推荐生成          │
└──────────────────────────────────┘
```

### 数据流
1. 用户在 Widget 输入消息
2. 前端组装请求：session_id + 对话历史(≤20条) + is_beginner + 用户消息
3. 后端收到请求，根据 is_beginner 决定产品集：
   - `true` → 安全过滤后的 ~26-42 条产品
   - `false` → 全部 217 条产品
4. 后端构建 OpenAI API 请求：System Prompt + 对话历史 + 产品 compact JSON
5. OpenAI API 返回回复（含语义匹配的推荐）
6. 后端返回回复给前端
7. 前端解析 `<!-- beginner:true -->` 标记（若有），更新 is_beginner
8. 前端展示回复，追加到历史

### SOLID 符合度
- **S（单一职责）**：前端只负责 UI 和会话管理，后端只负责数据过滤和 LLM 调用，LLM 只负责语义理解
- **O（开闭原则）**：对话路径和安全规则可通过配置扩展，无需修改核心逻辑
- **L（里氏替换）**：LLM 提供者可替换（OpenAI → 其他），只需实现相同接口
- **I（接口隔离）**：API 接口简洁，仅暴露 /chat 和 /health
- **D（依赖倒置）**：后端通过抽象接口调用 LLM，不直接依赖 OpenAI SDK 细节

---

## 4. 技术栈选型

| 类别 | 选型 | 备注（替代方案） |
|------|------|----------------|
| 前端框架 | 原生 HTML/CSS/JS | React, Vue |
| 后端框架 | Python FastAPI | Flask, Django |
| LLM 服务 | OpenAI API (gpt-4o-mini) | Claude API, Gemini |
| 数据处理 | pandas | polars |
| HTTP 客户端 | openai Python SDK | httpx 直接调用 |
| ASGI 服务器 | uvicorn | hypercorn |
| 跨域处理 | FastAPI CORS 中间件 | nginx 反代 |
| 代码质量 | pylint + bandit | ruff, flake8 |
| 测试框架 | pytest + pytest-asyncio | unittest |
| 包管理 | pip + requirements.txt | poetry, pipenv |

---

## 5. 核心模块设计

### 模块 1：Chat Widget（前端对话界面）

**职责：** 提供用户交互界面，管理会话状态和对话历史

**位置：** `frontend/`
- `frontend/index.html` — 主页面 / Widget 容器
- `frontend/style.css` — 样式
- `frontend/chat.js` — 对话逻辑和 API 通信

**接口：**
- `sendMessage(text)` — 发送用户消息到后端
- `appendMessage(role, content)` — 在界面追加消息气泡
- `parseBeginnerTag(response)` — 解析 `<!-- beginner:true -->` 标记
- `trimHistory(history)` — 修剪历史到最多 20 条消息

**扩展点：** 可替换样式主题；可添加快捷回复按钮

---

### 模块 2：API 路由层（FastAPI 端点）

**职责：** 接收前端请求，协调各模块处理，返回响应

**位置：** `backend/main.py`

**接口：**
- `POST /chat` — 接收 `{session_id, messages, is_beginner, user_message}` 返回 AI 回复
- `GET /health` — 健康检查

**扩展点：** 可添加中间件（日志、限流）；可添加新端点

---

### 模块 3：产品数据管理模块

**职责：** 加载 CSV 数据，建立品类索引，生成 compact JSON，执行新手安全过滤

**位置：** `backend/product_manager.py`

**接口：**
- `load_products(csv_path)` — 加载 CSV 并建立索引
- `get_all_products_json()` — 获取全部产品的 compact JSON
- `get_beginner_safe_products_json()` — 获取新手安全过滤后的 compact JSON
- `apply_beginner_filter(products_df)` — 应用新手硬规则过滤
- `apply_fallback(products_df, level)` — 执行降级策略

**扩展点：** 可添加品类/价格预过滤；可切换数据源（CSV → 数据库）

---

### 模块 4：LLM 集成模块

**职责：** 构建 prompt，调用 OpenAI API，处理响应

**位置：** `backend/llm_service.py`

**接口：**
- `get_recommendation(system_prompt, messages, products_json)` — 调用 LLM 获取推荐回复
- `build_system_prompt()` — 构建 system prompt（含语义映射指令）
- `build_messages(history, user_message, products_json)` — 构建完整消息列表

**扩展点：** 可替换 LLM 提供者；可调整 prompt 策略

---

### 模块 5：配置与常量管理

**职责：** 集中管理所有配置项和常量

**位置：** `backend/config.py`

**接口：**
- `OPENAI_API_KEY` — API 密钥（从环境变量读取）
- `CSV_PATH` — 产品数据文件路径
- `MAX_HISTORY_MESSAGES` — 最大历史消息数（20）
- `BEGINNER_THC_LIMITS` — 新手 THC 上限配置
- `MODEL_NAME` — LLM 模型名称（gpt-4o-mini）

**扩展点：** 可添加新配置项；可切换为 .env 文件管理

---

## 6. API 接口文档

### POST /chat

**描述：** 发送用户消息，获取 AI Budtender 回复

**请求体：**
```json
{
  "session_id": "uuid-string",
  "messages": [
    {"role": "user", "content": "我想要放松一下"},
    {"role": "assistant", "content": "完全理解..."}
  ],
  "is_beginner": false,
  "user_message": "有什么推荐吗？"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话 UUID，前端生成 |
| messages | array | 是 | 对话历史，最多 20 条 |
| is_beginner | boolean | 是 | 是否为新手 |
| user_message | string | 是 | 当前用户消息 |

**响应体：**
```json
{
  "reply": "AI 回复文本（可能含 <!-- beginner:true --> 标记）",
  "session_id": "uuid-string"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| reply | string | AI 回复内容 |
| session_id | string | 回传 session_id |

**错误响应：**
| 状态码 | 说明 |
|--------|------|
| 400 | 请求格式错误 |
| 500 | LLM 调用失败 |

---

### GET /health

**描述：** 健康检查端点

**响应体：**
```json
{
  "status": "ok",
  "products_loaded": 217
}
```

---

## 7. 数据模型设计

### 产品数据表（来自 CSV）

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| id | int | 索引序号 | 1 |
| Strain | string | 产品名称 | "Blue Dream" |
| Company | string | 品牌名称 | "Kiva" |
| Categories | string | 产品品类 | "Flower" |
| SubCategory | string | 子品类 | "Premium Flower" |
| Types | string | Indica/Sativa/Hybrid | "Hybrid" |
| THCLevel | float | THC 含量 | 22.0 |
| THCUnit | string | THC 单位 | "%" 或 "mg" |
| Price | float | 价格 | 45.00 |
| PriceRange | string | 价格区间 | "Budget"/"Mid"/"Premium" |
| Feelings | string | 效果感受 | "Relaxed,Happy,Uplifted" |
| FlavorProfile | string | 口味 | "Blueberry,Sweet" |
| TimeOfDay | string | 适用时段 | "Daytime"/"Nighttime"/"Anytime" |
| ActivityScenario | string | 活动场景 | "Relaxation,Social" |
| ExperienceLevel | string | 适用经验等级 | "Beginner"/"Intermediate"/"Experienced" |
| ConsumptionMethod | string | 消费方式 | "Smoke"/"Vape"/"Eat" |
| OnsetTime | string | 起效时间 | "5-10 min" |
| Duration | string | 持续时间 | "2-3 hrs" |
| HardwareType | string | 硬件类型（仅 Vaporizers） | "Disposable"/"510 Cartridge" |
| UnitWeight | string | 规格 | "3.5g" |
| PackSize | string | 包装数量（仅 Edibles） | "10" |

### Compact JSON 格式（传给 LLM）

每条产品使用缩写 key，14 个核心字段 + 2 个可选字段：

| 缩写 | 原字段 | 必含 |
|------|--------|------|
| id | 索引 | 是 |
| s | Strain | 是 |
| c | Company | 是 |
| cat | Categories | 是 |
| sub | SubCategory | 是 |
| t | Types | 是 |
| thc | THCLevel+THCUnit | 是 |
| p | Price | 是 |
| pr | PriceRange | 是 |
| f | Feelings | 是 |
| sc | ActivityScenario | 是 |
| tod | TimeOfDay | 是 |
| xl | ExperienceLevel | 是 |
| cm | ConsumptionMethod | 是 |
| on | OnsetTime | 是 |
| dur | Duration | 是 |
| flv | FlavorProfile | 否（非空时） |
| hw | HardwareType | 否（仅 Vaporizers） |

### 数据流

```
NYE4.0_v3.csv
    │
    ▼ pandas read_csv
DataFrame (217 rows)
    │
    ├─ 按 Categories 建立索引 → category_index: Dict[str, DataFrame]
    │
    ├─ 预生成 compact JSON → all_products_json: str
    │
    └─ 新手过滤 → beginner_safe_df → beginner_products_json: str
```

---

## 8. 项目结构

```
AI_BUDTENDER2/
├── backend/
│   ├── main.py                 # FastAPI 应用入口，API 路由
│   ├── config.py               # 配置和常量管理
│   ├── product_manager.py      # 产品数据加载、索引、过滤
│   ├── llm_service.py          # LLM 集成（OpenAI API 调用）
│   ├── models.py               # Pydantic 请求/响应模型
│   └── requirements.txt        # Python 依赖
├── frontend/
│   ├── index.html              # 对话 Widget 主页面
│   ├── style.css               # Widget 样式
│   └── chat.js                 # 对话逻辑、会话管理、API 通信
├── data/
│   └── NYE4.0_v3.csv           # 产品数据文件
├── tests/
│   ├── test_product_manager.py # 产品管理模块测试
│   ├── test_llm_service.py     # LLM 集成模块测试
│   ├── test_api.py             # API 端点测试
│   └── conftest.py             # 测试配置和 fixtures
├── .env.example                # 环境变量模板
├── .gitignore                  # Git 忽略配置
└── README.md                   # 项目说明
```

### 目录说明

| 目录/文件 | 说明 |
|----------|------|
| `backend/` | Python FastAPI 后端代码 |
| `frontend/` | 原生 HTML/CSS/JS 前端 Widget |
| `data/` | 产品 CSV 数据文件 |
| `tests/` | 单元测试和集成测试 |
| `.env.example` | 环境变量模板（含 OPENAI_API_KEY 等） |

---

## 9. 测试与验证策略

### 测试框架
- **后端测试：** pytest + pytest-asyncio（异步 FastAPI 测试）
- **API 测试：** httpx AsyncClient（FastAPI TestClient）
- **前端测试：** 手动测试（v1 不引入前端测试框架）

### 测试类型

#### 单元测试
- `test_product_manager.py`：
  - 测试 CSV 加载是否正确解析所有字段
  - 测试新手过滤是否正确排除浓缩品
  - 测试新手过滤是否正确执行 THC 上限
  - 测试降级策略各级别行为
  - 测试 compact JSON 格式是否正确
- `test_llm_service.py`：
  - 测试 system prompt 构建
  - 测试消息列表构建（含产品 JSON）
  - 测试 OpenAI API 调用（mock）

#### 集成测试
- `test_api.py`：
  - 测试 POST /chat 端点正常请求
  - 测试 POST /chat 新手模式
  - 测试 POST /chat 历史消息截断
  - 测试 GET /health 端点
  - 测试错误请求处理（400）

### 验收标准
1. 所有单元测试通过
2. 新手过滤规则 100% 覆盖（排除浓缩品、THC 上限、经验等级）
3. API 端点返回正确格式的响应
4. 对话 Widget 可在浏览器中正常加载和交互
5. 完整对话流程可在 3 轮内给出推荐
6. LLM 回复包含正确的产品信息（名称、品牌、THC、价格）

### 测试命令

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_product_manager.py -v
pytest tests/test_llm_service.py -v
pytest tests/test_api.py -v

# 运行测试并显示覆盖率
pytest tests/ -v --cov=backend --cov-report=term-missing

# 代码质量检查
pylint backend/
bandit -r backend/
```

---

## 初步可行性评估

| 评估项 | 评分 | 说明 |
|--------|------|------|
| 技术可行性 | 9/10 | 所有技术组件成熟，FastAPI + OpenAI API 集成简单 |
| 数据可行性 | 9/10 | CSV 仅 217 条，可完整传入 LLM 上下文 |
| 团队可行性 | 8/10 | 需要 Python 后端和基础前端开发能力 |
| 时间可行性 | 8/10 | MVP 功能清晰，模块间耦合低，可快速迭代 |

---

## 生成信息

- **生成时间：** 2026-03-05
- **基于文档：** AI_Budtender_PRD_中文版.md v1.0
- **项目阶段：** MVP期（代码量 0 行，无现有模块）
- **维度数量：** 9
