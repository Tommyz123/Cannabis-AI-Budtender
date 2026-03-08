"""FastAPI application entry point for AI Budtender."""

import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from backend.models import ChatRequest, ChatResponse
from backend.product_manager import ProductManager
from backend.llm_service import get_recommendation, get_simple_response

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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Handle a chat turn and return the AI recommendation.

    Selects the product set based on is_beginner flag,
    then calls the LLM to generate a reply.
    """
    if not request.user_message.strip():
        raise HTTPException(status_code=400, detail="user_message cannot be empty")

    # Fast path: simple greetings/closings skip LLM entirely
    simple = get_simple_response(request.user_message)
    if simple:
        logger.info("session=%s fast_path=True", request.session_id)
        return ChatResponse(reply=simple, session_id=request.session_id, response_time_ms=0.0)

    history = [{"role": m.role, "content": m.content} for m in request.messages]

    try:
        t_start = time.perf_counter()
        reply = get_recommendation(history, request.user_message, _product_manager, is_beginner=request.is_beginner)
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info("session=%s response_time_ms=%.1f", request.session_id, elapsed_ms)
    return ChatResponse(reply=reply, session_id=request.session_id, response_time_ms=elapsed_ms)
