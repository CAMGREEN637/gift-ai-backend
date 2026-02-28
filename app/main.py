# app/main.py

import os
from typing import Optional
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import logging

from app.retrieval import retrieve_gifts
from app.llm import generate_gift_response
from app.schemas import PreferencesRequest, GiftFeedback
from app.persistence import (
    save_preferences,
    get_preferences,
    save_feedback,
    get_inferred,
)
from app.database import init_db, get_db
from app.dependencies import check_rate_limit_dependency
from app.rate_limiter import record_token_usage
from supabase import Client

# Import routers
from app.admin_api import router as admin_router
from app.partners_api import router as partners_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# App Setup
app = FastAPI(title="Gift AI Backend")

# Mount static files
try:
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info("✓ Static files mounted from: %s" % static_dir)
except Exception as e:
    logger.warning("Could not mount static files: %s" % str(e))

# Include routers
app.include_router(admin_router)
app.include_router(partners_router)

# Startup
@app.on_event("startup")
def startup():
    init_db()

# API Key Protection
def require_api_key(x_api_key: str = Header(None)):
    expected_key = os.getenv("BACKEND_API_KEY")
    if not expected_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")

# ✅ FIXED CORS CONFIGURATION
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js local dev
        "https://web-production-314d8.up.railway.app",  # Production backend URL
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Image Proxy
@app.get("/proxy-image")
async def proxy_image(url: str):
    logger.info("Proxying image request for: %s" % url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://www.amazon.com/"
            }
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "image/jpeg")
                return Response(
                    content=response.content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "Access-Control-Allow-Origin": "http://localhost:3000"
                    }
                )
            else:
                return Response(
                    content=f"Failed to fetch image: {response.status_code}",
                    status_code=response.status_code
                )
    except Exception as e:
        logger.error("Error fetching image: %s" % str(e))
        return Response(content=f"Error: {str(e)}", status_code=500)

# Preferences
@app.post("/preferences")
def save_user_preferences(preferences: PreferencesRequest):
    save_preferences(
        user_id=preferences.user_id,
        interests=preferences.interests,
        vibe=preferences.vibe,
    )
    return {"status": "saved"}

# Feedback
@app.post("/feedback")
def submit_feedback(feedback: GiftFeedback):
    save_feedback(
        user_id=feedback.user_id,
        gift_name=feedback.gift_name,
        liked=feedback.liked,
    )
    return {"status": "feedback recorded"}

# Recommendation Endpoint
@app.get("/recommend")
def recommend(
    query: str,
    user_id: Optional[str] = None,
    partner_id: Optional[str] = None,
    max_price: Optional[int] = None,
    days_until_needed: Optional[int] = None,
    db: Client = Depends(get_db),
    ip_address: str = Depends(check_rate_limit_dependency)
):
    logger.info(f"Recommendation request: query={query}, partner_id={partner_id}")

    explicit = get_preferences(user_id) if user_id else None
    explicit = explicit or {"interests": [], "vibe": []}
    inferred = get_inferred(user_id) if user_id else {"interests": {}, "vibe": {}}

    merged_preferences = {
        "interests": (
            explicit["interests"]
            + [key for key, weight in inferred["interests"].items() for _ in range(weight)]
        ),
        "vibe": (
            explicit["vibe"]
            + [key for key, weight in inferred["vibe"].items() for _ in range(weight)]
        ),
    }

    gifts = retrieve_gifts(
        query=query,
        user_id=user_id,
        max_price=max_price,
        days_until_needed=days_until_needed,
        preferences=merged_preferences,
    )

    llm_response, tokens_used = generate_gift_response(
        query=query,
        gifts=gifts,
        preferences=merged_preferences,
    )

    try:
        record_token_usage(
            client=db,
            ip_address=ip_address,
            tokens=tokens_used,
            model="gpt-4o-mini",
            endpoint="/recommend"
        )
    except Exception as e:
        logger.error("Failed to record token usage: %s" % str(e))

    return llm_response

# Health Check
@app.get("/")
def health():
    return {"status": "ok"}