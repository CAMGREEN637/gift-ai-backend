# app/main.py

import os
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
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

# Import admin router
from app.admin_api import router as admin_router

# --------------------------------------------------
# Configure logging
# --------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------------------------------------
# App Setup (ONLY ONE INSTANCE!)
# --------------------------------------------------
app = FastAPI(title="Gift AI Backend")

# --------------------------------------------------
# Mount static files FIRST (before routes)
# --------------------------------------------------
try:
    # Static files are in app/static/
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"✓ Static files mounted from: {static_dir}")
except Exception as e:
    logger.warning(f"Could not mount static files: {str(e)}")

# --------------------------------------------------
# Include admin router
# --------------------------------------------------
app.include_router(admin_router)


# --------------------------------------------------
# Startup: initialize database
# --------------------------------------------------
@app.on_event("startup")
def startup():
    init_db()


# --------------------------------------------------
# API Key Protection (ADMIN ONLY)
# --------------------------------------------------
def require_api_key(x_api_key: str = Header(None)):
    expected_key = os.getenv("BACKEND_API_KEY")

    if not expected_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


# --------------------------------------------------
# CORS (Frontend Access)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://web-production-314d8.up.railway.app",
        "*"  # Allow all origins for development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Image Proxy Endpoints
# --------------------------------------------------
@app.get("/proxy-image")
async def proxy_image(url: str):
    """
    Proxy endpoint to fetch images and bypass CORS restrictions.
    Usage: /proxy-image?url=https://m.media-amazon.com/...
    """
    logger.info(f"Proxying image request for: {url}")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            # Add headers to mimic a browser request
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.amazon.com/"
            }

            response = await client.get(url, headers=headers)

            logger.info(f"Image fetch status: {response.status_code}")

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "image/jpeg")
                logger.info(f"Successfully fetched image, content-type: {content_type}")

                return Response(
                    content=response.content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                        "Access-Control-Allow-Origin": "*"
                    }
                )
            else:
                logger.error(f"Failed to fetch image: Status {response.status_code}")
                return Response(
                    content=f"Failed to fetch image: {response.status_code}",
                    status_code=response.status_code
                )

    except httpx.TimeoutException:
        logger.error(f"Timeout fetching image: {url}")
        return Response(content="Timeout fetching image", status_code=504)
    except Exception as e:
        logger.error(f"Error fetching image: {str(e)}")
        return Response(content=f"Error: {str(e)}", status_code=500)


@app.get("/test-proxy")
async def test_proxy():
    """Test the proxy with a known Amazon image"""
    test_url = "https://m.media-amazon.com/images/I/71zK6H8F1TL._AC_SL1500_.jpg"
    logger.info(f"Testing proxy with: {test_url}")
    return await proxy_image(test_url)


# --------------------------------------------------
# Preferences Endpoint (Explicit User Input)
# --------------------------------------------------
@app.post("/preferences")
def save_user_preferences(preferences: PreferencesRequest):
    save_preferences(
        user_id=preferences.user_id,
        interests=preferences.interests,
        vibe=preferences.vibe,
    )
    return {"status": "saved"}


# --------------------------------------------------
# Feedback Endpoint
# --------------------------------------------------
@app.post("/feedback")
def submit_feedback(feedback: GiftFeedback):
    save_feedback(
        user_id=feedback.user_id,
        gift_name=feedback.gift_name,
        liked=feedback.liked,
    )

    # NOTE:
    # Inferred preferences are NOT updated here yet
    # This will be added once gift → category mapping exists

    return {"status": "feedback recorded"}


