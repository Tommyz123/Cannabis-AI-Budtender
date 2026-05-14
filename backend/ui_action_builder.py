"""Build the ui_action payload returned alongside chat replies.

Consumes the `trace` dict populated by `llm_service.get_recommendation`
(out-param pattern) and produces the structured payload the frontend uses
to update its product grid, filter chips, and "spoken" product highlights.

The builder is intentionally side-effect free and stateless; everything it
needs comes from the trace and the provided `product_manager`.
"""

import re

# Whitelist of smart_search args that map to user-visible filter chips.
# Deliberately EXCLUDES `is_beginner` (session attribute, not a chip) and
# `hardware_type` (not in TOOLS_SCHEMA — derived field on results).
VISIBLE_FILTER_FIELDS = {"category", "strain_type", "effects", "max_price"}


def build_ui_action(
    trace: dict,
    reply_text: str,
    product_manager,
) -> dict | None:
    """Construct the full ui_action dict from a populated trace.

    Args:
        trace: The out-param dict populated by `get_recommendation`. Expected
            keys: `last_smart_search` (with `args` and `result`) and `profile`.
        reply_text: Final assistant reply, scanned for product-name mentions.
        product_manager: ProductManager instance used to score Top Picks.

    Returns:
        A dict with `filters`, `picks`, `spoken_product_ids`, and
        `total_matched`, or `None` when no smart_search ran this turn.
    """
    partial = build_ui_action_partial(trace, product_manager)
    if partial is None:
        return None
    last = trace.get("last_smart_search", {}) or {}
    filtered_products = (last.get("result") or {}).get("products", []) or []
    partial["spoken_product_ids"] = _scan_reply_for_product_ids(
        reply_text, filtered_products
    )
    return partial


def build_ui_action_partial(
    trace: dict,
    product_manager,
) -> dict | None:
    """Like ``build_ui_action`` but without the spoken-product-name scan.

    Used by the streaming endpoint, which knows the filters and picks the
    moment ``smart_search`` resolves but doesn't have the full reply text
    until streaming completes. The streaming endpoint emits this partial
    payload first (so the storefront can animate chips/grid/picks
    immediately) and follows up with a ``spoken`` event once the reply is
    complete (see ``scan_spoken_product_ids``).

    Returns ``None`` when no smart_search ran this turn.
    """
    last = trace.get("last_smart_search")
    if not last:
        return None

    profile = trace.get("profile", {}) or {}
    args = last.get("args", {}) or {}
    result = last.get("result", {}) or {}

    visible_filters = {
        k: v for k, v in args.items() if k in VISIBLE_FILTER_FIELDS and v
    }
    filtered_products = result.get("products", []) or []
    picks = product_manager.score_picks(filtered_products, profile, limit=3)

    return {
        "filters": visible_filters,
        "picks": picks,
        "spoken_product_ids": [],
        "total_matched": result.get("total", 0),
    }


def scan_spoken_product_ids(reply_text: str, trace: dict) -> list[int]:
    """Scan the final reply text for product-name mentions.

    The complement to ``build_ui_action_partial`` for the streaming flow:
    once the assistant reply is fully streamed, this returns the ordered
    list of product ids the reply mentioned (so the storefront can pulse
    those cards). Returns an empty list if no smart_search ran or the
    reply mentions no candidate names.
    """
    last = trace.get("last_smart_search")
    if not last:
        return []
    filtered_products = (last.get("result") or {}).get("products", []) or []
    return _scan_reply_for_product_ids(reply_text, filtered_products)


def _scan_key(name: str) -> str:
    """Return the first pipe-separated segment of a product name, stripped.

    Example: ``"Half & Half | UP | 10mg"`` → ``"Half & Half"``.
    The LLM rarely reproduces the full SKU-laden product name verbatim,
    so we scan against the leading segment instead.
    """
    return name.split("|", 1)[0].strip()


def _scan_reply_for_product_ids(reply: str, candidates: list[dict]) -> list[int]:
    """Find product ids whose name (or first |-segment) appears in the reply.

    Uses non-word-character lookarounds rather than ``\\b`` so the scan
    tolerates flanking markdown/punctuation: ``&``, ``|``, ``*`` (markdown
    bold), spaces, etc. all satisfy the lookaround.

    Returns ids ordered by first appearance in the reply, deduped.
    """
    if not reply:
        return []

    hits: list[tuple[int, int]] = []
    seen: set[int] = set()
    for prod in candidates:
        full_name = prod.get("s", "")
        if not full_name:
            continue
        key = _scan_key(full_name)
        if not key:
            continue
        pattern = re.compile(
            rf"(?<!\w){re.escape(key)}(?!\w)",
            re.IGNORECASE,
        )
        m = pattern.search(reply)
        pid = prod.get("id")
        if m and pid is not None and pid not in seen:
            hits.append((m.start(), pid))
            seen.add(pid)
    hits.sort(key=lambda h: h[0])
    return [pid for _, pid in hits]
