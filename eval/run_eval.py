"""
eval/run_eval.py — AI Budtender 自动化评估框架

用法：
    venv/bin/python eval/run_eval.py

依赖：
    - OPENAI_API_KEY（已有，用于 budtender 调用）
    - DEEPSEEK_API_KEY（LLM judge）
    - LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST（trace 记录）
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────────────────────
# 把项目根目录加入 sys.path，使 backend 模块可以直接 import
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

import openai

from backend.product_manager import ProductManager
from backend.llm_service import get_recommendation
from backend.router import get_simple_response

# ── 日志 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────────────────────────
DATASET_PATH = PROJECT_ROOT / "golden_dataset_v2.json"
CSV_PATH = PROJECT_ROOT / "data" / "NYE4.0_v3.csv"
DB_PATH = PROJECT_ROOT / "data" / "products.db"
REPORTS_DIR = PROJECT_ROOT / "reports"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

# ── Langfuse 初始化（可选，key 缺失时降级为本地模式）────────────────────────
_langfuse_enabled = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)
langfuse_client = None

if _langfuse_enabled:
    try:
        from langfuse import Langfuse
        langfuse_client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        logger.info("Langfuse 已连接：%s", LANGFUSE_HOST)
    except ImportError:
        logger.warning("langfuse 包未安装，跳过 trace 记录（pip install langfuse）")
        _langfuse_enabled = False
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Langfuse 初始化失败：%s，跳过 trace 记录", exc)
        _langfuse_enabled = False
else:
    logger.info("Langfuse key 未配置，本次以本地模式运行（不记录 trace）")


# ── 数据结构 ──────────────────────────────────────────────────────────────────
@dataclass
class EvalResult:
    tc_id: str
    scenario: str
    difficulty: str
    priority: str
    pass_count: int
    total_criteria: int
    rule_pass: bool
    score: float
    reply: str
    tool_calls: list = field(default_factory=list)
    criterion_results: list = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    user_message: str = ""
    conversation_history: list = field(default_factory=list)


# ── 工具调用拦截 ──────────────────────────────────────────────────────────────
class _PMWrapper:
    """轻量包装类，拦截 search_products 调用以记录 tool call，不修改共享 pm 对象（线程安全）。"""

    def __init__(self, pm: ProductManager, tool_calls_log: list):
        self._pm = pm
        self._log = tool_calls_log

    def search_products(self, **kwargs):
        result = self._pm.search_products(**kwargs)
        self._log.append({"name": "smart_search", "args": kwargs, "result": result})
        return result

    def __getattr__(self, name):
        return getattr(self._pm, name)


# ── 规则检查 ──────────────────────────────────────────────────────────────────
def _check_rules(tc: dict, tool_calls_log: list) -> tuple[bool, list[dict]]:
    """
    对照 expected_behavior 检查 tool call 规则。
    返回 (all_pass, rule_results_list)
    """
    expected = tc.get("expected_behavior", {})
    tool_should = expected.get("tool_should_be_called")
    expected_params = expected.get("expected_params", {})
    forbidden_params = expected.get("forbidden_params", {})

    rule_results = []
    all_pass = True

    # 1. 是否调用了正确的工具
    if tool_should == "smart_search":
        called = any(c["name"] == "smart_search" for c in tool_calls_log)
        rule_results.append({
            "rule": "tool_called",
            "expected": "smart_search",
            "pass": called,
            "reason": "smart_search 已调用" if called else "smart_search 未被调用",
        })
        if not called:
            all_pass = False
    elif tool_should == "optional":
        # Tool call is acceptable but not required — skip rule check
        rule_results.append({
            "rule": "tool_optional",
            "expected": "optional",
            "pass": True,
            "reason": "工具调用为可选，跳过规则检查",
        })
    elif tool_should is None:
        called = len(tool_calls_log) > 0
        rule_results.append({
            "rule": "tool_not_called",
            "expected": "no tool call",
            "pass": not called,
            "reason": "工具未调用（符合预期）" if not called else f"工具被意外调用：{tool_calls_log}",
        })
        if called:
            all_pass = False

    # 2. expected_params 检查（只检查第一个 smart_search 调用）
    if expected_params and tool_calls_log:
        actual_args = {}
        for c in tool_calls_log:
            if c["name"] == "smart_search":
                actual_args = c["args"]
                break

        def _norm(v):
            return str(v).lower().strip() if isinstance(v, str) else v

        for param, expected_val in expected_params.items():
            # 特殊处理：数值类型期望值（min_thc=20 等）
            if param in actual_args:
                actual_val = actual_args[param]
                # 列表类型：大小写不敏感子集匹配
                if isinstance(expected_val, list) and isinstance(actual_val, list):
                    actual_lower = [_norm(x) for x in actual_val]
                    expected_lower = [_norm(x) for x in expected_val]
                    overlap = [v for v in expected_lower if v in actual_lower]
                    ok = len(overlap) > 0
                else:
                    ok = _norm(actual_val) == _norm(expected_val)
            else:
                ok = False

            rule_results.append({
                "rule": f"expected_param:{param}",
                "expected": expected_val,
                "actual": actual_args.get(param),
                "pass": ok,
                "reason": f"参数 {param} 匹配" if ok else f"参数 {param} 缺失或不匹配（实际：{actual_args.get(param)}）",
            })
            if not ok:
                all_pass = False

    # 3. forbidden_params 检查
    if forbidden_params and tool_calls_log:
        actual_args = {}
        for c in tool_calls_log:
            if c["name"] == "smart_search":
                actual_args = c["args"]
                break

        for param, forbidden_val in forbidden_params.items():
            actual_val = actual_args.get(param)
            # 支持 ">N" 格式的数值比较
            if isinstance(forbidden_val, str) and forbidden_val.startswith(">"):
                threshold = float(forbidden_val[1:])
                if actual_val is not None:
                    violated = float(actual_val) > threshold
                else:
                    violated = False
            else:
                violated = actual_val == forbidden_val

            rule_results.append({
                "rule": f"forbidden_param:{param}",
                "forbidden": forbidden_val,
                "actual": actual_val,
                "pass": not violated,
                "reason": f"禁止参数 {param} 未出现（符合预期）" if not violated else f"禁止参数 {param}={actual_val} 被错误使用",
            })
            if violated:
                all_pass = False

    return all_pass, rule_results


# ── DeepSeek Judge ────────────────────────────────────────────────────────────
def _call_deepseek_judge(
    user_message: str,
    actual_reply: str,
    tool_calls_log: list,
    judge_criteria: list[str],
) -> tuple[str, list[dict]]:
    """
    调用 DeepSeek V3 作为 LLM 裁判，逐条评估 judge_criteria。
    返回 (raw_response_text, criterion_results)
    """
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY 未配置，跳过 LLM judge，所有 criteria 标记为 skip")
        skipped = [{"criterion": c, "pass": False, "reason": "DEEPSEEK_API_KEY 未配置，跳过"} for c in judge_criteria]
        return "SKIPPED", skipped

    criteria_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(judge_criteria))

    def _format_tool_calls_for_judge(log: list) -> str:
        if not log:
            return "（无工具调用）"
        formatted = []
        for c in log:
            entry = {"name": c["name"], "args": c["args"]}
            result = c.get("result")
            if result and isinstance(result, dict):
                products = result.get("products", [])
                entry["result_summary"] = {
                    "total": result.get("total", 0),
                    "products": products[:3],
                }
            formatted.append(entry)
        return json.dumps(formatted, ensure_ascii=False, indent=2)

    tool_calls_text = _format_tool_calls_for_judge(tool_calls_log)

    judge_prompt = f"""你是一个严格的 AI 评估裁判。
