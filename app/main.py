# app/main.py

import os
import asyncio
import time
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Depends, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import httpx
import logging
from datetime import datetime, timezone

from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.retrieval import retrieve_gifts, build_search_query, get_results_headline
from app.llm import generate_gift_response
from app.schemas import (
    PreferencesRequest,
    GiftFeedback,
    RecommendRequest,
    RecommendResponse,
    GiftItem,
)
from app.persistence import (
    save_preferences,
    get_preferences,
    save_feedback,
    get_inferred,
)
from app.database import init_db, get_db
from app.dependencies import check_rate_limit_dependency
from app.rate_limiter import record_token_usage
from app.admin_api import router as admin_router, verify_admin
from supabase import Client

# Import routers
from app.partners_api import router as partners_router
from app.user_profile_api import router as user_profile_router
from app.cron_api import router as cron_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level start time for uptime tracking
start_time = time.time()

# =============================================================================
# SENTRY
# =============================================================================

_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=os.getenv("ENVIRONMENT", "development"),
        integrations=[FastApiIntegration(), StarletteIntegration()],
        traces_sample_rate=0.1,
    )
    logger.info("Sentry initialized")

# =============================================================================
# APP SETUP
# =============================================================================

app = FastAPI(title="Gift AI Backend", version="2.0.0")

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
app.include_router(user_profile_router)
app.include_router(cron_router)


# Startup
@app.on_event("startup")
def startup():
    init_db()


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://web-production-314d8.up.railway.app",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# LOGGING HELPER
# =============================================================================

