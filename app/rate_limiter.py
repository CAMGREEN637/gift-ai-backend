# app/rate_limiter.py
# Rate limiting logic using Supabase

import os
from datetime import datetime, timedelta
from typing import Tuple
from fastapi import Request
from supabase import Client
import logging

from app.database import get_supabase, TABLE_TOKEN_USAGE

logger = logging.getLogger(__name__)

# Configuration constants
HOURLY_TOKEN_LIMIT = int(os.getenv("HOURLY_TOKEN_LIMIT", "10000"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW", "3600"))


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request.
    Checks proxy headers first (X-Forwarded-For, X-Real-IP),
    then falls back to direct client.host.

    Args:
        request: FastAPI Request object

    Returns:
        IP address as string
    """
    # Check X-Forwarded-For header (most common proxy header)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to direct client host
    return request.client.host if request.client else "unknown"


def record_token_usage(
    client: Client,
    ip_address: str,
    tokens: int,
    model: str,
    endpoint: str
) -> bool:
    """
    Record token usage in the database.

    Args:
        client: Supabase client instance
        ip_address: Client IP address
        tokens: Number of tokens used
        model: Model name (e.g., "gpt-4o-mini")
        endpoint: API endpoint (e.g., "/recommend")

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        data = {
            "ip_address": ip_address,
            "tokens_used": tokens,
            "model_name": model,
            "endpoint": endpoint,
            "timestamp": datetime.utcnow().isoformat()
        }

        result = client.table(TABLE_TOKEN_USAGE).insert(data).execute()
        logger.info(f"Recorded {tokens} tokens for IP: {ip_address}")
        return True

    except Exception as e:
        logger.error(f"Failed to record token usage: {str(e)}")
        return False


def get_hourly_token_usage(client: Client, ip_address: str) -> int:
    """
    Get total token usage for an IP in the last hour.

    Args:
        client: Supabase client instance
        ip_address: Client IP address

    Returns:
        Total tokens used in the last hour
    """
    try:
        one_hour_ago = datetime.utcnow() - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
        one_hour_ago_iso = one_hour_ago.isoformat()

        # Query for all token usage in the last hour
        result = client.table(TABLE_TOKEN_USAGE)\
            .select("tokens_used")\
            .eq("ip_address", ip_address)\
            .gte("timestamp", one_hour_ago_iso)\
            .execute()

        if not result.data:
            return 0

        # Sum up all tokens
        total_tokens = sum(row["tokens_used"] for row in result.data)
        return total_tokens

    except Exception as e:
        logger.error(f"Failed to get hourly token usage: {str(e)}")
        return 0


def check_rate_limit(client: Client, ip_address: str) -> Tuple[bool, int, datetime]:
    """
    Check if an IP address has exceeded the rate limit.

    Args:
        client: Supabase client instance
        ip_address: Client IP address

    Returns:
        Tuple of (is_allowed, tokens_used, reset_time)
        - is_allowed: True if request should be allowed
        - tokens_used: Total tokens used in current window
        - reset_time: When the rate limit will reset
    """
    try:
        tokens_used = get_hourly_token_usage(client, ip_address)

        # Find the oldest usage record in the current window
        one_hour_ago = datetime.utcnow() - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
        one_hour_ago_iso = one_hour_ago.isoformat()

        oldest_record = client.table(TABLE_TOKEN_USAGE)\
            .select("timestamp")\
            .eq("ip_address", ip_address)\
            .gte("timestamp", one_hour_ago_iso)\
            .order("timestamp", desc=False)\
            .limit(1)\
            .execute()

        # Reset time is 1 hour after the oldest record, or 1 hour from now if no records
        if oldest_record.data:
            oldest_timestamp = datetime.fromisoformat(oldest_record.data[0]["timestamp"].replace('Z', '+00:00'))
            reset_time = oldest_timestamp + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
        else:
            reset_time = datetime.utcnow() + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

        is_allowed = tokens_used < HOURLY_TOKEN_LIMIT

        return is_allowed, tokens_used, reset_time

    except Exception as e:
        logger.error(f"Failed to check rate limit: {str(e)}")
        # On error, allow the request but log it
        return True, 0, datetime.utcnow() + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)


def cleanup_old_token_usage(client: Client, days: int = 7) -> int:
    """
    Clean up token usage records older than specified days.

    Args:
        client: Supabase client instance
        days: Number of days to keep (default: 7)

    Returns:
        Number of records deleted
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        cutoff_iso = cutoff_date.isoformat()

        result = client.table(TABLE_TOKEN_USAGE)\
            .delete()\
            .lt("timestamp", cutoff_iso)\
            .execute()

        count = len(result.data) if result.data else 0
        logger.info(f"Cleaned up {count} old token usage records")
        return count

    except Exception as e:
        logger.error(f"Failed to cleanup old token usage: {str(e)}")
        return 0
