"""Pydantic request and response models for AI Budtender API."""

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single chat message with role and content."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")


class UIAction(BaseModel):
    """Structured UI update payload returned alongside a chat reply.

    Built by `backend.ui_action_builder.build_ui_action` from the trace
    populated by `get_recommendation`. The frontend consumes this to update
    filter chips, the product grid, the Top Pick row, and the "spoken"
    product highlights — all without parsing the reply text itself.

    All fields default to empty/zero so the model can be safely instantiated
    even when only a partial UI update is appropriate.
    """

    filters: dict = Field(
        default_factory=dict,
        description="Active filters to render as chips (whitelisted smart_search args).",
    )
    picks: list[dict] = Field(
        default_factory=list,
        description="Up to 3 Top Pick products with attached pick_reason.",
    )
    spoken_product_ids: list[int] = Field(
        default_factory=list,
        description="Product ids whose names appeared in the reply, in order of mention.",
    )
    total_matched: int = Field(
        default=0,
        description="Total number of products matching the active filter set.",
    )


class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    session_id: str = Field(..., description="UUID session identifier")
    messages: list[Message] = Field(
        default_factory=list,
        description="Conversation history (max 20 messages)",
    )
    user_message: str = Field(..., description="Current user message text")
    is_beginner: bool = Field(default=False, description="True if customer is a first-time/beginner user")
    removed_filters: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Filters the customer just removed via the chip × UI. Keys are "
            "the smart_search arg names ('category', 'strain_type', 'effects', "
            "'max_price'); values are the removed filter value. The backend "
            "uses this to compose a system instruction for the LLM rather "
            "than injecting a synthetic user message into the history."
        ),
    )
    manual_filters: dict = Field(
        default_factory=dict,
        description=(
            "Filters the customer has set manually via the sidebar UI "
            "(brand, strain_type, category, effects, max_price, max_thc, "
            "on_sale). Sent on every /chat call so the AI is aware of the "
            "user's manual constraints and can reason about them in replies "
            "without overwriting them. The backend injects a single system "
            "message describing these filters; it does not push a synthetic "
            "user message and does not bypass the fast path."
        ),
    )
    compare_product_ids: list[int] = Field(
        default_factory=list,
        description=(
            "Product IDs the customer wants to compare side-by-side, set by "
            "the storefront compare tray's 'Compare in chat' button. When "
            "non-empty, the backend instructs the LLM to call "
            "`get_product_details` once per ID (rather than `smart_search` "
            "with free-text names, which is fuzzy and capped by the agent "
            "loop's one-search-per-turn dedup). This bypasses the "
            "`is_product_comparison` smart_search injection in llm_service."
        ),
    )


class ChatResponse(BaseModel):
    """Response body for POST /chat."""

    reply: str = Field(..., description="AI assistant reply text")
    session_id: str = Field(..., description="Echo of the session identifier")
    response_time_ms: float = Field(..., description="Total response time in milliseconds")
    ui_action: UIAction | None = Field(
        default=None,
        description=(
            "Optional structured UI update for the two-pane storefront. "
            "Present when the turn ran a smart_search; null for "
            "greeting / info-gathering turns."
        ),
    )
