"""Build the ui_action payload returned alongside chat replies.

Consumes the `trace` dict populated by `llm_service.get_recommendation`
(out-param pattern) and produces the structured payload the frontend uses
to update its product grid, filter chips, and "spoken" product highlights.

The builder is intentionally side-effect free and stateless; everything it
needs comes from the trace and the provided `product_manager`.

Recommendations are a SINGLE deterministic list chosen from the products
``smart_search`` returned this turn (the top N by relevance). That one list
drives BOTH:

  * the "Best Matches" cards shown in the storefront, and
  * (via ``llm_service``) the products the assistant is instructed to talk
    about in its reply.

Because the cards and the prose are built from the same backend-chosen list,
"what the assistant recommends == what the storefront displays" is true by
construction — there is no prose-scanning step that could mis-attribute or
diverge, and the count is bounded to ``REC_MIN``..``REC_MAX``.
"""

# The Best Matches / recommendation list is capped to this many products, and
# we aim to surface at least REC_MIN when the search returned that many.
REC_MAX = 6
REC_MIN = 3
# Back-compat alias for the old constant name.
TOP_PICK_LIMIT = REC_MAX

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

    Top Picks are selected deterministically from the products that
    ``smart_search`` returned this turn, ranked by
    ``ProductManager.score_picks``. ``reply_text`` is accepted for API
    compatibility but is no longer scanned — picks no longer depend on the
    assistant's prose, so a card can never surface a product that was not
    retrieved.

    Args:
        trace: The out-param dict populated by `get_recommendation`. Expected
            keys: `last_smart_search` (with `args` and `result`) and `profile`.
        reply_text: Unused; retained for backward-compatible call sites.
        product_manager: ProductManager instance used to rank Top Picks.

    Returns:
        A dict with `filters`, `picks`, `spoken_product_ids`, and
        `total_matched`, or `None` when no smart_search ran this turn.
    """
    partial = build_ui_action_partial(trace, product_manager)
    if partial is None:
        return None
    picks = build_top_picks(trace, product_manager)
    partial["picks"] = picks
    partial["spoken_product_ids"] = [
        p["id"] for p in picks if p.get("id") is not None
    ]
    return partial


def build_ui_action_partial(
    trace: dict,
    product_manager,
) -> dict | None:
    """Like ``build_ui_action`` but without picks or spoken ids.

    Used by the streaming endpoint, which knows the filters the moment
    ``smart_search`` resolves but cannot determine picks until the full
    reply text is available (picks are derived from the AI's spoken
    product ids). The streaming endpoint emits this partial payload
    first (so the storefront can animate chips/grid immediately) and
    follows up with ``spoken`` + ``picks`` events once the reply is
    complete.

    ``picks`` is always an empty list here; the streaming endpoint emits
    a separate ``picks`` event after the reply finishes.

    Returns ``None`` when no smart_search ran this turn.
    """
    last = trace.get("last_smart_search")
    if not last:
        return None

    args = last.get("args", {}) or {}
    result = last.get("result", {}) or {}

    visible_filters = {
        k: v for k, v in args.items() if k in VISIBLE_FILTER_FIELDS and v
    }

    return {
        "filters": visible_filters,
        "picks": [],
        "spoken_product_ids": [],
        "total_matched": result.get("total", 0),
    }


def _retrieved_products(trace: dict) -> list[dict]:
    """Return this turn's smart_search result products (already sorted)."""
    last = trace.get("last_smart_search")
    if not last:
        return []
    return (last.get("result") or {}).get("products", []) or []


# Key under which backfilled product ids are recorded on the trace, so the
# card labeler can tag them "Similar option".
_BACKFILL_KEY = "_backfilled_ids"
# pick_reason shown on same-category backfill products (see _backfill_to_min).
SIMILAR_OPTION_REASON = "Similar option"


