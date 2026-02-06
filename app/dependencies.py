# app/dependencies.py

from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.rate_limiter import (
    get_client_ip,
    check_rate_limit,
    HOURLY_TOKEN_LIMIT
)


async def check_rate_limit_dependency(
    request: Request,
    session: Session = Depends(get_db)
) -> str:
    """
    FastAPI dependency to check rate limits before processing requests.

    Raises:
        HTTPException: 429 if rate limit exceeded

    Returns:
        IP address of the client
    """
    ip_address = get_client_ip(request)
    is_allowed, tokens_used, reset_time = check_rate_limit(session, ip_address)

    if not is_allowed:
        reset_time_str = reset_time.isoformat()
        retry_after_seconds = max(0, int((reset_time - datetime.utcnow()).total_seconds()))

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
