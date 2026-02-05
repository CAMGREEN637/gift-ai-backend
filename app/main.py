# app/main.py

import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/proxy-image")
async def proxy_image(url: str):
    """
    Proxy endpoint to fetch images and bypass CORS restrictions.
    Usage: /proxy-image?url=https://m.media-amazon.com/...
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)

            if response.status_code == 200:
                return StreamingResponse(
                    iter([response.content]),
                    media_type=response.headers.get("content-type", "image/jpeg")
                )
            else:
                return {"error": "Failed to fetch image"}
    except Exception as e:
        return {"error": str(e)}