def log_error(
    action: str,
    error: Exception,
    user_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    payload: dict = {
        "action":     action,
        "error":      str(error),
        "error_type": type(error).__name__,
        "user_id":    user_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    logger.error(json.dumps(payload))


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": str(exc), "code": "VALIDATION_ERROR"},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log_error("unhandled_exception", exc, extra={"path": str(request.url.path)})
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong on our end", "code": "INTERNAL_ERROR"},
    )


# =============================================================================
# API KEY PROTECTION
# =============================================================================

def require_api_key(x_api_key: str = Header(None)):
    expected_key = os.getenv("BACKEND_API_KEY")
    if not expected_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


# =============================================================================
# IMAGE PROXY
# Proxies Amazon images to avoid CORS issues
# =============================================================================

@app.get("/proxy-image")
async def proxy_image(url: str):
    logger.info("Proxying image request for: %s" % url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://www.amazon.com/",
            }
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "image/jpeg")
                return Response(
                    content=response.content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
            else:
                return Response(
                    content="Failed to fetch image: %d" % response.status_code,
                    status_code=response.status_code,
                )
    except Exception as e:
        logger.error("Error fetching image: %s" % str(e))
        return Response(content="Error: %s" % str(e), status_code=500)


# =============================================================================
# PREFERENCES
# =============================================================================

@app.post("/preferences")
def save_user_preferences(preferences: PreferencesRequest):
    save_preferences(
        user_id=preferences.user_id,
        interests=preferences.interests,
        vibe=preferences.vibe,
    )
    return {"status": "saved"}


# =============================================================================
# FEEDBACK
# =============================================================================

@app.post("/feedback")
def submit_feedback(feedback: GiftFeedback):
    save_feedback(
        user_id=feedback.user_id,
        gift_name=feedback.gift_name,
        liked=feedback.liked,
    )
    return {"status": "feedback recorded"}


# =============================================================================
# POST /recommend
# =============================================================================

@app.post("/recommend")
async def recommend(
    body: RecommendRequest,
    stream: bool = Query(default=False),
    db: Client = Depends(get_db),
    ip_address: str = Depends(check_rate_limit_dependency),
):
    t_total = time.time()

    user_id            = body.partner_id
    partner_id         = body.partner_id
    partner_name       = body.partner_name
    _raw_max_price = body.max_price
    if _raw_max_price is not None and _raw_max_price < 0:
        logger.warning("max_price %s is negative — treating as None", _raw_max_price)
        _raw_max_price = None
    max_price          = int(_raw_max_price) if _raw_max_price else None
    days_until_needed  = body.days_until_needed
    occasion           = body.occasion
    relationship_stage = body.relationship_stage
    confidence         = body.confidence

    logger.info(
        "Recommendation request: occasion=%s, stage=%s, partner_name=%s, "
        "confidence=%s, interests=%s, vibes=%s, max_price=%s" % (
            occasion, relationship_stage, partner_name,
            confidence, body.interests, body.vibe, max_price,
        )
    )

    query = build_search_query(body)
    logger.info("Built search query: %s" % query)

    # ------------------------------------------------------------------
    # PARALLEL DB READS
    # ------------------------------------------------------------------
    t_db = time.time()

    async def _fetch_preferences():
        return await asyncio.to_thread(get_preferences, user_id) if user_id else None

    async def _fetch_inferred():
        return (
            await asyncio.to_thread(get_inferred, user_id)
            if user_id
            else {"interests": {}, "vibe": {}}
        )

    async def _fetch_recipient_profile():
        if not (partner_id and user_id):
            return None
        try:
            return await asyncio.to_thread(
                lambda: db.table("user_profiles")
                    .select("saved_recipients")
                    .eq("user_id", user_id)
                    .single()
                    .execute()
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

    quiz_interests = list(body.interests or []) if confidence != "lost" else []

    merged_preferences = {
        "interests": list(set(
            quiz_interests
            + explicit["interests"]
            + [
                key
                for key, weight in inferred["interests"].items()
                for _ in range(weight)
            ]
        )),
        "vibe": (
            list(body.vibe or [])
            + explicit["vibe"]
            + [
                key
                for key, weight in inferred["vibe"].items()
                for _ in range(weight)
            ]
        ),
    }
    logger.info("Merged preferences: %s" % merged_preferences)

    # ------------------------------------------------------------------
    # RESOLVE PARTNER PROFILE
    # ------------------------------------------------------------------
    partner_profile      = None
    partner_context      = None
    partner_gift_history = []

    if profile_response and profile_response.data:
        saved_recipients = profile_response.data.get("saved_recipients", [])
        recipient = next(
            (r for r in saved_recipients if r.get("id") == partner_id), None
        )
        if recipient:
            logger.info("Loaded recipient: %s" % recipient.get("name"))
            partner_profile = recipient
            partner_context = {
                "name":        recipient.get("name"),
                "interests":   recipient.get("interests", []),
                "vibe":        recipient.get("vibe", []),
                "personality": recipient.get("personality_traits", []),
            }

    if not partner_context and partner_name:
        logger.info("Using partner name from request body: %s" % partner_name)
        partner_context = {
            "name":        partner_name,
            "interests":   list(body.interests or []),
            "vibe":        list(body.vibe or []),
            "personality": [],
        }

    # ------------------------------------------------------------------
    # RETRIEVE GIFTS
    # ------------------------------------------------------------------
    _raw_k = body.k
    if _raw_k is not None and not (1 <= _raw_k <= 20):
        logger.warning("k=%s is out of range [1, 20] — clamping to 5", _raw_k)
        _raw_k = 5
    base_k = _raw_k if _raw_k else 5
    exclude_names_lower = [n.lower() for n in (body.exclude_names or [])]
    k = base_k + len(exclude_names_lower)

    t_retrieval = time.time()
    gifts = await asyncio.to_thread(
        retrieve_gifts,
        query,
        user_id,
        None,
        max_price,
        days_until_needed,
        merged_preferences,
        partner_profile,
        partner_gift_history,
        request=body,
        k=k,
    )
    logger.info(f"[PERF] retrieve_gifts: {(time.time() - t_retrieval)*1000:.0f}ms")

    if exclude_names_lower:
        before = len(gifts)
        gifts = [g for g in gifts if g.get("name", "").lower() not in exclude_names_lower]
        logger.info(f"Load more: stripped {before - len(gifts)} already-shown, {len(gifts)} remain")
        gifts = gifts[:base_k]

    if not exclude_names_lower:
        original_count = len(gifts)
        gifts = [g for g in gifts if g.get("confidence", 0) >= 0.65]
        if original_count != len(gifts):
            logger.info(f"Filtered out {original_count - len(gifts)} gifts below 65% confidence")

    session_context = {
        "occasion":           occasion,
        "relationship":       relationship_stage,
        "relationship_stage": relationship_stage,
        "budget":             max_price,
        "days_until_needed":  days_until_needed,
        "confidence":         confidence,
    }

    results_headline, results_subline = get_results_headline(
        occasion or "", relationship_stage
    )

    # ------------------------------------------------------------------
    # NON-STREAMING PATH
    # ------------------------------------------------------------------
    if not stream:
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

        try:
            record_token_usage(
                client=db,
                ip_address=ip_address,
                tokens=tokens_used,
                model="gpt-4o-mini",
                endpoint="/recommend",
            )
            logger.info("Recorded %d tokens for IP: %s" % (tokens_used, ip_address))
        except Exception as e:
            logger.error("Failed to record token usage: %s" % str(e))

        logger.info(f"[PERF] Total /recommend: {(time.time() - t_total)*1000:.0f}ms")

        return {
            **llm_response,
            "occasion":           occasion,
            "relationship_stage": relationship_stage,
            "partner_name":       partner_name,
            "total_found":        len(gifts),
            "confidence":         confidence,
            "results_headline":   results_headline,
            "results_subline":    results_subline,
        }

    # ------------------------------------------------------------------
    # STREAMING PATH — SSE (?stream=true)
    # ------------------------------------------------------------------
    async def event_stream():
        preview_gifts = [
            {
                "name":              g.get("name"),
                "display_name":      g.get("display_name"),
                "price":             g.get("price"),
                "confidence":        g.get("confidence"),
                "image_url":         g.get("image_url"),
                "product_url":       g.get("product_url") or g.get("link", ""),
                "shipping_min_days": g.get("shipping_min_days"),
                "shipping_max_days": g.get("shipping_max_days"),
                "is_prime_eligible": g.get("is_prime_eligible"),
                "already_purchased": g.get("already_purchased", False),
            }
            for g in gifts[:3]
        ]
        logger.info(
            f"[STREAM] Sending preview with {len(preview_gifts)} gifts "
            f"at {(time.time() - t_total)*1000:.0f}ms"
        )
        yield f"data: {json.dumps({'type': 'preview', 'gifts': preview_gifts})}\n\n"

        t_llm = time.time()
        llm_response, tokens_used = await asyncio.to_thread(
            generate_gift_response,
            query,
            gifts,
            merged_preferences,
            partner_context,
            session_context,
        )
        logger.info(
            f"[PERF] generate_gift_response (stream): "
            f"{(time.time() - t_llm)*1000:.0f}ms"
        )

        yield f"data: {json.dumps({'type': 'result', **llm_response, 'occasion': occasion, 'relationship_stage': relationship_stage, 'partner_name': partner_name, 'total_found': len(gifts), 'confidence': confidence, 'results_headline': results_headline, 'results_subline': results_subline})}\n\n"

        yield "data: [DONE]\n\n"

        logger.info(
            f"[PERF] Total /recommend (stream): "
            f"{(time.time() - t_total)*1000:.0f}ms"
        )

        try:
            record_token_usage(
                client=db,
                ip_address=ip_address,
                tokens=tokens_used,
                model="gpt-4o-mini",
                endpoint="/recommend",
            )
        except Exception as e:
            logger.error("Failed to record token usage: %s" % str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

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
    """
    Original endpoint — only processes gifts where embedding IS NULL.
    Use /admin/regenerate-embeddings to force-refresh existing embeddings.
    """
    from app.retrieval import get_supabase_client
    from app.embeddings import (
        generate_embedding,
        create_gift_text_for_embedding,
        update_gift_embedding,
    )

    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("gifts").select("*").is_("embedding", "null").execute()
        )
        gifts = response.data
        logger.info("Found %d gifts without embeddings" % len(gifts))

        success_count = 0
        error_count   = 0

        for gift in gifts:
            try:
                text = create_gift_text_for_embedding(gift)
                logger.info("Generating embedding for: %s" % gift.get("name", "")[:40])
                embedding = generate_embedding(text)
                if embedding:
                    if update_gift_embedding(gift["id"], embedding):
                        success_count += 1
                        logger.info("✓ Saved embedding for: %s" % gift.get("name", "")[:40])
                    else:
                        error_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error("Error processing gift %s: %s" % (gift.get("id", ""), str(e)))
                error_count += 1

        return {
            "status":          "complete",
            "total_processed": len(gifts),
            "success":         success_count,
            "errors":          error_count,
        }
    except Exception as e:
        logger.error("Error in generate_embeddings: %s" % str(e))
        return {"status": "error", "error": str(e)}


# =============================================================================
# REGENERATE EMBEDDINGS — request model + endpoint
# =============================================================================

class RegenerateEmbeddingsRequest(BaseModel):
    gift_ids: Optional[List[str]] = None


@app.post("/admin/regenerate-embeddings", dependencies=[Depends(verify_admin)])
async def regenerate_embeddings(body: RegenerateEmbeddingsRequest = None):
    """
    Force re-generate embeddings for specific gifts by ID, or the entire catalog.

    Use this after tag migrations — the original /admin/generate-embeddings
    skips gifts that already have an embedding, so it won't pick up tag changes.
    This endpoint ignores existing embeddings entirely.

    Body (optional JSON):
        {}                              → re-generates ALL gifts (full catalog)
        { "gift_ids": ["gift_0001"] }   → targeted refresh for specific IDs

    110 gifts costs ~$0.00 at text-embedding-3-small rates (~30 seconds).
    """
    from app.retrieval import get_supabase_client
    from app.embeddings import (
        generate_embedding,
        create_gift_text_for_embedding,
        update_gift_embedding,
    )

    try:
        supabase = get_supabase_client()

        gift_ids = body.gift_ids if body else None

        if gift_ids:
            response = (
                supabase.table("gifts")
                .select("*")
                .in_("id", gift_ids)
                .execute()
            )
            mode = f"targeted ({len(gift_ids)} IDs)"
        else:
            # Full catalog refresh — ignores existing embeddings
            response = supabase.table("gifts").select("*").execute()
            mode = "full catalog"

        gifts = response.data or []
        logger.info(f"Re-embedding {len(gifts)} gifts — mode: {mode}")

        success_count = 0
        error_count   = 0
        skipped_ids   = []

        for gift in gifts:
            try:
                text = create_gift_text_for_embedding(gift)
                embedding = generate_embedding(text)

                if embedding:
                    if update_gift_embedding(gift["id"], embedding):
                        success_count += 1
                        logger.info(
                            f"✓ Re-embedded: "
                            f"{gift.get('display_name') or gift.get('name', '')[:50]}"
                        )
                    else:
                        error_count += 1
                        skipped_ids.append(gift["id"])
                else:
                    error_count += 1
                    skipped_ids.append(gift["id"])

            except Exception as e:
                logger.error(f"Error re-embedding {gift.get('id')}: {e}")
                error_count += 1
                skipped_ids.append(gift.get("id"))

        return {
            "status":          "complete",
            "mode":            mode,
            "total_processed": len(gifts),
            "success":         success_count,
            "errors":          error_count,
            "skipped_ids":     skipped_ids,
        }

    except Exception as e:
        logger.error(f"Error in regenerate_embeddings: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health")
async def health_check():
    from app.database import check_db_connection
    db_ok = await asyncio.to_thread(check_db_connection)
    uptime = int(time.time() - start_time)
    status = "ok" if db_ok else "degraded"
    return {
        "status":         status,
        "uptime_seconds": uptime,
        "checks": {
            "api":      "ok",
            "database": "ok" if db_ok else "error",
        },
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


@app.get("/")
def health():
    return {"status": "ok", "version": "2.0.0"}