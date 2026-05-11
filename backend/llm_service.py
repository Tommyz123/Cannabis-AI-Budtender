"""LLM integration module for AI Budtender.

Assembles message lists and calls the OpenAI API
with tool calling (Agent Loop) for smart product search.
"""
# pylint: disable=line-too-long

import json
import logging
import re
from langfuse.openai import openai
from backend.config import OPENAI_API_KEY, MODEL_NAME
from backend.prompts import SYSTEM_PROMPT
from backend.tool_executor import TOOLS_SCHEMA, execute_tool_call
from backend.router import (
    is_price_refinement_query,
    is_price_feedback_query,
    is_vape_flower_alternative,
    is_product_comparison,
    is_negative_strength_constraint,
    is_strength_feedback_query,
    derive_lower_thc_cap,
    has_form_keyword,
    determine_tool_choice,
    extract_profile_signals,
    serialize_profile,
    try_extract_search_params,
)

logger = logging.getLogger(__name__)





# ── Message assembly ───────────────────────────────────────────────────────────

RECENT_HISTORY_LIMIT = 10  # Only send last 10 messages (5 turns) to OpenAI; full history used for profile extraction


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
        # Extra injection when beginner is asking for flower/pre-rolls
        flower_in_msg = bool(re.search(r"\b(flower|pre.?rolls?|smoke|smoking)\b", user_message, re.I))
        flower_in_history = bool(re.search(r"\b(flower|pre.?rolls?)\b",
                                           " ".join(m.get("content","") for m in history if m.get("role")=="user"), re.I))
        if flower_in_msg or flower_in_history:
            messages[0]["content"] += (
                "\n\n[MANDATORY — BEGINNER FLOWER]: This beginner is asking about flower/pre-rolls. "
                "Your response MUST include ALL of the following, in this order:\n"
                "1. [LOWER-THC FRAMING] Before or alongside any product listing, explicitly say the "
                "options are lower in THC or milder. Use a phrase like: "
                "'I'll find some milder, lower-THC options' / "
                "'I've picked lower-THC flower for you' / "
                "'these are on the milder side' / "
                "'lower THC, perfect for a first-timer'. "
                "Showing the THC% number alone does NOT satisfy this — you must explicitly SAY it. "
                "'beginner-friendly' alone is NOT sufficient.\n"
                "2. [SAFETY TIP] Include 'start low and go slow', 'start with a small amount and wait', "
                "or similar explicit safety advice. REQUIRED even if asking a clarifying question first."
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

    # Inject max_thc cap when customer says "too strong / something lighter" after seeing recommendations
    if is_strength_feedback_query(user_message, history):
        thc_cap = derive_lower_thc_cap(history)
        if thc_cap is not None:
            messages[0]["content"] += (
                f"\n\n[IMMEDIATE ACTION REQUIRED]: Customer said the product was too strong. "
                f"Previous recommendations had THC levels on record. "
                f"You MUST include max_thc={thc_cap} in your smart_search call to find genuinely lighter options. "
                f"Do NOT re-search without max_thc — omitting it risks returning equally or more potent products. "
                f"Preserve all other known parameters (category, effects, hardware type, etc.)."
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


def _stream_final_response(client, messages):
    """Make a streaming LLM call and yield text chunks token by token."""
    stream = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _run_agent_loop_stream(
    client,
    messages: list[dict],
    tool_choice: str,
    product_manager,
):
    """
    Same as _run_agent_loop but streams the final LLM response token by token.

    Strategy:
    - Tool detection phase: non-streaming (must parse tool_calls structure)
    - Final response phase: streaming (after tools executed, or when no tools needed)
    """
    try:
        current_tools = TOOLS_SCHEMA
        for iteration in range(3):
            # If there are already tool results in messages (i.e. tools were executed in a
            # previous iteration), stream the final response directly instead of a
            # non-streaming call — this is the main "real streaming" path.
            # Tool result messages are always dicts; ChatCompletionMessage objects are not.
            has_tool_results = any(isinstance(m, dict) and m.get("role") == "tool" for m in messages)
            if has_tool_results:
                yield from _stream_final_response(client, messages)
                return

            # Non-streaming call for tool detection
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=current_tools,
                tool_choice=tool_choice,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                # No tools needed and no prior tool results — yield content we already have.
                # (Re-calling the API would waste a round-trip and may produce a different response.)
                content = msg.content or ""
                if content:
                    yield content
                return

            messages.append(msg)
            search_had_results = False
            smart_search_executed = False
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                if fn_name == "smart_search" and smart_search_executed:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": "duplicate smart_search ignored", "total": 0}),
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

            if search_had_results:
                current_tools = [t for t in TOOLS_SCHEMA if t["function"]["name"] != "smart_search"]
                tool_choice = "auto"
            else:
                current_tools = TOOLS_SCHEMA
                tool_choice = "auto"
            # Loop continues: next iteration detects has_tool_results=True → streams

        # Fallback: max iterations reached — stream final response
        yield from _stream_final_response(client, messages)

    except Exception as exc:
        raise RuntimeError(f"Streaming error: {exc}") from exc


def get_recommendation_stream(
    history: list[dict],
    user_message: str,
    product_manager,
    is_beginner: bool = False,
):
    """Streaming version of get_recommendation. Yields text chunks."""
    profile = extract_profile_signals(user_message, history)
    if not is_beginner and profile.get("experience_level") == "beginner":
        is_beginner = True
    tool_choice = determine_tool_choice(user_message, history)
    messages = _prepare_messages(history, user_message, profile, is_beginner)

    # Fast path: if params extractable, run fast path (non-streaming) then stream final
    # IMPORTANT: pass a copy of messages — fast path appends synthetic tool calls,
    # and if it fails the original messages must stay clean for the agent loop fallback.
    if tool_choice in ("auto", "required"):
        fast_params = try_extract_search_params(user_message, history, is_beginner)
        if fast_params:
            # Inject max_thc cap for strength feedback (fast path bypasses _prepare_messages injections)
            if is_strength_feedback_query(user_message, history):
                thc_cap = derive_lower_thc_cap(history)
                if thc_cap is not None:
                    fast_params["max_thc"] = thc_cap
            result = _run_fast_path(_openai_client, list(messages), fast_params, product_manager)
            if result:
                # Simulate streaming by yielding the full result at once
                # (fast path already ran 1 LLM call, can't re-stream it)
                yield result
                return

    yield from _run_agent_loop_stream(_openai_client, messages, tool_choice, product_manager)


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
    if not is_beginner and profile.get("experience_level") == "beginner":
        is_beginner = True
    tool_choice = determine_tool_choice(user_message, history)
    messages = _prepare_messages(history, user_message, profile, is_beginner)

    # Fast path: extract params at Python level → skip Call 1
    # IMPORTANT: pass a copy of messages — fast path appends synthetic tool calls,
    # and if it fails the original messages must stay clean for the agent loop fallback.
    if tool_choice in ("auto", "required"):
        fast_params = try_extract_search_params(user_message, history, is_beginner)
        if fast_params:
            # Inject max_thc cap for strength feedback (fast path bypasses _prepare_messages injections)
            if is_strength_feedback_query(user_message, history):
                thc_cap = derive_lower_thc_cap(history)
                if thc_cap is not None:
                    fast_params["max_thc"] = thc_cap
            logger.info("[FastPath] params=%s", fast_params)
            result = _run_fast_path(_openai_client, list(messages), fast_params, product_manager)
            if result:
                return result
            logger.info("[FastPath] failed or empty, falling back to agent loop")

    return _run_agent_loop(_openai_client, messages, tool_choice, product_manager)