以下是一个 AI Budtender 的对话评估任务。

用户输入：{user_message}
AI 回复：
{actual_reply}

工具调用记录：
{tool_calls_text}

请逐条评估以下标准，每条给出 pass（true/false）和简短原因（1句话）：
{criteria_text}

严格按照以下 JSON 格式输出，不要输出其他内容：
{{"results": [{{"criterion": "标准原文", "pass": true, "reason": "原因"}}]}}"""

    try:
        client = openai.OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": judge_prompt}],
            temperature=0,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content or ""

        # 解析 JSON
        # 有时模型会在 JSON 前后加 markdown 代码块
        json_text = raw
        if "```" in raw:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            json_text = raw[start:end]

        parsed = json.loads(json_text)
        results = parsed.get("results", [])

        # 确保每条 criterion 都有结果（防止模型漏掉）
        if len(results) < len(judge_criteria):
            for i in range(len(results), len(judge_criteria)):
                results.append({
                    "criterion": judge_criteria[i],
                    "pass": False,
                    "reason": "模型未返回此条结果",
                })

        return raw, results

    except json.JSONDecodeError as exc:
        logger.error("DeepSeek judge JSON 解析失败：%s\n原文：%s", exc, raw[:500])
        failed = [{"criterion": c, "pass": False, "reason": f"JSON 解析失败：{exc}"} for c in judge_criteria]
        return raw, failed
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("DeepSeek judge 调用失败：%s", exc)
        failed = [{"criterion": c, "pass": False, "reason": f"调用失败：{exc}"} for c in judge_criteria]
        return str(exc), failed


# ── 单个测试用例评估 ──────────────────────────────────────────────────────────
def _lf_span(name: str, **kwargs):
    """返回 Langfuse v3 span context manager，Langfuse 未启用时返回 nullcontext。"""
    if _langfuse_enabled and langfuse_client:
        return langfuse_client.start_as_current_span(name=name, **kwargs)
    return nullcontext()


def run_single_case(tc: dict, pm: ProductManager) -> EvalResult:
    tc_id = tc["id"]
    scenario = tc["scenario"]
    difficulty = tc["difficulty"]
    priority = tc["priority"]
    user_message = tc["input"]["user_message"]
    history = tc["input"].get("conversation_history", [])
    judge_criteria = tc.get("judge_criteria", [])

    logger.info("▶ 评估 %s [%s/%s/%s]：%s", tc_id, scenario, difficulty, priority, user_message[:60])

    tool_calls_log: list[dict] = []
    pm_wrapper = _PMWrapper(pm, tool_calls_log)

    # Langfuse v3：最外层 span = trace
    with _lf_span(tc_id):
        if _langfuse_enabled and langfuse_client:
            langfuse_client.update_current_trace(
                tags=[scenario, difficulty, priority],
                metadata={
                    "description": tc.get("description", ""),
                },
            )

        try:
            # ── 调用 budtender（使用 pm_wrapper 拦截工具调用）─────────────────
            t_start = time.time()
            with _lf_span("budtender_call"):
                simple = get_simple_response(user_message)
                if simple is not None:
                    actual_reply = simple
                else:
                    actual_reply = get_recommendation(
                        history=history,
                        user_message=user_message,
                        product_manager=pm_wrapper,
                    )
                elapsed_ms = int((time.time() - t_start) * 1000)
                if _langfuse_enabled and langfuse_client:
                    langfuse_client.update_current_span(
                        input={"user_message": user_message},
                        output={"reply": actual_reply},
                        metadata={"elapsed_ms": elapsed_ms},
                    )

            # ── span: tool_calls ───────────────────────────────────────────────
            with _lf_span("tool_calls"):
                if _langfuse_enabled and langfuse_client:
                    langfuse_client.update_current_span(
                        metadata={"tool_calls": tool_calls_log},
                    )

            # ── 规则检查 ───────────────────────────────────────────────────────
            with _lf_span("rule_check"):
                rule_pass, rule_results = _check_rules(tc, tool_calls_log)
                if _langfuse_enabled and langfuse_client:
                    langfuse_client.update_current_span(
                        metadata={"rule_pass": rule_pass, "rule_results": rule_results},
                    )

            # ── DeepSeek judge ─────────────────────────────────────────────────
            with _lf_span("deepseek_judge"):
                judge_raw, criterion_results = _call_deepseek_judge(
                    user_message=user_message,
                    actual_reply=actual_reply,
                    tool_calls_log=tool_calls_log,
                    judge_criteria=judge_criteria,
                )
                if _langfuse_enabled and langfuse_client:
                    langfuse_client.update_current_span(
                        input={"criteria_count": len(judge_criteria)},
                        output={"raw_response": judge_raw[:1000]},
                        metadata={"criterion_results": criterion_results},
                    )

            # ── 统计得分 ───────────────────────────────────────────────────────
            pass_count = sum(1 for r in criterion_results if r.get("pass", False))
            total_criteria = len(judge_criteria)
            score = pass_count / total_criteria if total_criteria > 0 else 0.0

            # ── 写入 Langfuse scores ───────────────────────────────────────────
            if _langfuse_enabled and langfuse_client:
                for r in criterion_results:
                    langfuse_client.score_current_trace(
                        name=r["criterion"][:40],
                        value=1.0 if r.get("pass") else 0.0,
                        comment=r.get("reason", ""),
                    )
                langfuse_client.score_current_trace(name="overall", value=score)
                langfuse_client.score_current_trace(name="rule_pass", value=1.0 if rule_pass else 0.0)

            status = "✅" if (score >= 0.6 and rule_pass) else "❌"
            logger.info(
                "%s %s | 规则:%s | 标准:%d/%d | 得分:%.0f%%",
                status, tc_id,
                "✅" if rule_pass else "❌",
                pass_count, total_criteria,
                score * 100,
            )

            return EvalResult(
                tc_id=tc_id,
                scenario=scenario,
                difficulty=difficulty,
                priority=priority,
                pass_count=pass_count,
                total_criteria=total_criteria,
                rule_pass=rule_pass,
                score=score,
                reply=actual_reply,
                tool_calls=tool_calls_log,
                criterion_results=criterion_results,
                elapsed_ms=elapsed_ms,
                user_message=user_message,
                conversation_history=history,
            )

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("❌ %s 评估出错：%s", tc_id, exc, exc_info=True)
            if _langfuse_enabled and langfuse_client:
                langfuse_client.score_current_trace(name="overall", value=0.0)
                langfuse_client.score_current_trace(name="error", value=1.0, comment=str(exc))
            return EvalResult(
                tc_id=tc_id,
                scenario=scenario,
                difficulty=difficulty,
                priority=priority,
                pass_count=0,
                total_criteria=len(judge_criteria),
                rule_pass=False,
                score=0.0,
                reply="",
                error=str(exc),
                user_message=user_message,
                conversation_history=history,
            )


# ── 批量评估 ──────────────────────────────────────────────────────────────────
def run_all_cases(dataset: dict, pm: ProductManager, max_workers: int = 1) -> list[EvalResult]:
    test_cases = dataset.get("test_cases", [])
    total = len(test_cases)

    logger.info("=" * 60)
    logger.info("开始评估 %d 个测试用例（并发 max_workers=%d）", total, max_workers)
    logger.info("=" * 60)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_single_case, tc, pm): tc for tc in test_cases}
        for future in as_completed(futures):
            results.append(future.result())

    # 按原始顺序排序（as_completed 返回顺序不确定）
    order = {tc["id"]: i for i, tc in enumerate(test_cases)}
    results.sort(key=lambda r: order.get(r.tc_id, 999))
    return results


# ── 生成报告 ──────────────────────────────────────────────────────────────────
def generate_report(results: list[EvalResult], dataset: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"eval_{timestamp}.md"

    total = len(results)
    # 通过标准：score >= 0.6 且 rule_pass
    passed = sum(1 for r in results if r.score >= 0.6 and r.rule_pass and r.error is None)
    pass_rate = passed / total * 100 if total > 0 else 0

    # 耗时统计
    elapsed_values = [r.elapsed_ms for r in results if r.elapsed_ms > 0]
    avg_ms = int(sum(elapsed_values) / len(elapsed_values)) if elapsed_values else 0
    min_ms = min(elapsed_values) if elapsed_values else 0
    max_ms = max(elapsed_values) if elapsed_values else 0

    # 按 scenario 分组统计
    from collections import defaultdict
    scenario_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        scenario_stats[r.scenario]["total"] += 1
        if r.score >= 0.6 and r.rule_pass and r.error is None:
            scenario_stats[r.scenario]["passed"] += 1

    lines = [
        "# AI Budtender 评估报告",
        f"",
        f"日期：{datetime.now().strftime('%Y-%m-%d %H:%M')}　　总用例：{total}　　通过：{passed}　　通过率：{pass_rate:.0f}%",
        f"",
        f"响应耗时（budtender API）：平均 {avg_ms/1000:.1f}s　　最快 {min_ms/1000:.1f}s　　最慢 {max_ms/1000:.1f}s",
        f"",
        f"## 总览",
        f"",
        f"| Scenario | 总数 | 通过 | 通过率 |",
        f"|----------|------|------|--------|",
    ]

    for scenario, stats in sorted(scenario_stats.items()):
        t = stats["total"]
        p = stats["passed"]
        r = p / t * 100 if t > 0 else 0
        lines.append(f"| {scenario} | {t} | {p} | {r:.0f}% |")

    lines += ["", "## 详细结果", ""]

    for r in results:
        overall_ok = r.score >= 0.6 and r.rule_pass and r.error is None
        status_icon = "✅" if overall_ok else "❌"

        elapsed_str = f" | 耗时 {r.elapsed_ms/1000:.1f}s" if r.elapsed_ms > 0 else ""
        lines.append(f"### {r.tc_id} {status_icon} {r.scenario} / {r.difficulty} / {r.priority}{elapsed_str}")
        lines.append(f"")

        if r.error:
            lines.append(f"- **错误**：{r.error}")
            lines.append(f"")
            continue

        # 工具调用检查
        if r.tool_calls:
            calls_str = ", ".join(c["name"] for c in r.tool_calls)
            lines.append(f"- 工具调用检查：{'✅' if r.rule_pass else '❌'} {calls_str} 已调用")
        else:
            lines.append(f"- 工具调用检查：{'✅' if r.rule_pass else '❌'} 无工具调用")

        lines.append(f"- 判断标准（{r.pass_count}/{r.total_criteria} 通过，得分 {r.score:.0%}）：")

        for cr in r.criterion_results:
            icon = "✅" if cr.get("pass") else "❌"
            criterion = cr.get("criterion", "")
            reason = cr.get("reason", "")
            lines.append(f"  - {icon} {criterion} — \"{reason}\"")

        lines.append(f"")
        lines.append("<details><summary>完整对话</summary>")
        lines.append("")

        for msg in r.conversation_history:
            role_label = "**User**" if msg["role"] == "user" else "**AI**"
            lines.append(f"{role_label}: {msg['content']}")
            lines.append("")

        lines.append(f"**User**: {r.user_message}")
        lines.append("")
        lines.append(f"**AI**: {r.reply}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    report_content = "\n".join(lines)
    report_path.write_text(report_content, encoding="utf-8")
    logger.info("报告已生成：%s", report_path)
    return report_path


# ── 主入口 ────────────────────────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI Budtender 自动化评估")
    parser.add_argument("--tc", type=str, default=None, help="只运行指定 TC（例如 tc_007）")
    parser.add_argument("--series", type=str, default=None, help="只运行指定系列（例如 B，匹配 tc_B*）")
    args = parser.parse_args()

    # 1. 加载数据集
    if not DATASET_PATH.exists():
        logger.error("数据集文件不存在：%s", DATASET_PATH)
        sys.exit(1)

    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    logger.info("数据集版本：%s，共 %d 个用例", dataset.get("version"), dataset.get("total_cases"))

    # 2. 初始化 ProductManager
    if not DB_PATH.exists():
        logger.error("产品 DB 不存在：%s", DB_PATH)
        sys.exit(1)

    pm = ProductManager()
    pm.load(str(DB_PATH))
    logger.info("产品数据已加载：%d 条", pm.total_count)

    # 3. 过滤数据集（--tc 参数）
    if args.tc:
        test_cases = [tc for tc in dataset.get("test_cases", []) if tc["id"] == args.tc]
        if not test_cases:
            logger.error("TC '%s' 在数据集中不存在", args.tc)
            sys.exit(1)
        dataset = dict(dataset)
        dataset["test_cases"] = test_cases
        logger.info("单 TC 模式：只运行 %s", args.tc)

    if args.series:
        prefix = f"tc_{args.series.upper()}"
        test_cases = [tc for tc in dataset.get("test_cases", []) if tc["id"].startswith(prefix)]
        if not test_cases:
            logger.error("系列 '%s' 在数据集中没有匹配用例", args.series)
            sys.exit(1)
        dataset = dict(dataset)
        dataset["test_cases"] = test_cases
        logger.info("系列过滤：运行 %d 个 %s* 用例", len(test_cases), prefix)

    # 4. 运行所有测试用例
    results = run_all_cases(dataset, pm)

    # 4. 生成报告
    report_path = generate_report(results, dataset)

    # 5. 控制台汇总
    total = len(results)
    passed = sum(1 for r in results if r.score >= 0.6 and r.rule_pass and r.error is None)
    print(f"\n{'='*60}")
    print(f"评估完成：{passed}/{total} 通过（{passed/total*100:.0f}%）")
    print(f"报告路径：{report_path}")
    if _langfuse_enabled:
        print(f"Langfuse：{LANGFUSE_HOST}")
    print(f"{'='*60}\n")

    # 有任何失败则以非零退出码退出（方便 CI）
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
