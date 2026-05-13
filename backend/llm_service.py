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

    # Inject action instruction for product comparison requests.
    #
    # Skip when the storefront compare tray sent compare_product_ids — main.py
    # injects a higher-fidelity signal in that case ("COMPARE_BY_ID: 1,2,3"
    # + get_product_details instructions). Two contradicting tool routes
    # would confuse the LLM, so let the by-id signal stand alone.
    has_compare_ids_signal = any(
        isinstance(m, dict)
        and m.get("role") == "system"
        and "[UI SIGNAL] COMPARE_BY_ID:" in (m.get("content") or "")
        for m in history
    )
    if is_product_comparison(user_message) and not has_compare_ids_signal:
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
    trace: dict | None = None,
) -> str | None:
    """
    Fast path: skip Call 1 by injecting a synthetic tool call + result, then
    make a single LLM call to generate the recommendation.

    Returns the reply string, or None if anything goes wrong (caller falls back
    to the standard agent loop).

    If `trace` is provided, records the search invocation under
    `trace["last_smart_search"]` BEFORE the LLM call so that even on LLM
    failure the trace reflects what was searched.
    """
    import uuid

    try:
        search_result = product_manager.search_products(**search_params)

        # Record the search in trace BEFORE the LLM call — so even if the LLM
        # call below raises, the caller can still surface what we matched.
        if trace is not None:
            trace["last_smart_search"] = {
                "args": dict(search_params),
                "result": search_result,
            }

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
    trace: dict | None = None,
) -> str:
    """
    Execute the Agent Loop: LLM call → tool execution → repeat until final answer.

    If `trace` is provided, every successful (non-duplicate) smart_search call
    is recorded under `trace["last_smart_search"]`. Multiple smart_search calls
    in a single turn leave only the most recent successful one in trace.

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
                    # Record into trace (parse the same args execute_tool_call
                    # parsed internally — execute_tool_call doesn't return them).
                    if trace is not None:
                        try:
                            parsed_args = json.loads(tool_call.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            parsed_args = {}
                        trace["last_smart_search"] = {
                            "args": parsed_args,
                            "result": result,
                        }
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


def _run_fast_path_stream(
    client,
    messages: list[dict],
    search_params: dict,
    product_manager,
    trace: dict | None = None,
):
    """Streaming counterpart of _run_fast_path.

    The fast path normally returns the entire reply as a single string (one
    non-streaming LLM call). That kills the streaming UX, so for the
    streaming endpoint we inline the synthetic tool-call/tool-result
    injection and then stream the final LLM response token-by-token.

    Yields text chunks; populates ``trace["last_smart_search"]`` before
    the first chunk so the caller can emit ui_action ahead of the text.
    Yields nothing (and lets the caller fall back to the agent loop) if
    anything goes wrong before the streaming call is reached.
    """
    import uuid

    try:
        search_result = product_manager.search_products(**search_params)

        if trace is not None:
            trace["last_smart_search"] = {
                "args": dict(search_params),
                "result": search_result,
            }

        fake_call_id = f"call_{uuid.uuid4().hex[:12]}"
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
        messages.append({
            "role": "tool",
            "tool_call_id": fake_call_id,
            "content": json.dumps(search_result, separators=(",", ":")),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FastPathStream] setup failed: %s", exc)
        return  # Caller falls back to agent loop

    yield from _stream_final_response(client, messages)


def _run_agent_loop_stream(
    client,
    messages: list[dict],
    tool_choice: str,
    product_manager,
    trace: dict | None = None,
):
    """
    Same as _run_agent_loop but streams the final LLM response token by token.

    Strategy:
    - Tool detection phase: non-streaming (must parse tool_calls structure)
    - Final response phase: streaming (after tools executed, or when no tools needed)

    Trace semantics match the non-streaming agent loop: when ``trace`` is
    provided, the most recent successful smart_search is recorded under
    ``trace["last_smart_search"]`` *before* the final response begins
    streaming. Callers can therefore peek at trace to emit ui_action SSE
    events while the text is still in flight.
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
                    if trace is not None:
                        try:
                            parsed_args = json.loads(tool_call.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            parsed_args = {}
                        trace["last_smart_search"] = {
                            "args": parsed_args,
                            "result": result,
                        }
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
    *,
    trace: dict | None = None,
):
    """Streaming version of get_recommendation. Yields text chunks.

    Trace semantics mirror the non-streaming ``get_recommendation``: when
    ``trace`` is provided, it is populated as a side channel with
    ``profile`` and ``last_smart_search`` keys. The fast path populates
    ``last_smart_search`` *before* yielding any text, so the SSE endpoint
    can read it and emit a ui_action event ahead of the first chunk.
    """
    profile = extract_profile_signals(user_message, history)
    if trace is not None:
        trace["profile"] = profile
    if not is_beginner and profile.get("experience_level") == "beginner":
        is_beginner = True
    tool_choice = determine_tool_choice(user_message, history)
    messages = _prepare_messages(history, user_message, profile, is_beginner)

    # Fast path: extract params at Python level → skip Call 1. The streaming
    # variant (_run_fast_path_stream) inlines the synthetic tool injection so
    # the FINAL LLM call streams token-by-token. trace["last_smart_search"]
    # is populated before the first chunk is yielded.
    # IMPORTANT: pass a copy of messages — fast path appends synthetic tool
    # calls, and if it yields nothing (setup failure) the original messages
    # must stay clean for the agent-loop fallback below.
    if tool_choice in ("auto", "required"):
        fast_params = try_extract_search_params(user_message, history, is_beginner)
        if fast_params:
            if is_strength_feedback_query(user_message, history):
                thc_cap = derive_lower_thc_cap(history)
                if thc_cap is not None:
                    fast_params["max_thc"] = thc_cap
            gen = _run_fast_path_stream(
                _openai_client, list(messages), fast_params, product_manager,
                trace=trace,
            )
            # Peek at the first chunk to detect whether fast path actually
            # produced output (setup may have failed silently). If it did,
            # yield the first chunk then stream the rest lazily — preserving
            # real over-the-wire streaming to the SSE consumer.
            first = next(gen, None)
            if first is not None:
                yield first
                yield from gen
                return

    yield from _run_agent_loop_stream(
        _openai_client, messages, tool_choice, product_manager,
        trace=trace,
    )


def get_recommendation(
    history: list[dict],
    user_message: str,
    product_manager,  # ProductManager instance
    is_beginner: bool = False,
    *,
    trace: dict | None = None,
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
        is_beginner: Whether the customer is flagged as a beginner.
        trace: Optional out-param dict. When provided, the function populates
            it as a side channel with two keys:
              - `profile`: the extracted profile signals
              - `last_smart_search`: `{"args": dict, "result": dict}` for the
                most recent successful smart_search this turn (fast-path or
                agent-loop). Absent when no smart_search ran.
            Existing callers that omit `trace` are unaffected — return type
            remains `str`.

    Returns:
        Final assistant reply text.

    Raises:
        RuntimeError: If the API call fails.
    """
    profile = extract_profile_signals(user_message, history)
    if trace is not None:
        # Side-channel: stash profile so the ui_action_builder can reuse it
        # without re-running the (non-trivial) extraction.
        trace["profile"] = profile
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
            result = _run_fast_path(
                _openai_client, list(messages), fast_params, product_manager,
                trace=trace,
            )
            if result:
                return result
            logger.info("[FastPath] failed or empty, falling back to agent loop")

    return _run_agent_loop(
        _openai_client, messages, tool_choice, product_manager,
        trace=trace,
    )
