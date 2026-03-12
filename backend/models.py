"""Pydantic request and response models for AI Budtender API."""

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single chat message with role and content."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")


class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    session_id: str = Field(..., description="UUID session identifier")
    messages: list[Message] = Field(
        default_factory=list,
        description="Conversation history (max 20 messages)",
    )
    user_message: str = Field(..., description="Current user message text")
    is_beginner: bool = Field(default=False, description="True if customer is a first-time/beginner user")


class ChatResponse(BaseModel):
    """Response body for POST /chat."""

    reply: str = Field(..., description="AI assistant reply text")
    session_id: str = Field(..., description="Echo of the session identifier")
    response_time_ms: float = Field(..., description="Total response time in milliseconds")
