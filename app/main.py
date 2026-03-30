# app/main.py

import os
import asyncio
import time
from typing import Optional, List
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Depends, Response, Query
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
from app.user_profile_api import router as user_profile_router  # NEW

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
app.include_router(user_profile_router)  # NEW


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


# Recommendation Endpoint
@app.get("/recommend")
async def recommend(
        query: str,
        user_id: Optional[str] = None,
        partner_id: Optional[str] = None,
        partner_name: Optional[str] = None,
        max_price: Optional[int] = None,
        min_price: Optional[int] = None,
        days_until_needed: Optional[int] = None,
        occasion: Optional[str] = None,
        relationship: Optional[str] = None,
        interests: List[str] = Query(default=[]),  # Quiz interests passed directly
        db: Client = Depends(get_db),
        ip_address: str = Depends(check_rate_limit_dependency)
):
    t_total = time.time()
    logger.info("Recommendation request: query=%s, partner_id=%s, partner_name=%s, occasion=%s, relationship=%s, interests=%s" % (
        query, partner_id, partner_name, occasion, relationship, interests
    ))

    # --- PARALLEL: fetch user preferences + recipient profile simultaneously ---
    # These are independent DB reads that previously ran sequentially before retrieve_gifts().
    t_db = time.time()

    async def _fetch_preferences():
        return await asyncio.to_thread(get_preferences, user_id) if user_id else None

    async def _fetch_inferred():
        return await asyncio.to_thread(get_inferred, user_id) if user_id else {"interests": {}, "vibe": {}}

    async def _fetch_recipient_profile():
        if not (partner_id and user_id):
            return None
        try:
            return await asyncio.to_thread(
                lambda: db.table('user_profiles').select('saved_recipients').eq('user_id', user_id).single().execute()
            )
        except Exception as e:
            logger.error("Failed to load recipient: %s" % str(e))
            return None

    explicit_raw, inferred, profile_response = await asyncio.gather(
        _fetch_preferences(),
        _fetch_inferred(),
        _fetch_recipient_profile(),
    )
    logger.info(f"[PERF] Parallel DB reads: {(time.time() - t_db)*1000:.0f}ms")

    explicit = explicit_raw or {"interests": [], "vibe": []}

    merged_preferences = {
        "interests": list(set(
            interests  # Quiz interests take priority
            + explicit["interests"]
            + [key for key, weight in inferred["interests"].items() for _ in range(weight)]
        )),
        "vibe": (
                explicit["vibe"]
                + [key for key, weight in inferred["vibe"].items() for _ in range(weight)]
        ),
    }

    logger.info("Merged preferences: %s" % merged_preferences)

    # Resolve recipient profile from parallel fetch result
    recipient_profile = None
    partner_context = None
    partner_profile = None
    partner_gift_history = []

    if profile_response and profile_response.data:
        saved_recipients = profile_response.data.get('saved_recipients', [])
        recipient = next((r for r in saved_recipients if r.get('id') == partner_id), None)
        if recipient:
            logger.info("Loaded recipient: %s" % recipient.get('name'))
            recipient_profile = recipient
            partner_profile = recipient
            partner_context = {
                "name": recipient.get("name"),
                "interests": recipient.get("interests", []),
                "vibe": recipient.get("vibe", []),
                "personality": recipient.get("personality_traits", []),
            }

    # If no partner_id but we have a partner_name from the quiz, use it
    if not partner_context and partner_name:
        logger.info("Using partner name from query: %s" % partner_name)
        partner_context = {
            "name": partner_name,
            "interests": [],
            "vibe": [],
            "personality": []
        }

    # Retrieve gifts — runs embedding + vector search + scoring
    t_retrieval = time.time()
    gifts = await asyncio.to_thread(
        retrieve_gifts,
        query,
        user_id,
        10,         # k
        min_price,
        max_price,
        days_until_needed,
        merged_preferences,
        partner_profile,
        partner_gift_history,
    )
    logger.info(f"[PERF] retrieve_gifts: {(time.time() - t_retrieval)*1000:.0f}ms")

    # --- CONFIDENCE THRESHOLD FILTER ---
    # Only keep gifts that have a match confidence of 80% or higher (0.8+)
    original_count = len(gifts)
    gifts = [g for g in gifts if g.get("confidence", 0) >= 0.8]
    if original_count != len(gifts):
        logger.info(f"Filtered out {original_count - len(gifts)} gifts below the 80% confidence threshold.")

    # Build session context for LLM
    session_context = {
        "occasion": occasion,
        "relationship": relationship,
        "budget": max_price,
        "days_until_needed": days_until_needed
    }

    # Generate response — single batched LLM call for all gift reasons
    t_llm = time.time()
    llm_response, tokens_used = await asyncio.to_thread(
        generate_gift_response,
        query,
        gifts,
        merged_preferences,
        partner_context,
        session_context,
    )
    logger.info(f"[PERF] generate_gift_response: {(time.time() - t_llm)*1000:.0f}ms")

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

    logger.info(f"[PERF] Total /recommend: {(time.time() - t_total)*1000:.0f}ms")
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