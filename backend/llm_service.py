"""LLM integration module for AI Budtender.

Assembles message lists and calls the OpenAI API
with tool calling (Agent Loop) for smart product search.
"""
# pylint: disable=line-too-long

import json
import logging
import openai
from backend.config import OPENAI_API_KEY, MODEL_NAME
from backend.prompts import SYSTEM_PROMPT
from backend.tool_executor import TOOLS_SCHEMA, execute_tool_call
from backend.router import (
    is_price_refinement_query,
    is_price_feedback_query,
    is_vape_flower_alternative,
    is_product_comparison,
    is_negative_strength_constraint,
    has_form_keyword,
    determine_tool_choice,
    extract_profile_signals,
    serialize_profile,
    try_extract_search_params,
)

logger = logging.getLogger(__name__)





# ── Message assembly ───────────────────────────────────────────────────────────

RECENT_HISTORY_LIMIT = 4  # Only send last 4 messages (2 turns) to OpenAI; full history used for profile extraction


def build_messages(
    history: list[dict],
    user_message: str,
    profile: dict | None = None,
) -> list[dict]:
    """
    Assemble the messages list for the OpenAI API call.

    Structure: [system + profile] + recent history (last 4) + [user message].
    Profile is extracted from full history by the caller (get_recommendation).
    No product JSON injected — products come via tool calling.

    Args:
        history: Previous messages as list of {role, content} dicts.
        user_message: Current user message text.
        profile: Optional session profile dict to append to system prompt.

    Returns:
        List of message dicts ready for the OpenAI chat API.
    """
    system_content = SYSTEM_PROMPT
    if profile:
        system_content += serialize_profile(profile)

    recent_history = history[-RECENT_HISTORY_LIMIT:] if len(history) > RECENT_HISTORY_LIMIT else history

    messages = [{"role": "system", "content": system_content}]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})
    return messages


# ── Agent loop ────────────────────────────────────────────────────────────────

def _prepare_messages(
    history: list[dict],
    user_message: str,
    profile: dict | None,
    is_beginner: bool,
) -> list[dict]:
    """Assemble messages list and inject session context injections."""
    messages = build_messages(history, user_message, profile)

    if is_beginner:
        messages[0]["content"] += (
            "\n\n[SESSION CONTEXT]: This customer has been identified as a first-time/beginner user. "
            "ALWAYS include is_beginner=true in ALL smart_search calls for this session. "
            "Never ask if they are a beginner — it is already confirmed."
        )

    # Inject targeted action instruction for price feedback (overrides "Customer feedback: price too high")
    if is_price_refinement_query(user_message, history):
        messages[0]["content"] += (
            "\n\n[IMMEDIATE ACTION REQUIRED]: Customer asked for something cheaper AFTER already seeing concrete recommendations. "
            "You MUST call smart_search immediately and keep the same vibe, effect direction, and form whenever possible. "
            "Use a lower-price filter than the previous options when available. "
            "Do NOT ask 'What price range works for you?' as the main response. "
            "After recommending cheaper options, end with one soft invitation such as "
            "'If you have a price range in mind, let me know and I can narrow it down even better.'"
        )
    elif is_price_feedback_query(user_message):
        messages[0]["content"] += (
            "\n\n[IMMEDIATE ACTION REQUIRED]: Customer said prices are too high but has NOT specified a budget. "
            "Your response MUST be ONE question only: ask what price range works for them. "
            "Do NOT write 'let me find' or 'I'll look for' anything. Just ask: 'What price range works for you?'"
        )

    # Inject action instruction when customer gives "vape or flower" alternatives
    if is_vape_flower_alternative(user_message):
        messages[0]["content"] += (
            "\n\n[IMMEDIATE ACTION REQUIRED]: Customer said 'vape or flower' (or similar). "
            "Per INFORMATION GATHERING rules: 'flower' is the selected form — category='Flower'. "
            "Both signals are now complete. Your ONLY valid action is to call smart_search immediately. "
            "DO NOT output any text before the tool call. DO NOT ask about pre-rolls. DO NOT ask about hardware type."
        )

    # Inject action instruction for product comparison requests
    if is_product_comparison(user_message):
        messages[0]["content"] += (
            "\n\n[COMPARISON REQUEST DETECTED]: Customer is asking to compare or choose between specific products. "
            "Per RECOMMENDATION REFINEMENT rules: you MUST call smart_search(query='[product A name]', limit=1) "
            "and then smart_search(query='[product B name]', limit=1) to retrieve fresh data for EACH product. "
            "Build the comparison ENTIRELY from tool-returned fields. "
            "DO NOT answer from memory or training data — product details (flavor, effects, THC) must come from the tool."
        )

    # Inject action instruction when customer gives negative strength constraint + form is known
    all_history_text = " ".join(msg.get("content", "") for msg in history)
    form_in_message = has_form_keyword(user_message)
    form_in_history = has_form_keyword(all_history_text)
    if is_negative_strength_constraint(user_message) and (form_in_message or form_in_history):
        messages[0]["content"] += (
            "\n\n[IMMEDIATE ACTION REQUIRED]: Customer expressed a negative outcome constraint (e.g. 'don't want to feel wrecked'). "
            "Per INFORMATION GATHERING rules: this is a complete weak effect signal — infer low-dose/Relaxed. "
            "Form is already known from this message or conversation history. "
            "Both signals are complete. Your ONLY valid action is to call smart_search immediately. "
            "DO NOT output any text before the tool call. DO NOT ask about THC level or dosage."
        )

    return messages


