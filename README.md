# AI Budtender

An embeddable AI chat widget that helps cannabis dispensary customers find the right product through multi-turn conversation — with built-in safety guardrails for first-time users.

---

## Features

- **Conversational Recommendations** — Understands customer needs through multi-turn dialogue (effects, budget, time of day, activity) and recommends the best-matched products from live inventory.
- **Beginner Safety Mode** — Enforces THC limits (edibles ≤ 5 mg, flower ≤ 20%, vaporizers ≤ 70%) when `is_beginner: true` is passed in the request. The LLM receives a session-level context injection so it never asks the customer again and always applies beginner filters throughout the conversation.
- **Agent Loop with Tool Calling** — Uses OpenAI function calling to run `smart_search` and `get_product_details` against a 217-product catalog, enabling precise, multi-criteria filtering without injecting the full dataset into every prompt.
- **Rich Free-Text Search** — `smart_search` matches against strain name, product type, effects, flavor profile, and hardware type, so queries like "citrus" or "pod" return relevant results.
- **Budget-Aware Sorting** — When a budget target is provided, results are sorted by proximity to the budget (closest price first) rather than by weight or premium ranking.
- **Accurate Result Counts** — The `total` field in search results reflects the actual number of matched products, not the number returned after the limit is applied.
- **Fast-Path Responses** — Greetings, closings, and simple acknowledgments bypass the LLM entirely, reducing latency and API cost.
- **Drop-In Chat Widget** — Pure HTML/CSS/JS frontend with a floating button and chat drawer; no build step required. Embeds on any webpage with a single `<script>` tag.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.12 · FastAPI 0.135 · Uvicorn |
| AI / LLM | OpenAI API 2.26 (`gpt-4o-mini`) with function calling |
| Data | Pandas 2.2 · CSV product catalog |
| Validation | Pydantic 2.12 |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Testing | Pytest · pytest-asyncio · HTTPX |
| Security Lint | Bandit · Pylint |

---

## Quick Start

### Prerequisites

- Python 3.12+
- An OpenAI API key

### 1. Clone and set up virtual environment

```bash
git clone <repo-url>
cd AI_BUDTENDER2

python3.12 -m venv venv
source venv/bin/activate          # Linux / macOS / WSL
# venv\Scripts\activate           # Windows CMD
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...your_key_here...
```

> The `.env` file is git-ignored and must never be committed.

### 4. Run the server

```bash
uvicorn backend.main:app --reload
```

The API will be available at `http://localhost:8000`.
Health check: `GET http://localhost:8000/health`

### 5. Open the frontend

Open `frontend/index.html` in your browser directly, or serve it from any static file server. The chat widget connects to `http://localhost:8000` by default.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Returns service status and loaded product count |
| `POST` | `/chat` | Accepts a `ChatRequest`, returns an AI recommendation |

### `POST /chat` payload

```json
{
  "session_id": "abc123",
  "messages": [{ "role": "user", "content": "I want something relaxing" }],
  "user_message": "I want something relaxing",
  "is_beginner": false
}
```

Set `is_beginner: true` for first-time customers. The backend injects a session-level context into the LLM, which will apply beginner safety filters for the entire session and never ask the customer whether they are a beginner.

---

## Project Structure

```
cannabis_AI_BUDTENDER/
├── backend/
│   ├── main.py            # FastAPI app, routes
│   ├── llm_service.py     # Agent loop, tool calling, prompt logic
│   ├── product_manager.py # CSV loading, multi-criteria search
│   ├── models.py          # Pydantic request/response schemas
│   └── config.py          # Global configuration constants
├── frontend/
│   ├── index.html         # Chat widget page
│   ├── style.css          # Widget styles
│   └── chat.js            # Session management, API calls, rendering
├── data/
│   └── NYE4.0_v3.csv      # Product catalog (217 records)
├── tests/                 # Pytest test suite
├── requirements.txt
└── .env                   # (not committed) API keys
```

---

## Running Tests

```bash
venv/bin/python -m pytest tests/ -v --cov=backend --cov-report=term-missing
```

## Eval Framework

The project includes a golden-dataset eval framework for validating LLM conversation quality end-to-end.

```bash
source venv/bin/activate
python eval/run_eval.py
```

Test cases are defined in `golden_dataset_v1.json`. Each case specifies a conversation scenario, pass/fail rules, and grading criteria. Results are logged to `reports/` and optionally to Langfuse for tracing.

Current coverage: **13 test cases** across discovery flow and recommendation refinement scenarios (12/13 passing; tc_A6 is a known non-deterministic edge case).

## License

Private project — not licensed for redistribution.
