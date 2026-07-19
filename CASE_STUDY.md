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

## What this means for a dispensary

- **Staff time back.** Budtenders stop fielding "what do you have for relaxing that isn't too strong?" lookups — customers self-serve against the full catalog, staff handle the sales that need a human.
- **217 products down to a shortlist in a few turns.** The agent narrows by effect, occasion, and form instead of making customers scroll a menu.
- **Recommendations come with reasons.** Each suggestion shows what it's based on — customers see *why*, which builds trust in the store, not just the bot.
- **Lower compliance exposure.** Medical claims, under-21 signals, and beginner-overdose risks are blocked in code — reducing the risk that a chatbot conversation endangers the license.
- **Drops into a real store.** The widget embeds with one script tag, and the catalog layer reads structured product data — pointing it at a live dispensary catalog is a contained change.

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

The catalog is 217 structured records with well-defined fields (category, strain, effects, THC, price). I evaluated the obvious alternative — embedding every product and doing **vector similarity retrieval** — and **deliberately chose structured SQL + multi-criteria filtering instead.** For this data size and shape, exact predicates (`THC ≤ 20%`, `price < $30`, category = edibles) are faster, exact, and fully controllable — where cosine similarity over embeddings would be fuzzy, harder to debug, and would fight the hard numeric compliance filters. *The goal was recommendation accuracy and controllability — not demonstrating a particular retrieval pattern.*

To be clear about the trade-off: **vector RAG is the right call when the source is large and unstructured** — a document corpus where you chunk, embed, and retrieve by semantic meaning because there are no clean fields to filter on (e.g. a legal/policy knowledge base answering open-ended questions). This catalog is the opposite: small, structured, query-by-attribute. Knowing *which* problem you have is the skill — and the retrieval layer is cleanly isolated, so swapping in a vector store is a contained change if the data ever outgrows SQL.

The same judgment applies to reliability: **critical compliance paths are enforced deterministically in code, while non-critical paths route the model toward a tool call and accept its probabilistic nature** — knowing where to force determinism vs. where to trust the model is the real skill.

---

## Determinism as a UI Contract — the Consistency Guardrail

A subtle bug surfaced in real testing: the chat prose named one set of products while the UI cards rendered another (a fuzzy product-name match colliding across brands). Rather than patch the matcher, I removed the bug's precondition: **the backend now deterministically selects the 3–6 recommendations, and both the model's prose and the UI cards render from that single list** — chat and cards physically cannot disagree. Thin result sets are backfilled to a minimum of three by category and honestly labeled "Similar option"; zero real matches stay zero — no fabricated results.

The guarantee is verified at the DOM level: the screenshot pipeline reads card names and chat text from the same live DOM and asserts every card is named in the conversation — assets only ship on `allConsistent: true`. All 148 tests and the 6/6 compliance eval held through the refactor.

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

## 对门店意味着什么
- **把员工时间还回来**：顾客对全量商品库自助筛选，"有什么放松又不太猛的"这类查询不再占用店员，人力留给需要真人的成交环节
- **217 件商品几轮对话缩到一个短名单**：按效果/场景/形式收敛，不让顾客刷菜单
- **推荐带依据**：每个建议显示它基于什么——顾客看得到"为什么"，信任落在店上而不只是机器人上
- **降低合规暴露**：医疗声明/未满21信号/新手过量风险在代码层被拦——减少一段聊天危及牌照的可能
- **能进真门店**：挂件一个 script 标签嵌入，商品层读结构化数据——接入真实 dispensary catalog 是可控改动

