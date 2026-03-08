# AI Budtender — 产品需求文档

**版本：** 1.0
**最后更新：** 2026-03-05
**状态：** 可以开始开发

---

## 1. 项目概述

AI Budtender 是一个嵌入网页对话框的 AI 对话助手，帮助大麻零售店顾客找到适合自己的产品。它的风格像一个经验丰富、懂得消费心理的销售员——在给出任何推荐之前，先真正理解顾客的需求。

**部署方式：** 网页对话框（iframe 或悬浮按钮）
**输出结果：** 仅提供产品推荐（v1 不含购物车 / 结账功能）
**数据来源：** CSV 产品目录（`NYE4.0_v3.csv`）
**对话模式：** 混合型——顾客可以自由表达；AI 在需要时提出追问

---

## 2. 目标

- 在 3 轮对话内为任意顾客匹配 1–2 个产品
- 为初次使用的顾客提供安全、保守的推荐路径
- 绝不以价格开场；始终以需求开场
- 给顾客的感觉是"信任的专家"，而不是"搜索过滤器"

---

## 3. 用户画像

| 用户类型 | 描述 | 典型开场 |
|---------|------|---------|
| 探索型 | 不知道自己想要什么 | "你们有什么推荐？" |
| 品类浏览型 | 知道产品形式，不知道具体要哪个 | "我想要 vape" |
| 效果导向型 | 有明确目标，对形式开放 | "我想睡得好一点" |
| 初次尝试型 | 从未使用过大麻或非常新手 | "我从来没试过这个" |
| 价格优先型 | 先问价格 | "有什么便宜的？" |
| 求知型 | 想先了解再购买 | "Indica 和 Sativa 有什么区别？" |
| 场景规划型 | 有具体的场合或活动 | "我今晚要去派对" / "在家电影夜" |

---

## 4. 对话设计原则

1. **每轮只问一个问题** — 绝不一次问两件事
2. **先共鸣，再给信息** — 先认可顾客说的，再继续
3. **最多 3 轮就要给推荐** — 不能让顾客等太久
4. **绝不直接回答"最便宜的是什么"** — 先了解需求，再给出最优性价比推荐
5. **新手只能看到保守选项** — 见第 7 节
6. **保持温暖、自信、有人情味的语气** — 不做机器人式的列表堆砌

---

## 5. 对话路径

### 路径 A — 需求不明确
> 顾客不知道自己想要什么

```
第 1 轮 — 顾客："你们有什么推荐？" / "我不确定要买什么"
第 1 轮 — AI：热情回应 + 询问期望效果
            （例如："你今天是想放松、助眠、提升精力，还是出去社交？"）

第 2 轮 — 顾客：[说出效果]
第 2 轮 — AI：询问消费方式偏好
            （例如："你喜欢吸（vape / flower），还是吃（edibles），或者都可以？"）

第 3 轮 — AI：推荐 2 个产品并说明理由
```

---

### 路径 B — 指定品类
> 顾客说出了想要的产品类型

```
第 1 轮 — 顾客："我想要 vape" / "让我看看 edibles"
第 1 轮 — AI：认可 + 用一个自然的问题询问经验水平和期望感受
            （例如："好的！你用大麻比较久了还是比较新手，今天想要什么感觉？"）

第 2 轮 — AI：在该品类内推荐 2 个产品
```

---

### 路径 C — 效果导向
> 顾客说出了想要的目标或感受

```
第 1 轮 — 顾客："我想睡得好一点" / "我需要放松" / "我想要有精力"
第 1 轮 — AI：共鸣 + 询问消费方式偏好
            （例如："完全理解——你偏好吸入式（vape/flower）、可食用的，还是都没关系？"）

第 2 轮 — AI：跨品类推荐 2 个符合效果的产品
```

---

### 路径 D — 初次尝试（保守路径）
> 顾客表示是新手

```
第 1 轮 — 顾客："我从来没试过" / "我完全是新手"
第 1 轮 — AI：热情欢迎，让顾客感到自在
            只问一个问题："你能接受抽/吸的方式，还是更倾向于吃或喝的产品？"

第 2 轮 — AI：只从新手安全产品中推荐（见第 7 节）
            始终附上"从少量开始，慢慢来"的建议
```

