# Claude Code 可借鉴技术分析

最后更新: 2026-03-31

## 文档目标

这份文档总结了从本地分析的 Claude Code 源码树中，哪些工程做法值得 `cannabis_AI_BUDTENDER` 借鉴，哪些不值得直接照搬，以及如果要落地，应该以什么技术方式改造到当前项目里。

本次参考的 Claude Code 源码位置主要是：

- `C:\Users\zhi89\Desktop\CC\src\src\query.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\Tool.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tools.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tools\AgentTool\AgentTool.tsx`
- `C:\Users\zhi89\Desktop\CC\src\src\tools\AgentTool\runAgent.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tasks\LocalAgentTask\LocalAgentTask.tsx`
- `C:\Users\zhi89\Desktop\CC\src\src\components\App.tsx`
- `C:\Users\zhi89\Desktop\CC\src\src\state\AppState.tsx`

当前 Budtender 重点参考文件：

- `backend/llm_service.py`
- `backend/product_manager.py`
- `backend/main.py`
- `eval/run_eval.py`

## 结论摘要

对 Budtender 最值得借鉴的不是 Claude Code 的终端 UI、多代理面板、bridge/teleport 这类“大产品能力”，而是下面四类工程思想：

1. 把 LLM 主循环和业务规则拆开。
2. 给工具调用建立统一抽象，不再靠 `if/elif` 扩张。
3. 把部分状态机从 prompt 迁移到代码层。
4. 增强运行时可观测性，让每轮对话路径可解释、可追踪、可评估。

一句话概括：

Budtender 应该借鉴 Claude Code 的“架构分层和运行框架”，而不是借它的“产品复杂度”。

## 适合借鉴的部分

### 1. 主循环与业务规则解耦

#### Claude Code 中的技术

Claude Code 的核心不是某个大 prompt，而是一条稳定的 query loop。主循环负责：

- 组装上下文
- 维护消息流
- 控制 token budget
- 处理工具调用回流
- 处理停止条件和后处理逻辑

参考位置：

- `C:\Users\zhi89\Desktop\CC\src\src\query.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\QueryEngine.ts`

#### 对 Budtender 的借鉴点

Budtender 目前的 `backend/llm_service.py` 已经包含了主循环雏形，但职责仍然比较集中。当前同一个文件同时承担了：

- system prompt 拼接
- 查询分类
- fast path
- 工具执行
- tool loop
- 会话级即时规则注入

这个方向本身是对的，但继续迭代会越来越难维护。

#### 建议的技术方式

将 `backend/llm_service.py` 拆成以下模块：

- `backend/query_runtime.py`
  负责调用模型、执行 tool loop、停止条件、异常转换。
- `backend/query_classifier.py`
  负责 `is_medical_query`、`is_vague_query`、`is_form_unknown_query`、`is_price_feedback_query` 等。
- `backend/prompt_builder.py`
  负责 system prompt 拼接、profile 注入、session context 注入。
- `backend/response_paths.py`
  负责 simple response、fast path、normal path 的路由。
- `backend/tool_runtime.py`
  负责工具注册、工具分发、工具结果标准化。

#### 落地收益

- 降低 `llm_service.py` 继续膨胀的风险
- 新增规则时，不必总改主循环
- 后续更容易做 tracing、A/B、回归定位

### 2. 工具系统抽象

#### Claude Code 中的技术

Claude Code 不是把工具当作“一个函数名”，而是统一抽象成 Tool 对象。一个工具通常包含：

- 名称
- 输入 schema
- 输出 schema
- 权限检查
- 执行函数
- 结果映射
- UI/进度描述

参考位置：

- `C:\Users\zhi89\Desktop\CC\src\src\Tool.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tools.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tools\MCPTool\MCPTool.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tools\BashTool\BashTool.tsx`

#### 对 Budtender 的借鉴点

Budtender 当前实际上已经是工具驱动，只是工具层还是隐式的：

- `smart_search`
- `get_product_details`

在 `backend/llm_service.py` 里，工具分发还是：

```python
if fn_name == "smart_search":
    ...
if fn_name == "get_product_details":
    ...
```

这个阶段还够用，但随着工具增加会快速变脆。

#### 建议的技术方式

增加一个轻量工具注册层，例如：

- `backend/tools/base.py`
  定义工具协议或 dataclass。
- `backend/tools/registry.py`
  统一注册工具。