# --------------------------------------------------
# Recommendation Endpoint (PUBLIC)
# --------------------------------------------------
@app.get("/recommend")
def recommend(
        query: str,
        user_id: Optional[str] = None,
        max_price: Optional[int] = None,
        db: Client = Depends(get_db),
        ip_address: str = Depends(check_rate_limit_dependency)
):
    logger.info(f"Recommendation request from IP: {ip_address}, query: {query}")

    # ---------------------------
    # Load explicit preferences
    # ---------------------------
    explicit = get_preferences(user_id) if user_id else None
    explicit = explicit or {"interests": [], "vibe": []}

    # ---------------------------
    # Load inferred preferences
    # ---------------------------
    inferred = get_inferred(user_id) if user_id else {"interests": {}, "vibe": {}}

    # ---------------------------
    # Merge explicit + inferred
    # ---------------------------
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

    # ---------------------------
    # Retrieve gifts
    # ---------------------------
    gifts = retrieve_gifts(
        query=query,
        user_id=user_id,
        max_price=max_price,
        preferences=merged_preferences,
    )

    # ---------------------------
    # Generate response
    # ---------------------------
    llm_response, tokens_used = generate_gift_response(
        query=query,
        gifts=gifts,
        preferences=merged_preferences,
    )

    # ---------------------------
    # Record token usage
    # ---------------------------
    try:
        record_token_usage(
            client=db,
            ip_address=ip_address,
            tokens=tokens_used,
            model="gpt-4o-mini",
            endpoint="/recommend"
        )
        logger.info(f"Recorded {tokens_used} tokens for IP: {ip_address}")
    except Exception as e:
        logger.error(f"Failed to record token usage: {str(e)}")
        # Don't fail the request if token recording fails

    return llm_response


# --------------------------------------------------
# Admin Endpoint (Protected)
# --------------------------------------------------
@app.post("/admin/load-vectors", dependencies=[Depends(require_api_key)])
def load_vectors():
    return {"status": "Vectors loaded"}


# --------------------------------------------------
# Admin Dashboard
# --------------------------------------------------
@app.get("/admin/products", response_class=HTMLResponse)
async def admin_dashboard():
    """Serve the admin product management dashboard"""
    try:
        # Get path to admin.html in app/static/
        html_path = Path(__file__).parent / "static" / "admin.html"

        logger.info(f"Loading admin dashboard from: {html_path}")

        # Use UTF-8 encoding to handle emojis and special characters
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
            logger.info("✓ Admin dashboard loaded successfully")
            return HTMLResponse(content=content)

    except FileNotFoundError:
        logger.error(f"Admin dashboard not found at: {html_path}")
        return HTMLResponse(
            content=f"""
            <h1>Admin dashboard not found</h1>
            <p>Expected location: {html_path}</p>
            <p>Make sure app/static/admin.html exists</p>
            """,
            status_code=404
        )
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        return HTMLResponse(
            content=f"<h1>Error loading admin page</h1><p>{str(e)}</p>",
            status_code=500
        )


# --------------------------------------------------
# Health Check
# --------------------------------------------------
@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/debug/gifts-simple")
async def debug_gifts_simple():
    """Simpler debug endpoint"""
    try:
        import os
        from supabase import create_client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")

        if not url or not key:
            return {"error": "Missing Supabase credentials"}

        supabase = create_client(url, key)
        response = supabase.table('gifts').select('*').limit(5).execute()

        return {
            "status": "ok",
            "count": len(response.data) if response.data else 0,
            "gifts": response.data
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/debug/quick-test")
async def quick_test():
    """Quick test to see where retrieval fails"""
    from app.database import get_db

    results = {}

    # Step 1: Can we connect to database?
    try:
        db = get_db()
        results["database_connection"] = "✅ OK"
    except Exception as e:
        results["database_connection"] = f"❌ FAILED: {str(e)}"
        return results

    # Step 2: Can we get gifts from Supabase?
    try:
        response = db.table('gifts').select('*').limit(5).execute()
        results["database_query"] = f"✅ OK - Found {len(response.data)} gifts"
        results["sample_gift_names"] = [g.get("name") for g in response.data]
    except Exception as e:
        results["database_query"] = f"❌ FAILED: {str(e)}"
        return results

    # Step 3: Can retrieval.py be imported?
    try:
        from app.retrieval import retrieve_gifts
        results["import_retrieval"] = "✅ OK"
    except Exception as e:
        results["import_retrieval"] = f"❌ FAILED: {str(e)}"
        return results

    # Step 4: Can retrieve_gifts run?
    try:
        gifts = retrieve_gifts(query="test", k=10)
        results["retrieve_gifts"] = f"✅ OK - Returned {len(gifts)} gifts"
        if gifts:
            results["first_gift"] = gifts[0].get("name", "NO NAME")
        else:
            results["first_gift"] = "No gifts returned!"
    except Exception as e:
        results["retrieve_gifts"] = f"❌ FAILED: {str(e)}"
        import traceback
        results["traceback"] = traceback.format_exc()

    return results