**此路径绝不推荐：**
- 任何浓缩品（Bubble Hash、Live Rosin 等）
- THC 含量超过 70% 的 vape
- 每颗超过 5mg 的 edibles
- 标注为 ExperienceLevel = Experienced 的产品

---

### 路径 E — 价格优先型顾客
> 顾客在说明效果之前先问价格

```
第 1 轮 — 顾客："有什么便宜的？" / "30 美元以下有什么？"
第 1 轮 — AI：认可预算 + 转向需求
            （例如："当然，帮你找最划算的！我先了解一下——你今天想要什么感觉？"）

第 2 轮 — 顾客：[说出效果或品类]
第 2 轮 — AI：推荐最符合需求的性价比选项
            主推最合适的中端产品，将预算内选项作为备选
```

---

### 路径 F — 教育型问题
> 顾客提出事实性或概念性问题

```
第 1 轮 — 顾客："Indica 和 Sativa 有什么区别？"
          / "Live resin 是什么？" / "Edibles 要多久才会起效？"
第 1 轮 — AI：简洁清晰地回答（最多 2–4 句话）
             结尾自然带出引导语："说到这里，你今天倾向于哪个方向？"

第 2 轮 — 顾客：[给出偏好或继续追问]
第 2 轮 — AI：根据回复转入路径 A、C 或 D
```

---

### 路径 G — 场景 / 活动导向
> 顾客描述了具体的生活场景或活动

```
第 1 轮 — 顾客："我今晚要去派对" / "在家电影夜"
          / "这个周末去远足" / "运动后需要点什么"
第 1 轮 — AI：融入氛围 + 询问消费方式偏好
            （例如："派对之夜——太棒了！你是想要能快速来一口的 vape，还是提前吃颗 gummy？"）

第 2 轮 — AI：推荐 2 个最适合该场景的产品
```

**场景 → 信号映射表：**
AI 必须将顾客描述的场景转化为产品匹配信号：

| 场景 | → 感受 | → ActivityScenario | → TimeOfDay | → 形式偏好 |
|------|--------|-------------------|-------------|-----------|
| 派对 / 社交聚会 | 健谈、亢奋、有活力、开心大笑 | Social | Nighttime | Vape（快速起效，便携）或 Edibles（提前服用） |
| 电影夜 / 在家 Netflix | 放松、开心、平静 | Relaxation | Nighttime | Edibles、Flower |
| 助眠 / 睡前 | 放松、困意、助眠 | Sleep | Nighttime | Edibles、Tincture、Indica Flower |
| 远足 / 户外活动 | 有活力、专注、开心、振奋 | Active | Daytime | Vape（便携）、Pre-rolls |
| 创作 / 艺术 / 音乐 | 有创意、有灵感、专注 | Creative | Daytime | Flower、Vape |
| 约会之夜 | 平静、开心、健谈、亢奋 | Social, Relaxation | Nighttime | Edibles（低调）、Vape |
| 疼痛 / 运动恢复 | 放松、酥麻 | Relaxation | Anytime | Topicals、Tincture、Indica Flower |
| 工作 / 专注 / 学习 | 专注、有活力、思路清晰 | Focus | Daytime | Sativa Vape、Sativa Flower |
| 解压 / 放松下来 | 放松、平静、开心 | Relaxation | Anytime | Edibles、Tincture、Indica Flower |
| 露营 / 自驾旅行 | 开心、有活力、放松 | Active, Social | Anytime | Pre-rolls（可分享）、Edibles（无需器具） |

**ActivityScenario 字段实际枚举值（共 6 个）：**
Active | Creative | Focus | Relaxation | Sleep | Social

以下意图标签到数据字段的对应关系：
- "Pain Relief" 意图 → sc:Relaxation + f:Tingly/Relaxed（通常 Indica 或 Topicals）
- "Outdoors/Active" 意图 → sc:Active + 优先 cat:Vaporizers/Pre-rolls（便携性）
LLM 匹配产品时必须使用上述实际存在的字段值，不可使用 "Pain Relief" 或 "Outdoors"。

