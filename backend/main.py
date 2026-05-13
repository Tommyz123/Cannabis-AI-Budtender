"""FastAPI application entry point for AI Budtender."""

import json
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from backend.models import ChatRequest, ChatResponse, UIAction
from backend.product_manager import ProductManager
from backend.llm_service import get_recommendation, get_recommendation_stream
from backend.router import get_simple_response
from backend.ui_action_builder import build_ui_action

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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Handle a chat turn and return the AI recommendation.
    Passes is_beginner flag to LLM session context when set.
    """
    user_message = request.user_message
    has_removed_filters = bool(request.removed_filters)

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
            logger.info("session=%s fast_path=True", request.session_id)
            return ChatResponse(
                reply=simple,
                session_id=request.session_id,
                response_time_ms=0.0,
            )

    history = [{"role": m.role, "content": m.content} for m in request.messages]

    if has_removed_filters:
        history = history + [
            {"role": "system", "content": _format_removed_filters(request.removed_filters)}
        ]

    trace: dict = {}
    try:
        t_start = time.perf_counter()
        reply = get_recommendation(
            history,
            user_message,
            _product_manager,
            is_beginner=request.is_beginner,
            trace=trace,
        )
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ui_action_dict = build_ui_action(trace, reply, _product_manager)
    ui_action = UIAction(**ui_action_dict) if ui_action_dict else None

    logger.info("session=%s response_time_ms=%.1f", request.session_id, elapsed_ms)
    return ChatResponse(
        reply=reply,
        session_id=request.session_id,
        response_time_ms=elapsed_ms,
        ui_action=ui_action,
    )


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """
    Streaming version of /chat. Returns text/event-stream (SSE).
    Each event: data: {"chunk": "..."}\n\n
    Final event: data: [DONE]\n\n
    """
    if not request.user_message.strip():
        raise HTTPException(status_code=400, detail="user_message cannot be empty")

    # Fast path: simple greetings skip LLM entirely — return as single chunk
    simple = get_simple_response(request.user_message)
    if simple:
        def _simple_gen():
            yield f"data: {json.dumps({'chunk': simple})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_simple_gen(), media_type="text/event-stream")

    history = [{"role": m.role, "content": m.content} for m in request.messages]

    def generate():
        try:
            for chunk in get_recommendation_stream(
                history,
                request.user_message,
                _product_manager,
                is_beginner=request.is_beginner,
            ):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
