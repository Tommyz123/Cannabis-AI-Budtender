"""FastAPI application entry point for AI Budtender."""

import base64
import json
import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from backend.models import ChatRequest, ChatResponse, UIAction
from backend.product_manager import ProductManager
from backend.llm_service import get_recommendation, get_recommendation_stream
from backend.router import get_simple_response
from backend.ui_action_builder import (
    build_top_picks,
    build_ui_action,
    build_ui_action_partial,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_product_manager = ProductManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load product CSV data on startup."""
    _product_manager.load()
    yield


app = FastAPI(title="AI Budtender API", version="1.0.0", lifespan=lifespan)

# Per-IP rate limit on the LLM-backed /chat endpoints. This is a demo cost
# guard: it caps how fast any single visitor can burn OpenAI tokens if the
# public URL gets scraped or shared widely. Limit is configurable via env so
# it can be tuned in the Render dashboard without a redeploy. Storage is
# in-memory (fine for a single free-tier instance); no external Redis needed.
_CHAT_RATE_LIMIT = os.getenv("CHAT_RATE_LIMIT", "20/minute")
limiter = Limiter(key_func=get_remote_address, default_limits=[])
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return a friendly 429 instead of the default plain text."""
    return Response(
        status_code=429,
        content=json.dumps({"detail": "Too many requests — please slow down and try again in a moment."}),
        media_type="application/json",
    )


_BASIC_USER = os.getenv("BASIC_AUTH_USER", "owner")
_BASIC_PASS = os.getenv("BASIC_AUTH_PASS", "")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not _BASIC_PASS:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8", "ignore")
                user, _, pw = decoded.partition(":")
                if user == _BASIC_USER and pw == _BASIC_PASS:
                    return await call_next(request)
            except Exception:
                pass
        return Response(
            status_code=401,
            content="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="AI Budtender"'},
        )


app.add_middleware(BasicAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    """Return service status and loaded product count."""
    return {
        "status": "ok",
        "products_loaded": _product_manager.total_count,
    }


@app.get("/products")
def list_products():
    """Return the full product catalog as compact dicts.

    Used by the two-pane storefront frontend to populate the product grid
    at page load. The list shape mirrors the `products` field returned by
    `smart_search`, including the optional `sale` / `disc` / `op` fields
    on products flagged as on-sale.
    """
    products = _product_manager.get_all_compact_list()
    return {"products": products, "total": len(products)}


@app.get("/filters")
def list_filters():
    """Return aggregate filter metadata for the HW-style sidebar.

    One round-trip on page load gives the frontend everything it needs to
    render categories, brands (with counts so it can sort/search), strain
    chips, effect checklist, and price/THC sliders. Counts reflect the full
    catalog — they don't shrink as the user narrows filters (HW behaves the
    same way to avoid the "0 results in 0 brands" dead-end).
    """
    return _product_manager.get_filter_metadata()


def _format_removed_filters(removed: dict[str, str]) -> str:
    """Compose a system-side UI signal describing chip × filter removals.

    Injected into the chat history as a single `role=system` message so
    the LLM can acknowledge the change and re-search without those
    constraints. We do NOT inject a synthetic user message — that would
    pollute conversation history and trigger compliance gating.
    """
    pairs = ", ".join(f"{k}={v}" for k, v in removed.items())
    return (
        f"[UI SIGNAL] The customer just removed these filters via the "
        f"chip × UI: {pairs}. Continue the conversation by acknowledging "
        f"the change and re-searching without those constraints."
    )


_COMPARE_SIGNAL_MARKER = "[UI SIGNAL] COMPARE_BY_ID:"


def _format_compare_request(product_ids: list[int]) -> str:
    """Compose a high-priority UI signal for compare-tray-driven comparisons.

    The storefront's compare tray sends the user-visible message ("Please
    compare these products: A, B, C.") to keep the chat readable, but the
    backend resolves the products by *ID* instead of free-text name. That
    avoids two pitfalls:
      1. `smart_search(query='A')` is a fuzzy substring across description /
         flavor / hardware → matches the wrong product.
      2. The agent loop dedups multiple `smart_search` calls in a single
         turn, so only the first of N products gets retrieved.

    `get_product_details(product_id='<id>')` has neither problem: it's an
    exact lookup with no dedup.
    """
    id_csv = ", ".join(str(pid) for pid in product_ids)
    return (
        f"{_COMPARE_SIGNAL_MARKER} {id_csv}.\n"
        f"The customer selected these specific products to compare from the "
        f"storefront UI. For each ID above, call "
        f"`get_product_details(product_id='<id>')` exactly once in this turn "
        f"to fetch fresh data. Then format a side-by-side comparison covering "
        f"name, brand, strain, THC, price, key effects, flavor, size, and "
        f"experience level. Do NOT call `smart_search` for this turn — fetch "
        f"by ID only."
    )


def _format_manual_filters(manual: dict) -> str:
    """Compose a low-priority UI signal describing the user's sidebar state.

    Unlike `removed_filters`, this is passive context — the user hasn't
    asked for a re-search, they just want the AI to be aware of which
    sidebar boxes are checked. The LLM should keep these constraints when
    suggesting products and may comment on them naturally ("Since you've
    filtered to Sativa, here are…") but should NOT replay them as a
    formal acknowledgment every turn.
    """
    # Render dict values concisely; lists become comma-joined.
    parts: list[str] = []
    for key, val in manual.items():
        if isinstance(val, list):
            if val:
                parts.append(f"{key}={','.join(str(v) for v in val)}")
        elif val not in (None, "", False):
            parts.append(f"{key}={val}")
    if not parts:
        return ""
    return (
        f"[UI CONTEXT] The customer has these filters set in the storefront "
        f"sidebar: {'; '.join(parts)}. Honor them silently when recommending "
        f"products; do not announce them back to the customer unless asked."
    )


@app.post("/chat", response_model=ChatResponse)
@limiter.limit(_CHAT_RATE_LIMIT)
def chat(request: Request, chat_request: ChatRequest):
    """
    Handle a chat turn and return the AI recommendation.
    Passes is_beginner flag to LLM session context when set.

    ``request`` (Starlette) is required by the rate limiter for per-IP keying; it is
    otherwise unused in the handler body.
    """
    user_message = chat_request.user_message
    has_removed_filters = bool(chat_request.removed_filters)

    # A chip-× turn with no typed text is legitimate: the customer didn't
    # speak, they clicked. Treat it as a non-empty input downstream so the
    # LLM service has something to work with, but only when the UI signal
    # accompanies it. If BOTH fields are empty, reject as before.
    if not user_message.strip():
        if not has_removed_filters:
            raise HTTPException(status_code=400, detail="user_message cannot be empty")
        user_message = "(removed filters via UI)"

    # Fast path: simple greetings/closings skip LLM entirely.
    # Bypass the fast path when removed_filters is set so the LLM can
    # acknowledge the change and re-search (router fast-path doesn't
    # understand UI signals — see R18 in the execution plan).
    if not has_removed_filters:
        simple = get_simple_response(user_message)
        if simple:
            logger.info("session=%s fast_path=True", chat_request.session_id)
            return ChatResponse(
                reply=simple,
                session_id=chat_request.session_id,
                response_time_ms=0.0,
            )

    history = [{"role": m.role, "content": m.content} for m in chat_request.messages]

    if has_removed_filters:
        history = history + [
            {"role": "system", "content": _format_removed_filters(chat_request.removed_filters)}
        ]

    if chat_request.manual_filters:
        manual_signal = _format_manual_filters(chat_request.manual_filters)
        if manual_signal:
            history = history + [
                {"role": "system", "content": manual_signal}
            ]

    if chat_request.compare_product_ids:
        history = history + [
            {"role": "system", "content": _format_compare_request(chat_request.compare_product_ids)}
        ]

    trace: dict = {}
    try:
        t_start = time.perf_counter()
        reply = get_recommendation(
            history,
            user_message,
            _product_manager,
            is_beginner=chat_request.is_beginner,
            trace=trace,
        )
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ui_action_dict = build_ui_action(trace, reply, _product_manager)
    ui_action = UIAction(**ui_action_dict) if ui_action_dict else None

    logger.info("session=%s response_time_ms=%.1f", chat_request.session_id, elapsed_ms)
    return ChatResponse(
        reply=reply,
        session_id=chat_request.session_id,
        response_time_ms=elapsed_ms,
        ui_action=ui_action,
    )


@app.post("/chat/stream")
@limiter.limit(_CHAT_RATE_LIMIT)
def chat_stream(request: Request, chat_request: ChatRequest):
    """Streaming version of /chat. Returns text/event-stream (SSE).

    ``request`` (Starlette) is required by the rate limiter for per-IP keying; it is
    otherwise unused in the handler body.

    SSE protocol (typed events):

      event: ui_action      ← emitted once, immediately after smart_search
      data: {filters, total_matched, picks:[], spoken_product_ids:[]}
                              picks is always empty here; the dedicated
                              picks event below carries the real Top Picks.

      data: {"chunk": "..."}                ← repeated, the streamed reply

      event: spoken         ← emitted once after streaming completes,
      data: [int, int, ...]   carrying the ordered list of product ids
                              whose names appeared in the reply

      event: picks          ← emitted once after streaming completes,
      data: [{id, pick_reason, ...}, ...]
                              Top Pick row content, ordered to match the
                              AI's mentions; reasons assigned by the
                              7-tier labeling algorithm. Only emitted
                              when at least one spoken id was found.

      data: [DONE]          ← final sentinel

    Greeting / info-gathering turns (no smart_search) skip the ui_action,
    spoken, and picks events. Fast-path simple replies skip them too.

    Honors the same ``removed_filters`` and ``manual_filters`` UI signals
    as the non-streaming ``/chat`` endpoint.
    """
    user_message = chat_request.user_message
    has_removed_filters = bool(chat_request.removed_filters)

    # Same chip-× allowance as /chat: empty user_message is OK iff a UI
    # signal accompanies it.
    if not user_message.strip():
        if not has_removed_filters:
            raise HTTPException(status_code=400, detail="user_message cannot be empty")
        user_message = "(removed filters via UI)"

    # Fast path: simple greetings skip LLM entirely — return as single chunk
    # and no ui_action (no smart_search happened).
    if not has_removed_filters:
        simple = get_simple_response(user_message)
        if simple:
            def _simple_gen():
                yield f"data: {json.dumps({'chunk': simple})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(_simple_gen(), media_type="text/event-stream")

    history = [{"role": m.role, "content": m.content} for m in chat_request.messages]

    if has_removed_filters:
        history = history + [
            {"role": "system", "content": _format_removed_filters(chat_request.removed_filters)}
        ]

    if chat_request.manual_filters:
        manual_signal = _format_manual_filters(chat_request.manual_filters)
        if manual_signal:
            history = history + [
                {"role": "system", "content": manual_signal}
            ]

    if chat_request.compare_product_ids:
        history = history + [
            {"role": "system", "content": _format_compare_request(chat_request.compare_product_ids)}
        ]

    def generate():
        trace: dict = {}
        ui_action_emitted = False
        reply_buf: list[str] = []

        def _emit_ui_action_if_ready():
            nonlocal ui_action_emitted
            if ui_action_emitted:
                return None
            if "last_smart_search" not in trace:
                return None
            payload = build_ui_action_partial(trace, _product_manager)
            if payload is None:
                return None
            ui_action_emitted = True
            return (
                f"event: ui_action\n"
                f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            )

        try:
            for chunk in get_recommendation_stream(
                history,
                user_message,
                _product_manager,
                is_beginner=chat_request.is_beginner,
                trace=trace,
            ):
                # Best-effort: emit ui_action as soon as the trace shows tool
                # results — usually before the very first text chunk lands.
                pre = _emit_ui_action_if_ready()
                if pre:
                    yield pre
                reply_buf.append(chunk)
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"

            # In case all tool work landed in the final chunk's iteration
            # (e.g. fast-path single-shot), try once more after the generator
            # has exhausted.
            late = _emit_ui_action_if_ready()
            if late:
                yield late

            # Reply done — emit the Top Picks. Picks are chosen
            # deterministically from the products smart_search returned this
            # turn (ranked by score_picks), NOT by scanning the reply text, so
            # a card can never surface a product that was not retrieved.
            if ui_action_emitted:
                picks = build_top_picks(trace, _product_manager)
                if picks:
                    ids = [p["id"] for p in picks if p.get("id") is not None]
                    yield (
                        f"event: spoken\n"
                        f"data: {json.dumps(ids, separators=(',', ':'))}\n\n"
                    )
                    yield (
                        f"event: picks\n"
                        f"data: {json.dumps(picks, separators=(',', ':'))}\n\n"
                    )
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


app.mount(
    "/",
    StaticFiles(directory="frontend", html=True),
    name="frontend",
)