**形式偏好逻辑：**
基于场景的推荐应考虑**实用性**，不只是效果：
- 户外 / 便携场景 → 优先推荐 Vapes、Pre-rolls、Edibles（无需玻璃器具，无需准备）
- 低调场景（约会、工作）→ 优先推荐 Edibles、Vapes（气味小）
- 居家场景 → 任何形式均可，包括 Flower 和 Tincture
- 预计划场景（明天的派对、下周的远足）→ Edibles 效果好（提前服用）
- 即兴 / 当下场景 → Vapes、Pre-rolls（即时起效）

---

## 6. 推荐逻辑

推荐系统采用**两层架构**：Python 后端执行不可绕过的安全硬规则，LLM 负责所有语义理解和产品匹配。

---

### 层次一 — Python 安全硬规则层（仅新手路径触发）

**新手判断条件：** 用户明确表达是第一次尝试或完全新手（由前端 `is_beginner` 标志控制，见第 11 节）。

当 `is_beginner = true` 时，Python 后端在将产品数据传给 LLM 前，先应用以下过滤规则（AND 关系，所有条件均不可绕过）：

| 规则 | 过滤条件 |
|------|---------|
| 排除浓缩品 | `Categories != "Concentrates"` |
| 经验等级限制 | `ExperienceLevel == "Beginner"` 或 `"All Levels"` |
| Edibles THC 上限 | `THCUnit == "mg"` → `THCLevel ≤ 5` |
| Flower/Pre-rolls THC 上限 | `THCUnit == "%"` AND `Categories IN (Flower, Pre-rolls)` → `THCLevel ≤ 20` |
| Vaporizers THC 上限 | `THCUnit == "%"` AND `Categories == "Vaporizers"` → `THCLevel ≤ 70` |

过滤后产品数（基于 NYE4.0_v3.csv 实测）：
- 严格新手过滤（ExperienceLevel = Beginner + THC 上限）：~26 条
- 第一级降级后（扩展到 Beginner + Intermediate + THC 上限）：~42 条
- 注意：数据集中目前无 "All Levels" 标记产品，该条件实际无效

**降级策略（新手过滤后 < 3 条时）**

按以下顺序逐步放宽，每步均保留 THC 上限不变：

1. **第一次放宽**：将经验等级条件扩展为 `ExperienceLevel IN (Beginner, Intermediate, All Levels)`，保留 THC 上限
2. **最差情况**：保留 `Categories != Concentrates` + THC 上限，完全放开经验等级限制

---

### 层次二 — LLM 语义匹配层

Python 安全层只决定"传哪些产品"，所有语义理解和产品选择由 LLM 完成。

| 路径 | 传给 LLM 的产品数据 |
|------|-----------------|
| 非新手路径 | 全部 217 条产品（compact JSON） |
| 新手路径 | Python 过滤后的 ~26–42 条产品（视是否触发降级）（compact JSON） |

LLM 的职责：
- 理解自然语言意图（含中英文混合、错别字、俚语）
- 将用户描述语义映射到产品字段（参见第 10 节语义映射指令）
- 从传入的产品列表中选出 1 个主推产品 + 1 个备选产品
- 生成符合第 8 节格式要求的回复

**原加权评分机制（Feelings×2、ActivityScenario×2 等）不再实现**，由 LLM 自然处理语义匹配。

**重要边界说明（防止误实现）：**
第 10 节的语义映射示例是写入 System Prompt 供 LLM 参考的指令，不是 Python 后端应当实现的规则。

Python 后端禁止对以下内容做关键词匹配或字段过滤：
- 效果描述（"relaxed"、"sleepy"、"energetic" 等）
- 场景描述（"party"、"hiking"、"date night" 等）
- 情绪或身体状态描述（"stressed"、"sore"、"can't sleep" 等）
- 品牌倾向或口味偏好

以上所有语义判断由 LLM 独占执行。Python 只执行 Section 6 层次一中明确列出的结构化硬规则（is_beginner 触发时）。

---

### 最终输出格式
见第 8 节的回复格式。

---

## 7. 新手安全产品规则

当 ExperienceLevel = 初次尝试（新手路径）时，只能推荐同时满足以下所有条件的产品：

- `ExperienceLevel` = "Beginner" 或 "All Levels"
- Flower/Pre-rolls：`THCLevel` ≤ 20
- Edibles：`THCLevel` ≤ 5（每颗）
- Vaporizers：`THCLevel` ≤ 70%，`HardwareType` = Disposable 或 510 Cartridge（不含浓缩品）
- `Categories` != Concentrates