def _backfill_to_min(trace: dict, product_manager, selected: list[dict]) -> list[dict]:
    """Top the recommendation list up to ``REC_MIN`` from the same category.

    When the strict search matched fewer than ``REC_MIN`` products, pad the
    list with additional products from the SAME category (relevance-sorted,
    excluding those already selected) so the Best Matches row always shows at
    least ``REC_MIN``. Backfilled products are appended to the trace's product
    list (so cards / the assistant directive can reference them) and their ids
    are recorded under ``trace[_BACKFILL_KEY]`` so they can be labeled as a
    "Similar option" rather than a strict match.

    Returns the (possibly extended) selected list. A no-op when the strict
    result already has ``REC_MIN``, the category is unknown, or the strict
    search matched nothing at all (0 matches is a genuine no-results state —
    we surface a broadened list only to *pad a thin real result*, never to
    fabricate recommendations for a query that matched nothing).
    """
    if not selected or len(selected) >= REC_MIN:
        return selected
    last = trace.get("last_smart_search") or {}
    category = (last.get("args") or {}).get("category")
    if not category:
        return selected

    try:
        extra = product_manager.search_products(category=category, limit=REC_MAX)
    except Exception:  # noqa: BLE001 — backfill is best-effort
        return selected

    have = {p.get("id") for p in selected}
    result_products = (last.get("result") or {}).get("products", []) or []
    backfilled = list(trace.get(_BACKFILL_KEY) or [])
    for prod in (extra.get("products") or []):
        if len(selected) >= REC_MIN:
            break
        pid = prod.get("id")
        if pid is None or pid in have:
            continue
        have.add(pid)
        selected.append(prod)
        result_products.append(prod)      # make it visible to cards + directive
        backfilled.append(pid)
    # Persist the augmented product list and backfill markers back onto trace.
    trace.setdefault("last_smart_search", {}).setdefault("result", {})["products"] = result_products
    trace[_BACKFILL_KEY] = backfilled
    return selected


def select_recommendation_ids(trace: dict, product_manager=None) -> list[int]:
    """Pick the single deterministic recommendation list for this turn.

    Takes the top ``REC_MAX`` products from the (relevance-sorted)
    smart_search result — the same ordering the product grid uses. This one
    list is the source of truth for BOTH the Best Matches cards and the
    products the assistant is told to recommend, so the two can never
    disagree.

    When ``product_manager`` is supplied and the strict result has fewer than
    ``REC_MIN`` products, the list is padded from the same category (marked as
    "Similar option") so the row always shows at least ``REC_MIN``.

    Returns product ids in display order. Empty when no smart_search ran or it
    returned nothing.
    """
    products = _retrieved_products(trace)
    selected = [p for p in products[:REC_MAX] if p.get("id") is not None]
    if product_manager is not None:
        selected = _backfill_to_min(trace, product_manager, selected)
    return [p["id"] for p in selected]


def build_top_picks(trace: dict, product_manager) -> list[dict]:
    """Build the Best Matches cards for this turn's recommendation list.

    The card set is exactly ``select_recommendation_ids(trace, product_manager)``
    — the top-N retrieved products (padded to ``REC_MIN`` from the same
    category when needed) — each labeled with a ``pick_reason``. Backfilled
    products are labeled ``SIMILAR_OPTION_REASON``. Deterministic and drawn
    only from products present in the trace, so a card can never surface a
    product the assistant wasn't also told about. Empty when no smart_search
    ran or it returned nothing.
    """
    ids = select_recommendation_ids(trace, product_manager)
    if not ids:
        return []
    filtered_products = _retrieved_products(trace)
    profile = trace.get("profile", {}) or {}
    picks = product_manager.assign_pick_reasons(filtered_products, profile, ids)
    backfilled = set(trace.get(_BACKFILL_KEY) or [])
    if backfilled:
        for p in picks:
            if p.get("id") in backfilled:
                p["pick_reason"] = SIMILAR_OPTION_REASON
    return picks
