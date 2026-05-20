# 变更日志

> 按时间倒序记录每次代码修改、优化、评估。只追加，不修改历史记录。
> 格式：`## [YYYY-MM-DD] 类型 | 简述`
>
> 历史归档：[logging_2026Q2.md](logging_2026Q2.md)（2026-05-18 及之前，752 行）

## [2026-05-19] 修复 | router fast-path 加 strain-effect 冲突反转 + tc_SEC2 反向回归保护

- **背景**：tc_SEC1 锁定的 strain-effect 意图切换 bug（用户 history 锁 indica → 当前消息问 energy）端到端连续 2 次 prompt 修改失败（5 PASS/1 FAIL → 3 PASS/3 FAIL），原因经证据级诊断查明：**`router.py` fast-path 在 Python 层把"history 的 strain + 当前消息的 effect"组合成 smart_search 参数后直接绕过 LLM Call 1，且 fast-path 内部 LLM 调用不传 `tools=`，导致 `STRAIN_EFFECT_CONFLICT_PROMPT` 完全没作用点。**

- **变更内容**：
  1. `backend/router.py:try_extract_search_params` — 把 `effects = _detect_effects(msg_lower)` 拆为 `effects_in_current`，再决定是否回退 history；在 build params 前插入冲突反转块（约 +12 行）：
     - 触发条件：`strain_type and not strain_in_current and effects_in_current`
     - Indica + 当前消息含 Energetic/Uplifted → 反转为 Sativa
     - Sativa + 当前消息含 Sleepy → 反转为 Indica
     - 不影响用户当前消息显式声明 strain 的场景（strain_in_current 非 None 时跳过反转）
  2. `backend/prompts.py` — `STRAIN_EFFECT_CONFLICT_PROMPT` 末尾新增 "Tool Call Parameter Rule (CRITICAL)" 区块（约 +18 行），列出参数级 ✅/❌ 反例。作为 agent-loop 路径上的真实防御保留（fast-path 路径绕过 LLM 时此 prompt 无效，但当前修复让 fast-path 自己处理冲突）。
  3. `golden_dataset_v2.json` — total_cases 30 → 31，新增 `tc_SEC2`：反向场景（Sativa lock + 当前消息 sleepy → 应反转为 Indica/Hybrid），mirror tc_SEC1 的 6 条 judge_criteria。

- **涉及文件**：
  - `backend/router.py`（router 模块）
  - `backend/prompts.py`（prompts 模块）
  - `golden_dataset_v2.json`（eval 数据集）

- **测试结果**：
  - `_test_sec1.py` 端到端 × 3 次 → 全部 6/6 PASS（之前 5/1 FAIL → 3/3 FAIL → 修复后 6/0）
  - `pytest tests/ -q` → 144/144 通过，无回退
  - `eval/run_eval.py --tc tc_SEC2` → 规则:✅ / 标准:6/6 / 得分:100%（fast-path 实测注入 `strain_type='Indica', effects=['Relaxed','Sleepy']`，反转生效）
  - 报告：`reports/eval_20260519_203436.md`

- **诊断流程改进**：本次确立"证据级诊断 → 根因确认 → 设计方案 → 主公拍板 → 实施 → 评估 eval"五步流程，已写入 memory（feedback_diagnose_before_design.md）。