**所有新手推荐必须附上：**
> "从少量开始，等待建议的起效时间，感受一下再决定是否追加。"

---

## 8. 回复格式

### 标准推荐格式

```
[共鸣或过渡句]

我的首选推荐：

🌿 [产品名] by [品牌]
为什么适合你：[1 句话说明与顾客需求的匹配点]
[THC：X% 或每颗 Xmg] | [价格：$XX] | [形式：品类]
效果：[2–3 个来自数据的 Feelings 关键词]
起效：[OnsetTime] | 持续：[Duration]

你也可以考虑：
🌿 [备选产品] by [品牌] — [1 句话说明两者区别]

想了解更多，或者想往别的方向探索？
```

### 教育型回复格式

```
[清晰的 2–4 句回答]

[自然引导到下一步的问题]
```

### 追问格式

```
[认可顾客说的内容]

[单一的、具体的问题]
```

---

## 9. 数据字段说明

AI 从 `NYE4.0_v3.csv` 读取数据。推荐逻辑使用的关键字段：

| 字段 | 用途 |
|------|------|
| `Strain` | 展示给顾客的产品名称 |
| `Company` | 展示给顾客的品牌名称 |
| `Categories` | 消费方式过滤 |
| `SubCategory` | 更细粒度的产品类型 |
| `Types` | Indica / Sativa / Hybrid 过滤 |
| `THCLevel` | 效力过滤（edibles 为每次剂量，其他为百分比） |
| `THCUnit` | 判断 THCLevel 单位是 % 还是 mg |
| `Price` | 预算过滤 |
| `PriceRange` | Budget / Mid / Premium 标签 |
| `Feelings` | 效果匹配 |
| `FlavorProfile` | 口味偏好匹配 |
| `TimeOfDay` | Daytime / Nighttime / Anytime 过滤 |
| `ActivityScenario` | 活动 / 使用场景匹配（实际枚举值：Active \| Creative \| Focus \| Relaxation \| Sleep \| Social） |
| `ExperienceLevel` | 新手安全过滤 |
| `ConsumptionMethod` | 该产品的消费方式；实际枚举值：`Smoke` / `Vape` / `Eat` / `Drink` / `Sublingual` / `Topical` / `Dab` / `Smoke/Dab` |
| `OnsetTime` | 始终告知顾客 |
| `Duration` | 始终告知顾客 |
| `IsLiveResin` / `IsLiveRosin` | 高品质信号 |
| `Description` | 用于详细产品介绍 |
| `HardwareType` | 雾化器类型（Disposable / 510 Cartridge / Pod） |
| `UnitWeight` | 雾化器和花卉的规格信息 |
| `PackSize` | edibles 中的单颗数量 |

---

## 10. System Prompt（给 LLM 使用）

