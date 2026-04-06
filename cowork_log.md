# Cowork Log

## [2026-04-02 13:32] 修复 | router.py is_form_unknown_query | 成功
- 分析测试日志 budtender_test_20260402_1313.md（20 组真实接口测试，10/20 通过）
- 定位根因：`is_form_unknown_query()` 在 occasion 信号明确时仍拦截 tool call，导致 S9/S11/S12 等场景驱动推荐全部失败
- 新增 tc_G9（occasion-driven 无 form → 应直接搜索）并确认 fail
- 修改 `router.py`：`_OCCASION_SIGNALS` 命中时 bypass form-gate
- Eval 结果：tc_G9 100%，全集 22/22 100%，无回退
- Commit：c2ecb31（main 分支）
[2026-04-04 00:45] 修复 | feature/price-followup-fix 合并前检查 | 发现2个单测失败（beginner-ready 测试用例措辞不真实）+ eval tc_G11 失败，替换为真实药房场景表达后 65 passed、tc_G11 ✅，顺利合并入 main
[2026-04-04 17:03] 修复 | tc_C3 新手 edibles 剂量提醒 | 全集 24/24 100%，无回退，分支 feature/compliance-c3-fix
[2026-04-04 17:49] 修复 | router.py regex bugs (A+B) | happy 边界修复 + price regex 兼容粗体格式，全集 24/24 100%
[2026-04-04 18:20] 修复 | eval/run_eval.py rate limit 问题 | max_workers 4→1，全集顺序跑，23/24 通过（96%），tc_G8 失败为预存饮料品类问题与本轮 C/D/H 改动无关
[2026-04-04 18:32] 修复 | tc_G8 Beverages 品类映射 | prompts.py INFORMATION_GATHERING_PROMPT 补充 drink→Beverages 映射，全集 24/24 100%