- `backend/tools/search.py`
  `smart_search` 的 schema 和执行逻辑。
- `backend/tools/details.py`
  `get_product_details` 的 schema 和执行逻辑。

建议工具对象至少统一以下字段：

- `name`
- `description`
- `input_schema`
- `execute(**kwargs)`
- `activity_label`

#### 示例结构

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    executor: Callable[..., dict]
    activity_label: str
```

#### 落地收益

- 以后新增 `compare_products`、`list_categories`、`list_subtypes` 更自然
- `TOOLS_SCHEMA` 可以从注册表自动生成
- eval 中可以更容易记录工具名、参数、结果摘要

### 3. 用代码控制状态机，而不是只靠 prompt

#### Claude Code 中的技术

Claude Code 的一个关键思路是：模型负责生成语言和做局部决策，但系统的“边界、阶段、约束”尽量由代码控制，而不是完全交给 prompt。

例如：

- 工具是否可用由代码裁剪
- agent 是否允许后台运行由代码决定
- 权限模式和 prompt 展示能力由代码注入
- 子 agent 的工具池、消息上下文、MCP 权限都由代码先构造好

参考位置：

- `C:\Users\zhi89\Desktop\CC\src\src\tools\AgentTool\AgentTool.tsx`
- `C:\Users\zhi89\Desktop\CC\src\src\tools\AgentTool\runAgent.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tools\AgentTool\agentToolUtils.ts`

#### 对 Budtender 的借鉴点

Budtender 当前已经开始这样做了，这是非常好的方向：

- `_determine_tool_choice()`
- `try_extract_search_params()`
- `_prepare_messages()` 中的定向动作注入

但目前仍有大量状态机依赖 prompt 兜底，比如：

- 两个 signal 收没收齐
- 哪些反馈必须先追问
- 什么时候必须直接调用 tool
- 什么时候禁止 tool call

#### 建议的技术方式

定义显式的对话状态或动作枚举，例如：

- `ASK_EFFECT`
- `ASK_FORM`
- `ASK_BUDGET`
- `ASK_REJECTION_REASON`
- `RUN_SEARCH`
- `REFUSE_AGE`
- `REFUSE_NON_CONSENSUAL`
- `RESPOND_MEDICAL_DISCLAIMER`

再由一个规则引擎函数先决定 action，再决定是否调用模型。

建议新增：

- `backend/conversation_policy.py`

输出结构类似：

```python
@dataclass
class ConversationDecision:
    action: str
    tool_choice: str
    reason: str
    injected_constraints: list[str]