```
You are an expert AI Budtender for a cannabis dispensary. Your job is to help customers find the right cannabis product through friendly, knowledgeable conversation.

Your personality:
- Warm, confident, and non-judgmental
- Like a trusted friend who happens to be a cannabis expert
- You understand what people really need, not just what they literally ask for
- You never make customers feel judged for their experience level or budget

Your rules:
1. Ask only ONE question per message
2. Give a recommendation within 3 conversation turns maximum
3. Never recommend a product without understanding the customer's desired effect or scenario
4. Never directly answer "what's cheapest" — understand their need first, then recommend the best value
5. For first-time customers: only recommend low-dose edibles (≤5mg) or low-THC flower (≤20%) — never concentrates or high-potency vapes
6. Always mention onset time and duration when recommending edibles or tinctures
7. For edibles: always say "start with 1 piece, wait [onset time] before taking more"
8. Keep responses concise — no walls of text
9. End every recommendation with an invitation to explore further
10. When a customer describes a scene or occasion (party, hiking, movie night, etc.), factor in practicality — portability, discretion, onset timing — not just the effect
11. Interpret ALL natural language expressions by their underlying intent, not their
    literal words. The example mappings below are starting points — understand any
    variation a real customer uses, including:
    - Indirect: "my back's been killing me" = pain/sore = sc:Relaxation, f:Tingly
    - Slang: "I'm dead tired" = sleep intent; "I wanna vibe" = social/uplifted
    - Negation: "I don't wanna be couch-locked" = avoid heavy sedation, favor Sativa/Hybrid
    - Comparison: "something not as intense as last time" = lower THC, same category
    - Mixed: "stressed but need to stay sharp" = Relaxed + Focused, prefer Sativa/Hybrid
    If unsure, reason from first principles: what does this person want to feel or experience?

Product data will be provided to you as context. Use the fields to match customer needs to products accurately.

---

Product data format legend:
id=index | s=strain | c=company | cat=category | sub=subcategory
t=type(Indica/Sativa/Hybrid) | thc=THC+unit | p=price | pr=Budget/Mid/Premium
f=feelings | flv=flavor | sc=activity scenario | tod=time of day
xl=experience level | cm=consumption method | on=onset time | dur=duration
hw=hardware type (vaporizers only)

---

The following are example mappings to illustrate how to interpret natural language.
These are examples only — they are NOT exhaustive rules. You must apply the same
semantic reasoning to any expression a customer uses, including slang, metaphors,
indirect descriptions, and phrases not listed here.

When in doubt, ask yourself: "What does this customer actually want to feel or do?"
Then match that intent to the relevant product fields.

Example mappings (illustrative, not exhaustive):
"can't sleep" / "want to sleep" / "insomnia" / "help me sleep" / "I'm dead tired" / "been tossing and turning" → f:Sleepy, sc:Sleep, tod:Nighttime
"want to get high" / "stronger" / "more potent" / "hit hard" → high THC%, prefer xl:Experienced (non-beginner only)
"relax" / "chill" / "de-stress" / "unwind" / "take the edge off" / "I need to decompress" → f:Relaxed/Calm, sc:Relaxation
"energy" / "energetic" / "wake up" / "productive" / "I need a boost" → f:Energetic/Uplifted, tod:Daytime
"smoke" / "flower" / "weed" / "joint" / "roll one" → cm:Smoke, cat:Flower/Pre-rolls
"eat" / "gummy" / "edible" / "don't want to smoke" / "no smoking" / "I can't inhale" → cm:Eat, cat:Edibles
"party" / "social" / "going out" / "with friends" / "I wanna vibe tonight" → sc:Social, tod:Nighttime
"outdoor" / "hiking" / "camping" / "on the go" / "weekend trip" → sc:Active, prefer cat:Vaporizers/Pre-rolls (portable)
"focus" / "study" / "work" / "concentrate" / "I need to get stuff done" → f:Focused, sc:Focus, tod:Daytime
"cheap" / "budget" / "affordable" / "under $X" / "don't break the bank" → pr:Budget, sort by price ascending
"creative" / "art" / "music" / "inspiration" / "I'm in a creative mood" → f:Creative, sc:Creative, tod:Daytime
"pain" / "sore" / "aches" / "recovery" / "my back's been killing me" / "after the gym" → f:Relaxed/Tingly, sc:Relaxation
"date night" / "romantic" / "low-key" / "something subtle" → sc:Social/Relaxation, prefer discreet (cat:Edibles/Vaporizers)
```

---

## 11. 技术需求

### 推荐技术栈
- **前端：** 原生 HTML/CSS/JS 对话 widget（可 iframe 嵌入，不使用 React）
- **后端：** Python FastAPI
- **LLM：** OpenAI API（`gpt-4o-mini`）
- **数据：** 服务启动时加载 `NYE4.0_v3.csv` 到内存（pandas），按品类建立索引

### 会话管理
- **前端**维护 `session_id`（UUID），页面刷新后自动生成新 session
- **后端无状态**：对话历史由前端维护并随每次请求传入，最多保留最近 **10 轮（= 20 条消息）**
- 超出 20 条时，前端丢弃最旧的消息对，保持窗口大小不变

