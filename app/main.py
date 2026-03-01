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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://web-production-314d8.up.railway.app",
        "*"
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
                        "Access-Control-Allow-Origin": "*"
                    }
                )
            else:
                return Response(
                    content="Failed to fetch image: %d" % response.status_code,
                    status_code=response.status_code
                )
    except Exception as e:
        logger.error("Error fetching image: %s" % str(e))
        return Response(content="Error: %s" % str(e), status_code=500)

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

# Recommendation Endpoint (Updated with full context)
@app.get("/recommend")
def recommend(
    query: str,
    user_id: Optional[str] = None,
    partner_id: Optional[str] = None,
    max_price: Optional[int] = None,
    days_until_needed: Optional[int] = None,
    occasion: Optional[str] = None,  # NEW
    relationship: Optional[str] = None,  # NEW
    db: Client = Depends(get_db),
    ip_address: str = Depends(check_rate_limit_dependency)
):
    logger.info("Recommendation request: query=%s, partner_id=%s, occasion=%s, relationship=%s" % (
        query, partner_id, occasion, relationship
    ))

    # Load session preferences
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

    # Load partner profile (persistent data - separate from session)
    partner_profile = None
    partner_gift_history = []
    partner_context = None

    if partner_id and user_id:
        try:
            # Get partner profile
            partner_response = db.table('partners').select('*').eq('id', partner_id).eq('user_id', user_id).single().execute()
            if partner_response.data:
                partner_profile = partner_response.data
                logger.info("Loaded partner profile: %s" % partner_profile.get('name'))

                # Update search timestamp
                db.table('partners').update({
                    'last_gift_search_at': datetime.now().isoformat(),
                    'gift_search_count': partner_profile.get('gift_search_count', 0) + 1
                }).eq('id', partner_id).execute()

                # Get purchased gift IDs
                history_response = db.table('partner_gift_history').select('gift_id').eq('partner_id', partner_id).eq('purchased', True).execute()
                partner_gift_history = [item['gift_id'] for item in history_response.data if item.get('gift_id')]
                logger.info("Excluding %d previously purchased gifts" % len(partner_gift_history))

                # Build partner context for LLM
                partner_context = {
                    "name": partner_profile.get("name"),
                    "interests": partner_profile.get("interests", []),
                    "vibe": partner_profile.get("vibe", []),
                    "personality": partner_profile.get("personality_traits", []),
                }
        except Exception as e:
            logger.error("Failed to load partner profile: %s" % str(e))

    # Retrieve gifts with clean separation
    gifts = retrieve_gifts(
        query=query,
        user_id=user_id,
        max_price=max_price,
        days_until_needed=days_until_needed,
        preferences=merged_preferences,
        partner_profile=partner_profile,
        partner_gift_history=partner_gift_history,
    )

    # Build session context for LLM
    session_context = {
        "occasion": occasion,
        "relationship": relationship,
        "budget": max_price,
        "days_until_needed": days_until_needed
    }

    # Generate response with rich context
    llm_response, tokens_used = generate_gift_response(
        query=query,
        gifts=gifts,
        preferences=merged_preferences,
        partner_context=partner_context,
        session_context=session_context  # NEW
    )

    # Record token usage
    try:
        record_token_usage(
            client=db,
            ip_address=ip_address,
            tokens=tokens_used,
            model="gpt-4o-mini",
            endpoint="/recommend"
        )
        logger.info("Recorded %d tokens for IP: %s" % (tokens_used, ip_address))
    except Exception as e:
        logger.error("Failed to record token usage: %s" % str(e))

    return llm_response

# Admin endpoints
@app.post("/admin/load-vectors", dependencies=[Depends(require_api_key)])
def load_vectors():
    return {"status": "Vectors loaded"}

@app.get("/admin/products", response_class=HTMLResponse)
async def admin_dashboard():
    try:
        html_path = Path(__file__).parent / "static" / "admin.html"
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
            return HTMLResponse(content=content)
    except Exception as e:
        logger.error("Error loading admin dashboard: %s" % str(e))
        return HTMLResponse(content="Error loading admin page", status_code=500)

@app.post("/admin/generate-embeddings")
async def generate_embeddings_for_all_gifts():
    from app.retrieval import get_supabase_client
    from app.embeddings import generate_embedding, create_gift_text_for_embedding, update_gift_embedding
    import traceback

    try:
        supabase = get_supabase_client()
        response = supabase.table('gifts').select('*').is_('embedding', 'null').execute()
        gifts = response.data

        logger.info("Found %d gifts without embeddings" % len(gifts))

        success_count = 0
        error_count = 0

        for gift in gifts:
            try:
                text = create_gift_text_for_embedding(gift)
                logger.info("Generating embedding for: %s" % gift.get('name', '')[:40])
                embedding = generate_embedding(text)

                if embedding:
                    if update_gift_embedding(gift['id'], embedding):
                        success_count += 1
                        logger.info("✓ Saved embedding for: %s" % gift.get('name', '')[:40])
                    else:
                        error_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error("Error processing gift %s: %s" % (gift.get('id', ''), str(e)))
                error_count += 1

        return {
            "status": "complete",
            "total_processed": len(gifts),
            "success": success_count,
            "errors": error_count
        }
    except Exception as e:
        logger.error("Error in generate_embeddings: %s" % str(e))
        return {"status": "error", "error": str(e)}

# Health Check
@app.get("/")
def health():
    return {"status": "ok"}