# AI Budtender

An embeddable AI chat widget that helps cannabis dispensary customers find the right product through multi-turn conversation — with built-in safety guardrails for first-time users.

---

## Features

- **Conversational Recommendations** — Understands customer needs through multi-turn dialogue (effects, budget, time of day, activity) and recommends the best-matched products from live inventory.
- **Information Gathering Layer** — Collects two signals before searching: effect/scenario and consumption form. Asks one question at a time, leads with expertise ("Since you're looking to relax…"), and stops asking after escalation (repeated "I don't know").
- **Compliance Layer** — Enforces medical disclaimers (no treatment claims), age verification (21+ hard block), and beginner safety (dosage limits, no infused products for first-timers).
- **Recommendation Refinement** — Handles post-recommendation feedback: asks for budget on price objections, re-searches with `max_thc` on strength feedback, asks for reason on generic rejections, fetches full product details on request, and runs side-by-side comparisons.
- **Beginner Safety Mode** — Enforces THC limits (edibles ≤ 5 mg, flower ≤ 20%, vaporizers ≤ 70%) when `is_beginner: true` is passed in the request. The LLM receives a session-level context injection so it never asks the customer again and always applies beginner filters throughout the conversation.
- **Agent Loop with Tool Calling** — Uses OpenAI function calling to run `smart_search` and `get_product_details` against a 217-product SQLite catalog, enabling precise, multi-criteria filtering without injecting the full dataset into every prompt.
- **Rich Free-Text Search** — `smart_search` matches against product name, strain type, effects, flavor profile, hardware type, and description, so queries like "citrus" or "pod" return relevant results.
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
| Data | SQLite3 · Pandas 2.2 · 217-product catalog |
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
cd cannabis_AI_BUDTENDER

python3.12 -m venv venv
source venv/bin/activate          # Linux / macOS / WSL
# venv\Scripts\activate           # Windows CMD
```

### 2. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...your_key_here...
```

> The `.env` file is git-ignored and must never be committed.

### 4. Initialize the database

Run once to create and populate the SQLite database from the source CSV:

```bash
python scripts/setup_db.py
python scripts/migrate_csv_to_sqlite.py
```

This creates `data/products.db` with 217 products across 8 categories.

### 5. Run the server

```bash
uvicorn backend.main:app --reload
```

The API will be available at `http://localhost:8000`.
Health check: `GET http://localhost:8000/health`

### 6. Open the frontend

Serve the frontend with a local HTTP server (required to avoid CORS errors):

```bash
python -m http.server 3000 --directory frontend/
```

Then open `http://localhost:3000` in your browser. The chat widget connects to `http://localhost:8000` by default.

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
│   ├── product_manager.py # SQLite loading, multi-criteria search
│   ├── models.py          # Pydantic request/response schemas
│   └── config.py          # Global configuration constants
├── frontend/
│   ├── index.html         # Chat widget page
│   ├── style.css          # Widget styles
│   └── chat.js            # Session management, API calls, rendering
├── data/
│   ├── products.db        # SQLite product database (217 records, 8 categories)
│   └── NYE4.0_v3.csv      # Source CSV (read-only, used for migration only)
├── scripts/
│   ├── setup_db.py        # Creates SQLite tables and indexes (run once)
│   └── migrate_csv_to_sqlite.py  # Migrates CSV → SQLite with attributes JSON
├── tests/                 # Pytest test suite
├── eval/                  # Golden-dataset eval framework
├── reports/               # Eval output reports
├── requirements.txt
└── .env                   # (not committed) API keys
```

---

## Running Tests

```bash
venv/bin/python -m pytest tests/ -v --cov=backend --cov-report=term-missing
```

---

## Eval Framework

The project includes a golden-dataset eval framework for validating LLM conversation quality end-to-end.

```bash
source venv/bin/activate
python eval/run_eval.py
```

Test cases are defined in `golden_dataset_v2.json`. Each case specifies a conversation scenario, pass/fail rules, and grading criteria. Results are logged to `reports/` and optionally to Langfuse for tracing.

Current coverage: **21 test cases** (21/21 passing):

| Direction | TCs | Description |
|---|---|---|
| C — Compliance Layer | C1~C6 | Medical disclaimers, age verification, beginner safety |
| G — Information Gathering | G1~G8 | Signal collection, escalation, multi-turn patterns |
| B — Recommendation Refinement | B1~B6 | Price/strength feedback, dislike, product details, comparison |
| F — Search Fallback | F1 | Fallback behavior when no exact match found |

---

## License

Private project — not licensed for redistribution.
