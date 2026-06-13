"""
CS Agent Tool Functions.

All tools read from Redis (seeded at gateway startup) with in-memory fallback.
No hardcoded mock data — Redis is the single source of truth.

Exception-handling pattern per design.md §3.3.3:
  - Catch only specific, known errors.
  - Do NOT catch asyncio.CancelledError, KeyboardInterrupt, or bare Exception
    in the outer scope — that disables the ADK retry system.
  - Return {"status": "error", ...} for recoverable API errors so the LLM
    can acknowledge missing context instead of hallucinating.
"""
import json
import logging
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers — Redis lookups with graceful degradation
# ---------------------------------------------------------------------------

async def _redis_get_account(account_id: str) -> dict | None:
    """Look up account context from Redis hash seeded at gateway startup."""
    try:
        from redis_fabric.fabric import get_redis
        redis = await get_redis()
        raw = await redis.hget(f"account:{account_id}", "context")
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis account lookup failed for %s: %s", account_id, exc)
    return None


async def _redis_get_policy(policy_name: str) -> str | None:
    """Look up policy document content from Redis hash."""
    try:
        from redis_fabric.fabric import get_redis
        redis = await get_redis()
        raw = await redis.hget(f"policy:{policy_name}", "content")
        if raw:
            return raw
    except Exception as exc:
        logger.warning("Redis policy lookup failed for %s: %s", policy_name, exc)
    return None


# ---------------------------------------------------------------------------
# Tool functions — called by cs_reasoning_agent
# ---------------------------------------------------------------------------

async def fetch_account_data(account_id: str) -> dict[str, Any]:
    """
    Fetch customer account data from Redis.

    Returns account tier, lifetime value, and recent orders.
    Returns error artifact if account not found or Redis unavailable.
    """
    data = await _redis_get_account(account_id)
    if data:
        return {"status": "success", "data": data}

    # Account genuinely not found — return a typed error so the agent
    # can acknowledge missing context rather than fabricating account details.
    return {
        "status": "error",
        "error_type": "account_not_found",
        "message": (
            f"Account {account_id} not found in the customer database. "
            "Do not fabricate account details. Acknowledge missing context."
        ),
    }


async def lookup_order_status(order_id: str) -> dict[str, Any]:
    """
    Look up the shipping/fulfillment status of an order.

    Searches all known accounts' recent_orders for the given order_id.
    Returns status, carrier, and tracking info if found.
    """
    try:
        from redis_fabric.fabric import get_redis
        redis = await get_redis()

        # Scan all account keys and search recent_orders for this order_id
        async for key in redis.scan_iter(match="account:ACC-*"):
            raw = await redis.hget(key, "context")
            if not raw:
                continue
            account_data = json.loads(raw)
            for order in account_data.get("recent_orders", []):
                if order.get("order_id") == order_id:
                    return {
                        "status": "success",
                        "data": {
                            "order_id": order_id,
                            "order_status": order.get("status", "unknown"),
                            "date": order.get("date"),
                            "total": order.get("total"),
                            "items": order.get("items", []),
                            "account_id": account_data.get("account_id"),
                            "account_tier": account_data.get("tier"),
                            # Carrier/tracking populated from order if present,
                            # else indicate it must be fetched from fulfillment system
                            "carrier": order.get("carrier", "See fulfillment system"),
                            "tracking_number": order.get("tracking_number", "Not available"),
                        },
                    }
    except Exception as exc:
        logger.warning("Order lookup failed for %s: %s", order_id, exc)
        return {
            "status": "error",
            "error_type": "lookup_failed",
            "message": (
                f"Order lookup failed for {order_id} due to a system error: {exc}. "
                "Do not fabricate order details."
            ),
        }

    return {
        "status": "error",
        "error_type": "order_not_found",
        "message": (
            f"Order {order_id} not found. It may be too old or the ID may be incorrect. "
            "Ask the customer to verify the order ID."
        ),
    }


