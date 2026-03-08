"""Central configuration management for AI Budtender."""

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
CSV_PATH: str = os.getenv("CSV_PATH", "data/NYE4.0_v3.csv")
MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-4o-mini")

BEGINNER_THC_LIMITS: dict = {
    "edibles_mg": 5,
    "flower_percent": 20,
    "vaporizers_percent": 70,
}
