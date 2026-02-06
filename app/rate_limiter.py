# app/rate_limiter.py

import os
from datetime import datetime, timedelta
from typing import Tuple
from fastapi import Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import TokenUsage

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
    session: Session,
    ip_address: str,
    tokens: int,
    model: str,
    endpoint: str
) -> None:
    """
    Record token usage in the database.

    Args:
        session: SQLAlchemy database session
        ip_address: Client IP address
        tokens: Number of tokens used
        model: Model name (e.g., "gpt-4o-mini")
        endpoint: API endpoint (e.g., "/recommend")
    """
    usage_record = TokenUsage(
        ip_address=ip_address,
        tokens_used=tokens,
        model_name=model,
        endpoint=endpoint,
        timestamp=datetime.utcnow()
    )
    session.add(usage_record)
    session.commit()


def get_hourly_token_usage(session: Session, ip_address: str) -> int:
    """
    Get total token usage for an IP in the last hour.

    Args:
        session: SQLAlchemy database session
        ip_address: Client IP address

    Returns:
        Total tokens used in the last hour
    """
    one_hour_ago = datetime.utcnow() - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

    total_tokens = session.query(func.sum(TokenUsage.tokens_used)).filter(
        TokenUsage.ip_address == ip_address,
        TokenUsage.timestamp >= one_hour_ago
    ).scalar()

    return total_tokens or 0


def check_rate_limit(session: Session, ip_address: str) -> Tuple[bool, int, datetime]:
    """
    Check if an IP address has exceeded the rate limit.

    Args:
        session: SQLAlchemy database session
        ip_address: Client IP address

    Returns:
        Tuple of (is_allowed, tokens_used, reset_time)
        - is_allowed: True if request should be allowed
        - tokens_used: Total tokens used in current window
        - reset_time: When the rate limit will reset
    """
    tokens_used = get_hourly_token_usage(session, ip_address)

    # Find the oldest usage record in the current window
    one_hour_ago = datetime.utcnow() - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
    oldest_record = session.query(TokenUsage).filter(
        TokenUsage.ip_address == ip_address,
        TokenUsage.timestamp >= one_hour_ago
    ).order_by(TokenUsage.timestamp.asc()).first()

    # Reset time is 1 hour after the oldest record, or 1 hour from now if no records
    if oldest_record:
        reset_time = oldest_record.timestamp + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
    else:
        reset_time = datetime.utcnow() + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

    is_allowed = tokens_used < HOURLY_TOKEN_LIMIT

    return is_allowed, tokens_used, reset_time
