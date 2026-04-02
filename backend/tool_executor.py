"""Tool definitions and execution for AI Budtender Agent Loop.

Contains the OpenAI function-calling schema (TOOLS_SCHEMA) and the
dispatcher (execute_tool_call) that maps tool names to ProductManager calls.
"""
# pylint: disable=line-too-long

import json
import logging

logger = logging.getLogger(__name__)

# ── Tool schema (OpenAI function calling) ─────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "smart_search",
            "description": (
                "Search the product catalog. Use this whenever you are ready to recommend products. "
                "All parameters are optional — use only the ones relevant to the customer's request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text keyword search (strain name, flavor, effect, etc.)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Product category: Flower, Pre-rolls, Edibles, Vaporizers, Concentrates, Tinctures, Accessories",
                    },
                    "strain_type": {
                        "type": "string",
                        "description": "Filter by strain type: Indica, Sativa, or Hybrid. Use this when the customer explicitly requests a strain type.",
                    },
                    "effects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Desired effect keywords (e.g. ['Sleepy', 'Relaxed', 'Focused'])",
                    },
                    "exclude_effects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Effects to avoid (e.g. ['Sedated'] for 'no couch lock')",
                    },
                    "exclude_categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Categories to exclude (e.g. ['Concentrates'] for beginners)",
                    },
                    "min_thc": {
                        "type": "number",
                        "description": "Minimum THC percentage (for experienced users wanting potency)",
                    },
                    "max_thc": {
                        "type": "number",
                        "description": "Maximum THC percentage (for customers who find current options too strong, e.g. max_thc=70 for vape, max_thc=18 for flower)",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price filter",
                    },
                    "budget_target": {
                        "type": "number",
                        "description": "Target budget — finds best value products at or near this price",
                    },
                    "time_of_day": {
                        "type": "string",
                        "description": "Daytime, Nighttime, or Anytime",
                    },
                    "activity_scenario": {
                        "type": "string",
                        "description": "Activity scenario: Sleep, Relaxation, Focus, Social, Active, Creative, etc.",
                    },
                    "list_sub_types": {
                        "type": "boolean",
                        "description": "If true, return category/subcategory overview instead of individual products",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 8)",
                    },
                    "is_beginner": {
                        "type": "boolean",
                        "description": "Set to true if the customer is a first-time or beginner user. Applies safety limits: max 5mg THC for edibles, max 20% for flower/vapes, excludes high-THC topicals and concentrates.",
                    },
                    "unit_weight": {
                        "type": "string",
                        "description": (
                            "Filter by product unit weight/size. "
                            "Use exact values from data: '28g' for 1oz, '14g' for half oz, "
                            "'7g' for quarter oz, '3.5g' for eighth. "
                            "Example: customer asks '1oz flower' → unit_weight='28g'"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Get full details for a specific product by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID (integer as string)",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
]


# ── Tool dispatcher ────────────────────────────────────────────────────────────

def execute_tool_call(tool_call, product_manager) -> dict:
    """Dispatch a single tool call and return its result dict."""
    fn_name = tool_call.function.name
    try:
        fn_args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        fn_args = {}

    logger.info("[Agent] Calling tool: %s args=%s", fn_name, fn_args)

    if fn_name == "smart_search":
        return product_manager.search_products(**fn_args)
    if fn_name == "get_product_details":
        pid = fn_args.get("product_id", "")
        return product_manager.get_product_by_id(pid) or {}
    return {"error": f"Unknown tool: {fn_name}"}
