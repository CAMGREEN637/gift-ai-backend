# app/main.py

import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Depends, Response

from app.retrieval import retrieve_gifts
from app.llm import generate_gift_response
from app.schemas import PreferencesRequest, GiftFeedback
from app.persistence import (
    save_preferences,
    get_preferences,
    save_feedback,
    get_inferred,
)
from app.database import init_db
from fastapi.responses import StreamingResponse
import httpx
import logging
from fastapi.middleware.cors import CORSMiddleware









# --------------------------------------------------
# App Setup
# --------------------------------------------------

app = FastAPI(title="Gift AI Backend")

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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
):
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
    return generate_gift_response(
        query=query,
        gifts=gifts,
        preferences=merged_preferences,
    )

# --------------------------------------------------
# Admin Endpoint (Protected)
# --------------------------------------------------

@app.post("/admin/load-vectors", dependencies=[Depends(require_api_key)])
def load_vectors():
    return {"status": "Vectors loaded"}

# --------------------------------------------------
# Health Check
# --------------------------------------------------

@app.get("/")
def health():
    return {"status": "ok"}


app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Make sure CORS is enabled
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# Test endpoint to verify the proxy works
@app.get("/test-proxy")
async def test_proxy():
    """Test the proxy with a known Amazon image"""
    test_url = "https://m.media-amazon.com/images/I/71zK6H8F1TL._AC_SL1500_.jpg"
    logger.info(f"Testing proxy with: {test_url}")
    return await proxy_image(test_url)