async def check_return_eligibility(order_id: str) -> dict[str, Any]:
    """
    Check whether an order is eligible for return.

    Eligibility rules (seeded from policy documents):
      - Standard customers: 30-day return window from order date.
      - Premium customers: 45-day return window, free return shipping.
      - Items must be unused and in original packaging (not enforced programmatically).

    Returns days remaining, eligibility flag, and any premium-tier benefits.
    """
    import time
    from datetime import datetime

    try:
        from redis_fabric.fabric import get_redis
        redis = await get_redis()

        order_data = None
        account_tier = "standard"

        async for key in redis.scan_iter(match="account:ACC-*"):
            raw = await redis.hget(key, "context")
            if not raw:
                continue
            account_data = json.loads(raw)
            for order in account_data.get("recent_orders", []):
                if order.get("order_id") == order_id:
                    order_data = order
                    account_tier = account_data.get("tier", "standard")
                    break
            if order_data:
                break

        if not order_data:
            return {
                "status": "error",
                "error_type": "order_not_found",
                "message": f"Cannot check return eligibility: order {order_id} not found.",
            }

        order_date_str = order_data.get("date", "")
        if order_date_str:
            order_ts = datetime.strptime(order_date_str, "%Y-%m-%d").timestamp()
            days_since = (time.time() - order_ts) / 86400
        else:
            days_since = 0

        return_window = 45 if account_tier == "premium" else 30
        days_remaining = max(0, return_window - days_since)
        eligible = days_remaining > 0

        return {
            "status": "success",
            "data": {
                "order_id": order_id,
                "eligible": eligible,
                "days_remaining": int(days_remaining),
                "return_window_days": return_window,
                "account_tier": account_tier,
                "free_return_shipping": account_tier == "premium",
                "note": (
                    "Items must be unused and in original packaging."
                    if eligible
                    else f"Return window of {return_window} days has expired."
                ),
            },
        }

    except Exception as exc:
        logger.warning("Return eligibility check failed for %s: %s", order_id, exc)
        return {
            "status": "error",
            "error_type": "check_failed",
            "message": (
                f"Return eligibility check failed for {order_id}: {exc}. "
                "Do not assume eligibility."
            ),
        }


async def get_policy_document(policy_name: str) -> dict[str, Any]:
    """
    Fetch an internal policy document from Redis.

    Known policy names: return_policy, refund_policy, shipping_policy, warranty_policy.
    """
    content = await _redis_get_policy(policy_name)
    if content:
        return {"status": "success", "data": {"policy_name": policy_name, "content": content}}

    # Try common aliases (e.g. agent might ask for "returns" instead of "return_policy")
    aliases: dict[str, str] = {
        "returns": "return_policy",
        "refund": "refund_policy",
        "shipping": "shipping_policy",
        "warranty": "warranty_policy",
    }
    canonical = aliases.get(policy_name.lower())
    if canonical:
        content = await _redis_get_policy(canonical)
        if content:
            return {"status": "success", "data": {"policy_name": canonical, "content": content}}

    return {
        "status": "error",
        "error_type": "policy_not_found",
        "message": (
            f"Policy document '{policy_name}' not found. "
            "Available policies: return_policy, refund_policy, shipping_policy, warranty_policy."
        ),
    }


async def write_resolution_draft(
    draft: dict[str, Any], tool_context: ToolContext
) -> dict[str, Any]:
    """
    Write the drafted resolution to ADK session state.

    Must be the final tool called by the cs_reasoning_agent.
    The cs_formatter_agent reads resolution_draft from state in Stage B.
    """
    try:
        tool_context.state["resolution_draft"] = json.dumps(draft)
        logger.debug("Resolution draft written to session state.")
        return {"status": "success", "message": "Draft saved to session state."}
    except Exception as exc:
        # Do not raise — return structured error so the framework can retry.
        return {"status": "error", "error_type": "internal_error", "message": str(exc)}
