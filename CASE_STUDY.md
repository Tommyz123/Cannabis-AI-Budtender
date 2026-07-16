# Case Study — AI Budtender: A Compliance-Aware Conversational Agent

> **One-liner:** An LLM agent that recommends cannabis products through multi-turn conversation — with compliance guardrails enforced in *code*, not just prompts, and proven by an automated eval suite.

> *Note: this is a portfolio project built to production standards (layered architecture, CI-ready eval, full test suite) — not a live deployment.*

---

## The Problem

Cannabis retail sits on hard legal lines. A recommendation assistant can't just be a friendly chatbot bolted onto GPT — the moment it says *"this will treat your anxiety"* (a medical claim), engages a customer who signals they're under 21, or tells a first-timer to take a full 10 mg edible, it crosses a compliance line that can put a dispensary's license at risk.

Most off-the-shelf chatbots have no concept of these boundaries. The challenge wasn't "make an AI that recommends products" — it was **"make an AI that recommends products while never crossing a compliance line, and prove it does so reliably."**

---

## What I Built

A conversational recommendation agent for a dispensary storefront:

- **Multi-turn conversation** that collects the two signals it needs (desired effect/occasion + consumption form), asking one question at a time and leading with expertise instead of interrogating.
- **Tool-calling agent loop** (OpenAI function calling) that queries a **217-product, 8-category** catalog through `smart_search` / `get_product_details` — so the model reasons over *real inventory*, not hallucinated products.
- **A drop-in chat widget** (vanilla JS, no build step) — embeds on any page with a single `<script>` tag.

---

## The Hard Part — Compliance Enforced in Code

The differentiator isn't the chatbot; it's that **safety is a two-layer system, not a hopeful sentence in a prompt.**

**Layer 1 — Prompt modules (highest-priority, injected first):** four independent, individually-editable compliance modules — medical-claim protection (bans therapeutic verbs like "alleviate/relieve"), age verification (hard block on any under-21 signal), non-consensual-use refusal, and beginner safety (dosage limits + mandatory "start low, go slow" guidance).

