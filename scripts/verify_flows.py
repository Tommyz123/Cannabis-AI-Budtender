"""HTTP-level self-verification of the four spec-D flows.

Runs against a live backend on http://localhost:8000 (override with --base).
Does NOT require a browser. The LLM-dependent flows (B, C, D) gracefully
skip when OPENAI_API_KEY is missing or the backend returns 502.

Flows:
  A — Cold load            (GET /products)
  B — Stepwise filter      (POST /chat "I want sativa flower")
  C — Change mind          (POST /chat "actually, indica" with history)
  D — Chip removal         (POST /chat with removed_filters)
  E — Cart                 (frontend-only; documented as skipped)

Exit code: 0 if all attempted flows pass, 1 if any fail (skipped counts as pass).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import urllib.error
import urllib.request


# ── Colored output helpers (degrade to plain text when not a TTY) ──────────────

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _USE_COLOR else s


PASS = lambda s: _c("32", f"PASS  {s}")
FAIL = lambda s: _c("31", f"FAIL  {s}")
SKIP = lambda s: _c("33", f"SKIP  {s}")
INFO = lambda s: _c("36", s)


# ── HTTP helpers ───────────────────────────────────────────────────────────────


def get_json(url: str, timeout: float = 5.0) -> tuple[int, dict | None]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return 0, None


def post_json(url: str, body: dict, timeout: float = 30.0) -> tuple[int, dict | None]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body_text = e.read().decode("utf-8")
            return e.code, json.loads(body_text) if body_text else None
        except Exception:
            return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return 0, None


# ── Flow checks ────────────────────────────────────────────────────────────────


def flow_a_cold_load(base: str) -> bool:
    print(INFO("\n[A] Cold load — GET /products"))
    status, data = get_json(f"{base}/products")
    if status != 200 or not data:
        print(FAIL(f"  GET /products returned {status}"))
        return False
    total = data.get("total", 0)
    products = data.get("products", [])
    sale_count = sum(1 for p in products if p.get("sale"))
    has_disc = all("disc" in p for p in products if p.get("sale"))
    has_no_op = all("op" not in p for p in products)
    ok = total == 217 and len(products) == 217 and sale_count >= 1 and has_disc and has_no_op
    print(
        f"  total={total}, sale_count={sale_count}, disc_on_each_sale={has_disc}, "
        f"no_fabricated_op={has_no_op}"
    )
    if ok:
        print(PASS("  Flow A"))
    else:
        print(FAIL("  Flow A — expected total=217, sale_count>=1, disc on every sale item, no op"))
    return ok


def flow_b_stepwise_filter(base: str, has_llm: bool) -> bool:
    print(INFO("\n[B] Stepwise filter — POST /chat 'I want sativa flower'"))
    if not has_llm:
        print(SKIP("  Flow B (no OPENAI_API_KEY)"))
        return True

    status, data = post_json(
        f"{base}/chat",
        {
            "session_id": "verify-B",
            "messages": [],
            "user_message": "I want sativa flower",
        },
        timeout=60.0,
    )
    if status == 502:
        print(SKIP("  Flow B (backend got 502 — LLM unreachable)"))
        return True
    if status != 200 or not data:
        print(FAIL(f"  POST /chat returned {status}: {data}"))
        return False
    ua = data.get("ui_action")
    if ua is None:
        print(FAIL("  ui_action is null — expected filters/picks/etc"))
        return False
    filters = ua.get("filters") or {}
    picks = ua.get("picks") or []
    total = ua.get("total_matched", 0)
    print(f"  filters={filters}")
    print(f"  picks={[(p.get('id'), (p.get('s') or '')[:30], p.get('pick_reason')) for p in picks]}")
    print(f"  total_matched={total}")
    # Lenient assertions: LLM may interpret "sativa flower" various ways
    ok = bool(filters) and total > 0
    if ok:
        print(PASS("  Flow B"))
    else:
        print(FAIL("  Flow B — expected non-empty filters + total_matched > 0"))
    return ok


def flow_c_change_mind(base: str, has_llm: bool) -> bool:
    print(INFO("\n[C] Change mind — POST /chat 'actually, indica' with history"))
    if not has_llm:
        print(SKIP("  Flow C (no OPENAI_API_KEY)"))
        return True

    history = [
        {"role": "user", "content": "I want sativa flower"},
        {
            "role": "assistant",
            "content": "Here are some great sativa flower options for you.",
        },
    ]
    status, data = post_json(
        f"{base}/chat",
        {
            "session_id": "verify-C",
            "messages": history,
            "user_message": "actually, indica",
        },
        timeout=60.0,
    )
    if status == 502:
        print(SKIP("  Flow C (502)"))
        return True
    if status != 200 or not data:
        print(FAIL(f"  POST /chat returned {status}"))
        return False
    ua = data.get("ui_action") or {}
    filters = ua.get("filters") or {}
    print(f"  filters={filters}")
    # LLM should now search Indica, not Sativa
    strain = (filters.get("strain_type") or "").lower()
    ok = "indica" in strain or "indica" in str(filters).lower()
    if ok:
        print(PASS("  Flow C"))
    else:
        print(FAIL("  Flow C — expected strain_type Indica in filters"))
    return ok


def flow_d_chip_removal(base: str, has_llm: bool) -> bool:
    print(INFO("\n[D] Chip × removal — POST /chat removed_filters only"))

    # Sub-check D1: backend rejects when BOTH user_message and removed_filters empty
    status_empty, _ = post_json(
        f"{base}/chat",
        {"session_id": "verify-D1", "messages": [], "user_message": ""},
    )
    print(f"  D1 (empty/empty): status={status_empty} (expect 400)")
    if status_empty != 400:
        print(FAIL("  Flow D1 — expected 400 for empty user_message + no removed_filters"))
        return False

    if not has_llm:
        print(SKIP("  Flow D2 (LLM portion) — no OPENAI_API_KEY"))
        print(PASS("  Flow D (D1 passed; D2 skipped)"))
        return True

    # Sub-check D2: with removed_filters, request is accepted and reaches LLM
    history = [
        {"role": "user", "content": "I want sativa flower"},
        {"role": "assistant", "content": "Here are some sativa flowers..."},
    ]
    status, data = post_json(
        f"{base}/chat",
        {
            "session_id": "verify-D2",
            "messages": history,
            "user_message": "",
            "removed_filters": {"strain_type": "Sativa"},
        },
        timeout=60.0,
    )
    if status == 502:
        print(SKIP("  Flow D2 (502)"))
        return True
    if status != 200 or not data:
        print(FAIL(f"  D2 POST /chat returned {status}"))
        return False
    reply = data.get("reply", "")
    print(f"  reply preview: {reply[:120]!r}")
    ok = len(reply) > 10
    if ok:
        print(PASS("  Flow D"))
    else:
        print(FAIL("  Flow D — expected non-trivial reply text"))
    return ok


def flow_e_cart_note() -> bool:
    print(INFO("\n[E] Cart"))
    print(SKIP("  Flow E (frontend-only — verify in browser by clicking Add)"))
    return True


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Force-skip LLM-dependent flows even if API key is set",
    )
    args = parser.parse_args()

    # Probe backend
    status, data = get_json(f"{args.base}/health")
    if status != 200:
        print(FAIL(f"\nBackend not reachable at {args.base}/health (status={status})"))
        print(INFO("Start it with: ./scripts/run_local.sh"))
        return 1
    print(INFO(f"Backend healthy: {data}"))

    has_llm = bool(os.getenv("OPENAI_API_KEY")) and not args.skip_llm
    if not has_llm:
        print(INFO("OPENAI_API_KEY not set (or --skip-llm given) — LLM flows will be SKIPPED"))

    results = []
    results.append(("A Cold load", flow_a_cold_load(args.base)))
    results.append(("B Stepwise filter", flow_b_stepwise_filter(args.base, has_llm)))
    results.append(("C Change mind", flow_c_change_mind(args.base, has_llm)))
    results.append(("D Chip removal", flow_d_chip_removal(args.base, has_llm)))
    results.append(("E Cart", flow_e_cart_note()))

    print(INFO("\n=== Summary ==="))
    failed = 0
    for name, ok in results:
        marker = "OK" if ok else "FAIL"
        print(f"  [{marker}] {name}")
        if not ok:
            failed += 1
    print()
    if failed == 0:
        print(PASS(f"All {len(results)} flows OK (skipped count as OK)"))
        return 0
    print(FAIL(f"{failed} of {len(results)} flows FAILED"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
