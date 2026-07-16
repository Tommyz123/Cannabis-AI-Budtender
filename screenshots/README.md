# AI Budtender — Portfolio Screenshots

Captured from the running app (FastAPI backend + Verdant storefront frontend),
real conversations against the live 217-product catalog. Used as portfolio
evidence for the CASE_STUDY. All images are English-only.

Each screenshot was verified programmatically at capture time (not just visually):
compliance replies were driven by real guardrail code; the recommendation cards
were checked to equal the products the assistant names in chat.

| File | What it shows | Why it matters |
|---|---|---|
| `01_compliance_medical_claim_block.png` | Customer asks *"anything that can treat my anxiety?"* → assistant refuses the medical claim ("I can't offer medical advice…") and pivots to a compliant suggestion | Compliance guardrail #1 — medical-claim protection, enforced in code (router returns `tool_choice="none"`), not just prompt text |
| `02_compliance_age_block.png` | Customer says *"I'm 19…"* → assistant hard-blocks: "cannabis products are only available to customers aged 21 and older. I'm unable to make any recommendations." | Compliance guardrail #2 — age verification, a hard refusal with no product recommendation |
| `03_storefront_before.png` | The full storefront: 217 products across 8 categories, filters sidebar, product grid | "Before" state for the conversation-driven UI story |
| `04_conversation_driven_after.png` | After the customer types one sentence — *"I want something relaxing for sleep — edibles, under $30"* — the page reshapes: `217 → 36 of 217`, four filter chips auto-applied (Form: Edibles, Effect: Relaxed, Effect: Sleepy, Under $30), and the **✨ Best Matches for You** row populates. The chat below lists the same products. | Conversation-driven UI: one natural-language request drives filters + grid + recommendations, no manual clicking |
| `05_best_matches_row.png` | All six Best Matches cards in one row (names, prices, THC, per-card reason) | Shows the recommendation set the assistant is talking about in chat — cards == chat, by construction |

## The consistency guarantee (worth calling out in interviews)

The Best Matches cards and the products the assistant recommends in prose are
built from **one** backend-chosen list (the top N of the retrieved set, padded
from the same category to a 3–6 minimum and labeled "Similar option" when a
strict search returns fewer). The assistant is instructed to recommend exactly
that list, and the cards render exactly that list — so "what it recommends ==
what it displays" is true *by construction*, not by after-the-fact text
matching. This replaced an earlier prose-scanning approach that could
mis-attribute products whose names shared a brand prefix.

## Reproducing

Run the backend + frontend (see the project README), open the storefront, and
type a need into the AI Budtender chat drawer. Screenshots here were captured
headless via Playwright; the capture/verification scripts are not committed
(they lived in a scratch dir).