```

#### 落地收益

- 合规行为更稳定
- prompt 变短，模型负担更小
- 更适合写 deterministic tests

### 4. 运行时可观测性与结构化 trace

#### Claude Code 中的技术

Claude Code 虽然场景复杂，但一个很值得学的点是：系统内部尽量保留“这轮发生了什么”的结构化痕迹。

即使不看 UI，它的任务和消息系统也体现了以下思想：

- 当前正在做什么
- 最近调用了哪些工具
- 用了多少 token
- 结果从哪里来
- 任务何时完成/失败

参考位置：

- `C:\Users\zhi89\Desktop\CC\src\src\tasks\LocalAgentTask\LocalAgentTask.tsx`
- `C:\Users\zhi89\Desktop\CC\src\src\query.ts`

#### 对 Budtender 的借鉴点

Budtender 当前已经有不错的 eval 和 tool log 基础，尤其是：

- `eval/run_eval.py` 中的 `_PMWrapper`
- `_check_rules()`
- `tool_calls_log`

这说明你已经很接近“结构化 trace”了。

#### 建议的技术方式

在 `/chat` 运行路径中记录统一 trace 对象。例如：

- `session_id`
- `user_message`
- `classification_hits`
- `tool_choice`
- `fast_path_used`
- `tool_calls`
- `fallback_used`
- `response_time_ms`
- `final_reply_length`

建议新增：

- `backend/tracing.py`

并在 `backend/main.py` 与 `backend/query_runtime.py` 中统一调用。

#### 推荐 trace 结构

```python
{
  "session_id": "...",
  "user_message": "...",
  "route": "fast_path|tool_loop|simple_response",
  "classifiers": ["price_feedback", "form_known"],
  "tool_choice": "required",
  "tool_calls": [
    {"name": "smart_search", "args": {...}, "result_total": 4}
  ],
  "fallback_used": False,
  "response_time_ms": 812.4
}
```

#### 落地收益

- 线上问题更容易复盘
- eval 可以直接复用 trace 字段
- 日后接 Langfuse / OpenTelemetry / BI 都更容易

### 5. 明确能力边界

#### Claude Code 中的技术

Claude Code 在工具权限、sandbox、agent allowed tools 上非常强调“系统先限定能力边界，再让模型运行”。

参考位置：

- `C:\Users\zhi89\Desktop\CC\src\src\tools\AgentTool\agentToolUtils.ts`
- `C:\Users\zhi89\Desktop\CC\src\src\tools\BashTool\BashTool.tsx`

#### 对 Budtender 的借鉴点

Budtender 没有 shell/file 权限风险，但有“业务越权风险”：

- 不能做医疗承诺
- 不能给未成年人推荐
- 不能给无 consent 场景提供帮助
- 不能在工具返回空时编造库存
- 不能在没有数据时自己补全 flavor / effects / THC

#### 建议的技术方式

把这些能力边界抽成显式规则，而不是只放在 prompt 中：

- `backend/policy_rules.py`

按类型组织：

- `hard_refusal_rules`
- `tool_forbidden_rules`
- `tool_required_rules`
- `tool_result_grounding_rules`

#### 落地收益

- 业务风险更低
- 新场景扩展时不容易漏规则
- 更适合 CI 和 regression 测试

## 不建议直接照搬的部分

### 1. 多代理系统

Claude Code 的 agent/task/swarm 体系很强，但对 Budtender 当前阶段明显过度设计。

不建议直接引入：

- subagent
- background agent
- teammate
- coordinator

原因：

- Budtender 是单领域、高约束问答，不需要把任务拆给多个 agent
- 当前的主要问题是规则稳定性和架构清晰度，不是并行能力

### 2. 终端 UI / TUI 架构

Claude Code 的 React + Ink + AppState + task panel 架构不适合 Budtender。

不建议直接借：

- `components/App.tsx`
- `state/AppState.tsx`
- `ink/`

原因：

- Budtender 当前是 FastAPI + 简单网页组件
- 你不需要 terminal-native UI

### 3. 复杂 feature flag 体系

Claude Code 里大量使用：

- `feature('KAIROS')`
- `feature('BRIDGE_MODE')`
- `USER_TYPE === 'ant'`

这类体系是成熟大产品才需要的。

Budtender 当前不建议引入同等复杂度的开关系统。最多保留少量显式配置项即可，例如：

- 是否启用 fast path
- 是否启用 eval trace
- 是否启用 Langfuse

## 对 Budtender 的具体落地建议

### 建议优先级 P0

1. 拆分 `backend/llm_service.py`
2. 引入轻量 tool registry
3. 加结构化 trace

### 建议优先级 P1

1. 引入显式 `ConversationDecision`
2. 把 “必须问 / 必须搜 / 必须拒绝” 前移到代码层
3. 让 eval 直接读取运行时 trace 字段，而不是只看最终文本

### 建议优先级 P2

1. 补一个更清晰的会话 profile/state 数据结构
2. 考虑把 prompt 模块拆分为多个独立文件
3. 为工具调用增加统一 activity label 和错误分类

## 推荐的最小改造蓝图

推荐先做这一版，不要一次性过度重构：

```text
backend/
  main.py
  llm_service.py              # 先保留为兼容入口
  query_runtime.py            # 新：主循环
  query_classifier.py         # 新：分类器
  prompt_builder.py           # 新：prompt 拼接
  conversation_policy.py      # 新：动作决策
  tracing.py                  # 新：结构化 trace
  tool_runtime.py             # 新：工具分发
  tools/
    __init__.py
    registry.py
    search.py
    details.py
```

迁移顺序建议：

1. 先把 `TOOLS_SCHEMA` 和 `_execute_tool_call()` 移到 `tools/`
2. 再把 `_determine_tool_choice()` 和相关分类器移出
3. 最后把 `_run_agent_loop()` 移到 `query_runtime.py`

这样改动最稳，回归风险最低。

## 一句话建议

Budtender 最应该借鉴 Claude Code 的地方是：

“把模型、规则、工具、状态和执行路径拆清楚，并让每轮运行都可解释。”

最不该借的是：

“为了像 agent 平台而引入不必要的复杂度。”