## 最难的部分——合规用代码强制
差异化不在聊天本身，而在**安全是双层系统，不是提示词里一句祈祷**。
- **第一层·提示词模块**（最高优先级，最先注入）：4 个独立可编辑的合规模块——医疗声明保护（禁"缓解/减轻"等治疗性动词）、年龄验证（任何<21信号硬拦）、非自愿使用拒绝、新手安全（剂量限制 + 强制"start low go slow"）。
- **第二层·代码层硬强制**（不依赖模型自觉）：医疗类查询被路由分类器捕获并返回 `tool_choice="none"`，模型在结构上被禁止推荐商品；新手安全是数据层数值硬过滤（食用≤5mg / 花≤20% / 电子烟≤70%，排除注入型），会话级生效不会中途忘记。
这套"提示词+代码"双保险正是合规敏感领域（金融/医疗/法律）所需，也是"demo"和"受监管企业真能跑的东西"的分界。

## 证明它有效——eval 驱动开发
本项目自带 golden-dataset eval 框架，端到端验证对话质量：**31 个 eval 用例**覆盖 7 个维度（合规/信息收集/推荐优化/兜底/多轮上下文/防幻觉/意图切换），含幻觉与意图冲突的 **P0 回归守卫**；混合评分=确定性规则检查 + LLM 裁判（DeepSeek）逐条打分；可观测性接 **Langfuse**，失败非零退出=可进 CI；**148 个单元/集成测试**（mock LLM，秒级离线跑，无需 API key 即可复现）。**结果：合规维度每次跑都 6/6（100%）——最要紧的护栏永不失手；整体约 30-31/31（≈95%+）覆盖全部维度。**

## 一个值得强调的工程判断
商品库 217 条结构化数据，字段清晰（品类/品系/效果/THC/价格）。我评估了显而易见的替代方案——把每个商品 embedding 后做**向量相似度检索**——并**刻意选择结构化 SQL + 多条件过滤**。就这个数据量和结构而言，精确谓词（`THC ≤ 20%`、`价格 < $30`、品类=食用）更快、精确、完全可控；而 embedding 上的余弦相似度会模糊、更难调试、还会和数值型合规硬过滤打架。*目标是推荐的准确性和可控性，不是展示某种检索模式。*

把取舍说清楚：**向量 RAG 是对的选择——当数据源大而非结构化时**：一堆文档，你需要 chunk、embedding、按语义检索，因为没有干净字段可过滤（比如回答开放式问题的法律/政策知识库）。而这个商品库正相反：小、结构化、按属性查询。**知道自己面对的是哪种问题才是真本事**——且检索层干净隔离，将来数据涨大了要换向量库是可控改动。

同样的判断也用在可靠性上：**关键合规路径用代码强制确定性，非关键路径则把模型引向工具调用、接受它的概率本性**——知道何处该强制确定性、何处该信任模型，才是真本事。

## 确定性一致性护栏——把"嘴上说的"和"卡片摆的"锁成一份
真实测试暴露的 bug：聊天文字点名一组产品、UI 卡片却摆出另一组（模糊品名匹配跨品牌撞名）。我没有修补匹配器，而是消灭这类 bug 的存在条件：**后端确定性选出 3-6 个推荐，模型照单念、卡片照单摆**——同一份清单，文字和卡片物理上不可能不一致。结果太少时按品类补齐到 3 张并诚实标注"Similar option"；真零结果保持零，不造假。验证做到 DOM 级：截图脚本从同一 live DOM 读卡名和聊天文字，断言每张卡都在对话中被点名，`allConsistent: true` 才出图。重构后 148 测试全过、合规 eval 保持 6/6。

## 成果
✅ **合规维度每次跑 6/6（100%）**——最要紧的护栏永不失手 ✅ **整体约 30-31/31（≈95%+）** 覆盖 7 个 eval 维度 ✅ 148/148 测试全过（离线、无需 API key） ✅ 合规双层强制且有专门 eval 验证 ✅ 完整可运行产品（FastAPI 后端 + 可嵌入挂件 + 217 商品实时库）

## 这证明的可迁移能力（都不限大麻）
构建真实 LLM agent（tool-calling/function calling/延迟成本优化）；把软性政策要求变成代码级硬约束（金融/医疗/法律 AI 关键）；eval 驱动开发（规则+LLM裁判+可观测，资深 LLM 工程师的可靠交付流程）；务实架构（分层单一职责、按需选型、代码整洁有文档）。
