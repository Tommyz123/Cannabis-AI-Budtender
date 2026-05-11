"""Central configuration management for AI Budtender."""

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
CSV_PATH: str = os.getenv("CSV_PATH", "data/NYE4.0_v3.csv")
DB_PATH: str = os.getenv("DB_PATH", "data/products.db")
MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-4o-mini")

# Langfuse observability — SDK reads LANGFUSE_HOST; .env may use LANGFUSE_BASE_URL
_langfuse_host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
os.environ["LANGFUSE_HOST"] = _langfuse_host

BEGINNER_THC_LIMITS: dict = {
    "edibles_mg": 5,
    "flower_percent": 20,
    "vaporizers_percent": 70,
}