**Layer 2 — Hard enforcement in code (doesn't rely on the model behaving):**
- Medical queries are caught by a router classifier that returns `tool_choice="none"` — the model is **structurally forbidden from recommending products** on a medical question, regardless of how it's phrased.
- Beginner safety is a **numeric hard filter** at the data layer: edibles ≤ 5 mg, flower ≤ 20 % THC, vaporizers ≤ 70 %, infused products excluded — applied session-wide so it can't be forgotten mid-conversation.

This "prompt + code" belt-and-suspenders design is exactly what compliance-sensitive domains (finance, healthcare, legal) require, and it's what separates a demo from something a regulated business could actually run.

---

## Proving It Works — Eval-Driven Development

The project ships with a **golden-dataset eval framework** that validates conversation quality end-to-end:

- **31 eval cases** across 7 dimensions (compliance, information-gathering, recommendation-refinement, fallback, multi-turn context, anti-hallucination, and intent-switch) — including **P0 regression guards** for hallucination and strain/effect-conflict handling.
- **Hybrid grading:** deterministic rule checks (was the right tool called? were forbidden params avoided?) **plus** an LLM-as-judge (DeepSeek) that scores each turn against per-case criteria.
- **Results:** the **compliance dimension passes 6/6 (100%) every run** — the guardrails that matter most are rock-solid. Overall the suite clears **~30–31 of 31 (≈95%+)** across all dimensions.
- **Observability:** eval runs trace to **Langfuse** for scoring and inspection; non-zero exit on failure means it's CI-ready.
- **148 unit/integration tests** that mock the LLM client and run offline in seconds — reproducible on any machine without an API key.

---

## An Engineering Judgment Call Worth Highlighting

The catalog is 217 structured records. I evaluated vector/embedding retrieval and **deliberately chose structured SQL + multi-criteria filtering instead** — for this data size and shape it's faster, more precise, and fully controllable, with none of the overhead or fuzziness of a vector store. *Right-sizing the tool to the problem, not reaching for the heaviest option because it's fashionable.* (For a larger unstructured knowledge base, vector RAG would be the correct call — and the architecture cleanly supports swapping the retrieval layer.)

The same judgment applies to reliability: **critical compliance paths are enforced deterministically in code, while non-critical paths route the model toward a tool call and accept its probabilistic nature** — knowing where to force determinism vs. where to trust the model is the real skill.

---

## Results

- ✅ **Compliance dimension: 6/6 (100%) every run** — the guardrails that matter most never fail
- ✅ **~30–31/31 (≈95%+)** overall across 7 eval dimensions
- ✅ **148/148** unit/integration tests passing (offline, no API key required)
- ✅ Compliance enforced at both prompt and code layers, verified by dedicated eval cases
- ✅ Full working product — FastAPI backend + embeddable widget + live 217-product catalog

---

## Transferable Skills This Demonstrates

Nothing here is cannabis-specific. The same approach applies to any regulated or grounded-AI use case:

- **Building real LLM agents** — tool-calling loops, function calling, latency/cost optimization (fast-path bypass for greetings)
- **Turning soft policy requirements into hard, code-level constraints** — critical for finance / healthcare / legal AI
- **Eval-driven development** — rule checks + LLM-as-judge + observability, the workflow senior LLM engineers use to ship reliably
- **Pragmatic architecture** — layered, single-responsibility modules; right-sized technology choices; clean, documented code

---

### Tech Stack
Python 3.12 · FastAPI · OpenAI function calling (`gpt-4o-mini`) · SQLite · Pydantic · Pytest · DeepSeek (LLM judge) · Langfuse (eval observability) · Vanilla JS widget

---
---

# 案例研究（中文底稿）— AI Budtender：一个合规感知的对话式导购 Agent

> **一句话定位：** 一个通过多轮对话推荐大麻产品的 LLM agent——合规护栏用**代码**强制（不只写在提示词里），并有自动化 eval 套件验证。

> *说明：这是一个按生产标准构建的作品集项目（分层架构、可进 CI 的 eval、完整测试套件），非线上部署。*

## 问题
大麻零售有硬性法律红线。导购助手不能只是套在 GPT 上的友好聊天机器人——一旦它说"这个能治你的焦虑"（医疗声明）、继续服务一个透露自己未满 21 岁的顾客、或让新手直接吃满 10mg 软糖，就越过了可能危及门店牌照的合规线。多数现成 chatbot 根本没有这些边界概念。**真正的挑战不是"做个能推荐产品的 AI"，而是"做个推荐产品时永不越合规线、且能证明它可靠做到的 AI"。**

## 我做了什么
面向门店的对话式推荐 agent：多轮对话收集两个信号（想要的效果/场景 + 消费形式），一次问一个、以专业口吻引导；tool-calling agent 循环（OpenAI function calling）查询 **217 款 8 类** 真实商品库，让模型基于真实库存推理而非编造；即插即用聊天挂件（原生 HTML/CSS/JS，无需构建），一个 `<script>` 标签嵌入任何页面。

## 最难的部分——合规用代码强制
差异化不在聊天本身，而在**安全是双层系统，不是提示词里一句祈祷**。
- **第一层·提示词模块**（最高优先级，最先注入）：4 个独立可编辑的合规模块——医疗声明保护（禁"缓解/减轻"等治疗性动词）、年龄验证（任何<21信号硬拦）、非自愿使用拒绝、新手安全（剂量限制 + 强制"start low go slow"）。
- **第二层·代码层硬强制**（不依赖模型自觉）：医疗类查询被路由分类器捕获并返回 `tool_choice="none"`，模型在结构上被禁止推荐商品；新手安全是数据层数值硬过滤（食用≤5mg / 花≤20% / 电子烟≤70%，排除注入型），会话级生效不会中途忘记。
这套"提示词+代码"双保险正是合规敏感领域（金融/医疗/法律）所需，也是"demo"和"受监管企业真能跑的东西"的分界。

## 证明它有效——eval 驱动开发
本项目自带 golden-dataset eval 框架，端到端验证对话质量：**31 个 eval 用例**覆盖 7 个维度（合规/信息收集/推荐优化/兜底/多轮上下文/防幻觉/意图切换），含幻觉与意图冲突的 **P0 回归守卫**；混合评分=确定性规则检查 + LLM 裁判（DeepSeek）逐条打分；可观测性接 **Langfuse**，失败非零退出=可进 CI；**148 个单元/集成测试**（mock LLM，秒级离线跑，无需 API key 即可复现）。**结果：合规维度每次跑都 6/6（100%）——最要紧的护栏永不失手；整体约 30-31/31（≈95%+）覆盖全部维度。**

## 一个值得强调的工程判断
商品库 217 条结构化数据。我评估了向量/embedding 检索，**刻意选择结构化 SQL + 多条件过滤**——就这个数据量和结构而言更快、更精准、完全可控，没有向量库的开销和模糊性。*按问题选型，不为赶时髦上最重的工具。*（若换成更大的非结构化知识库，向量 RAG 才是对的选择——架构也干净地支持替换检索层。）

同样的判断也用在可靠性上：**关键合规路径用代码强制确定性，非关键路径则把模型引向工具调用、接受它的概率本性**——知道何处该强制确定性、何处该信任模型，才是真本事。

## 成果
✅ **合规维度每次跑 6/6（100%）**——最要紧的护栏永不失手 ✅ **整体约 30-31/31（≈95%+）** 覆盖 7 个 eval 维度 ✅ 148/148 测试全过（离线、无需 API key） ✅ 合规双层强制且有专门 eval 验证 ✅ 完整可运行产品（FastAPI 后端 + 可嵌入挂件 + 217 商品实时库）

## 这证明的可迁移能力（都不限大麻）
构建真实 LLM agent（tool-calling/function calling/延迟成本优化）；把软性政策要求变成代码级硬约束（金融/医疗/法律 AI 关键）；eval 驱动开发（规则+LLM裁判+可观测，资深 LLM 工程师的可靠交付流程）；务实架构（分层单一职责、按需选型、代码整洁有文档）。