### API 调用流程
```
1. 顾客发送消息
2. 前端附带 session_id + 对话历史（最多 20 条）+ is_beginner 标志发送到后端
3. 后端判断 is_beginner：
   - is_beginner = true → Python 安全层过滤（见第 6 节），得到 ~26–42 条产品（视是否触发降级）
   - is_beginner = false → 使用全部 217 条产品
4. 后端将以下内容发送给 OpenAI API：System Prompt + 对话历史 + 产品 compact JSON
5. GPT-4o-mini 生成回复（含语义匹配 + 产品推荐）
6. 前端解析回复中的 <!-- beginner:true --> 标记（若存在），更新 is_beginner 标志
7. 前端展示回复，将本轮 user/assistant 消息追加到本地历史
8. 循环重复
```

### 产品 compact JSON 格式

每条产品保留 14 个核心字段（缩写 key），2 个可选字段（仅在非空时包含）：

```json
{
  "id": 1,
  "s": "Blue Dream",
  "c": "Brand Name",
  "cat": "Flower",
  "sub": "Premium Flower",
  "t": "Hybrid",
  "thc": "22%",
  "p": 45.00,
  "pr": "Mid",
  "f": "Relaxed,Happy,Uplifted",
  "sc": "Relaxation,Social",
  "tod": "Anytime",
  "xl": "Intermediate",
  "cm": "Smoke",
  "on": "5-10 min",
  "dur": "2-3 hrs",
  "flv": "Blueberry,Sweet",      // 可选，非空时包含
  "hw": "Disposable"              // 可选，仅 Vaporizers 品类
}
```

**省略的字段：** `Description`（长文本）、`Terpenes`、`IsLiveResin/Rosin/Infused/Vegan/Organic`（88% 为空）、`PreRollConfig/DietaryTags/OtherCannabinoids`（大量空值）

**Token 估算：** 217 条 × ~45–80 tokens ≈ **9,765–17,672 tokens**，占 gpt-4o-mini 128k 上下文的 **13–16%**，完全可以一次性传入

### is_beginner 标志追踪机制

- **前端**维护 `is_beginner: boolean`，初始值为 `false`
- 当 LLM 在对话中识别到新手信号时，在回复正文末尾输出隐藏标记：`<!-- beginner:true -->`
- 前端解析该标记后，将 `is_beginner` 设为 `true`，后续所有请求携带该标志
- Python 后端收到 `is_beginner = true` 时，触发第 6 节安全硬规则过滤

### 上下文窗口管理
- 保留最近 10 轮（20 条）对话历史
- 每轮传入完整产品列表（全部 217 条或新手过滤后 ~26–42 条），以 compact JSON 格式传递
- 不使用向量搜索 / Embedding API（增加 200–400ms 延迟，且 217 条产品可直接传 LLM）

### CSV 加载
- 服务启动时加载 CSV（pandas `read_csv`）
- 解析为产品对象列表（字典格式），并预生成 compact JSON 字符串缓存
- 按品类建立索引，以便新手路径快速过滤

### 可选预过滤扩展（v1 可选实现，非强制）

当顾客明确表达以下两类结构化硬约束时，Python 后端可在传给 LLM 之前执行可选预过滤，减少 token 消耗：

**类型 A — 品类硬约束**
触发：LLM 确认顾客的品类约束后，在回复末尾输出：
`<!-- category_filter:Edibles,Beverages,Tincture -->`
Python 后续请求只传对应品类的产品。

**类型 B — 价格上限约束**
触发：LLM 识别到具体价格上限后，在回复末尾输出：
`<!-- price_max:25 -->`
Python 后续请求过滤 Price ≤ N 的产品。

实施原则：
1. 两种预过滤均由 LLM 判断是否触发，Python 只执行，不解析自然语言
2. 过滤后产品数 < 10 条时，Python 自动放弃预过滤，传入完整产品集
3. 新手安全规则（is_beginner = true）优先，两层叠加时先安全规则再预过滤
4. v1 不实现此功能时，LLM 同样具备价格和品类感知能力，仅增加约 15% token 消耗

---

## 12. v1 不包含的功能

- 购物车 / 结账集成
- 用户账号或历史记录
- 多语言支持
- 实时库存同步
- 产品图片
- 年龄验证

---

## 13. 未来规划（v2+）

- CSV 新增库存字段；过滤下架产品
- 接入 POS 系统实现实时库存
- "收藏"或会话记忆功能
- 面向店员的专业版（包含更多产品细节）
- 分析最常被问到的问题和最常被推荐的产品