def _run_fast_path(
    client,
    messages: list[dict],
    search_params: dict,
    product_manager,
) -> str | None:
    """
    Fast path: skip Call 1 by injecting a synthetic tool call + result, then
    make a single LLM call to generate the recommendation.

    Returns the reply string, or None if anything goes wrong (caller falls back
    to the standard agent loop).
    """
    import uuid

    try:
        search_result = product_manager.search_products(**search_params)
        fake_call_id = f"call_{uuid.uuid4().hex[:12]}"

        # Inject synthetic Call-1 assistant message
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": fake_call_id,
                "type": "function",
                "function": {
                    "name": "smart_search",
                    "arguments": json.dumps(search_params, separators=(",", ":")),
                },
            }],
        })

        # Inject tool result
        messages.append({
            "role": "tool",
            "tool_call_id": fake_call_id,
            "content": json.dumps(search_result, separators=(",", ":")),
        })

        # Single LLM call — no tools needed, search already done
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    except Exception as exc:  # noqa: BLE001
        logger.warning("[FastPath] exception: %s", exc)
        return None  # Signal caller to fall back


def _run_agent_loop(
    client,
    messages: list[dict],
    tool_choice: str,
    product_manager,
) -> str:
    """
    Execute the Agent Loop: LLM call → tool execution → repeat until final answer.

    Raises:
        RuntimeError: If the API call fails.
    """
    try:
        # Agent loop — max 3 iterations to prevent infinite loops
        current_tools = TOOLS_SCHEMA
        for iteration in range(3):
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=current_tools,
                tool_choice=tool_choice,
            )

            msg = response.choices[0].message

            # No tool calls → we have the final answer
            if not msg.tool_calls:
                return msg.content or ""

            # Append assistant message with tool calls
            messages.append(msg)

            # Execute each tool call — only the first smart_search per turn is executed;
            # duplicate smart_search calls are skipped to prevent flavor-constraint loss.
            search_had_results = False
            smart_search_executed = False
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                if fn_name == "smart_search" and smart_search_executed:
                    # Duplicate smart_search in same turn — skip execution, return placeholder
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": "duplicate smart_search ignored — use a single call combining all criteria", "total": 0}, separators=(",", ":")),
                    })
                    continue
                result = execute_tool_call(tool_call, product_manager)
                if fn_name == "smart_search":
                    smart_search_executed = True
                    if result.get("total", 0) > 0:
                        search_had_results = True
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, separators=(",", ":")),
                })

            # If search returned results, remove smart_search to prevent re-search
            # but keep get_product_details available so LLM can fetch product info
            # If search was empty, allow LLM to retry with different parameters
            if search_had_results:
                current_tools = [t for t in TOOLS_SCHEMA if t["function"]["name"] != "smart_search"]
                tool_choice = "auto"
            else:
                current_tools = TOOLS_SCHEMA
                tool_choice = "auto"

        # Fallback: call once more without tools
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    except openai.APITimeoutError as exc:
        raise RuntimeError("OpenAI API request timed out.") from exc
    except openai.RateLimitError as exc:
        raise RuntimeError("OpenAI API rate limit exceeded.") from exc
    except openai.APIError as exc:
        raise RuntimeError(f"OpenAI API error: {exc}") from exc


_openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)


def get_recommendation(
    history: list[dict],
    user_message: str,
    product_manager,  # ProductManager instance
    is_beginner: bool = False,
) -> str:
    """
    Run the Agent Loop: call LLM → execute tool calls → call LLM again until done.

    Fast path: if search parameters can be extracted at Python level, skip the
    first LLM call and inject a synthetic tool result directly, reducing latency
    by ~2-5 seconds for ~60-70% of recommendation requests.

    Args:
        history: Previous messages as list of {role, content} dicts.
        user_message: Current user message text.
        product_manager: ProductManager instance for tool execution.

    Returns:
        Final assistant reply text.

    Raises:
        RuntimeError: If the API call fails.
    """
    profile = extract_profile_signals(user_message, history)
    tool_choice = determine_tool_choice(user_message, history)
    messages = _prepare_messages(history, user_message, profile, is_beginner)

    # Fast path: extract params at Python level → skip Call 1
    if tool_choice in ("auto", "required"):
        fast_params = try_extract_search_params(user_message, history, is_beginner)
        if fast_params:
            logger.info("[FastPath] params=%s", fast_params)
            result = _run_fast_path(_openai_client, messages, fast_params, product_manager)
            if result:
                return result
            logger.info("[FastPath] failed or empty, falling back to agent loop")

    return _run_agent_loop(_openai_client, messages, tool_choice, product_manager)
