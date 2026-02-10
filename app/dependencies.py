# app/dependencies.py
# FastAPI dependencies using Supabase

from fastapi import Request, HTTPException, Depends
from supabase import Client
from datetime import datetime

from app.database import get_db
from app.rate_limiter import (
    get_client_ip,
    check_rate_limit,
    HOURLY_TOKEN_LIMIT
)
import logging

logger = logging.getLogger(__name__)


async def check_rate_limit_dependency(
    request: Request,
    client: Client = Depends(get_db)
) -> str:
    """
    FastAPI dependency to check rate limits before processing requests.

    Raises:
        HTTPException: 429 if rate limit exceeded

    Returns:
        IP address of the client
    """
    try:
        ip_address = get_client_ip(request)
        is_allowed, tokens_used, reset_time = check_rate_limit(client, ip_address)

        if not is_allowed:
            reset_time_str = reset_time.isoformat()
            retry_after_seconds = max(0, int((reset_time - datetime.utcnow()).total_seconds()))

            logger.warning(f"Rate limit exceeded for IP: {ip_address} ({tokens_used} tokens)")

            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "message": f"You have used {tokens_used} tokens in the last hour. Limit is {HOURLY_TOKEN_LIMIT} tokens per hour.",
                    "tokens_used": tokens_used,
                    "limit": HOURLY_TOKEN_LIMIT,
                    "reset_time": reset_time_str,
                    "retry_after_seconds": retry_after_seconds
                }
            )

        return ip_address

    except HTTPException:
        # Re-raise HTTP exceptions (rate limit exceeded)
        raise
    except Exception as e:
        logger.error(f"Error checking rate limit: {str(e)}")
        # On error, allow the request but log it
        return get_client_ip(request)
