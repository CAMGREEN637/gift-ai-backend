# app/main.py

from typing import Optional
from fastapi import FastAPI
from app.retrieval import retrieve_gifts
from app.llm import generate_gift_response
from app.schemas import PreferencesRequest, GiftFeedback
from app.persistence import (
    save_preferences,
    get_preferences,
    save_feedback,
    get_inferred
)
from app.database import init_db

app = FastAPI()

# --------------------------------------------------
# Startup
# --------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()

# --------------------------------------------------
# Preferences Endpoint (EXPLICIT)
# --------------------------------------------------

@app.post("/preferences")
def save_user_preferences(preferences: PreferencesRequest):
    save_preferences(
        user_id=preferences.user_id,
        interests=preferences.interests,
        vibe=preferences.vibe
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
        liked=feedback.liked
    )
    return {"status": "feedback recorded"}

# --------------------------------------------------
# Recommendation Endpoint
# --------------------------------------------------

@app.get("/recommend")
def recommend(
    query: str,
    user_id: Optional[str] = None,
    max_price: Optional[int] = None
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
    # Merge preferences
    # ---------------------------
    merged_preferences = {
        "interests": (
            explicit["interests"] +
            [k for k, v in inferred["interests"].items() for _ in range(v)]
        ),
        "vibe": (
            explicit["vibe"] +
            [k for k, v in inferred["vibe"].items() for _ in range(v)]
        )
    }

    # ---------------------------
    # Retrieve gifts
    # ---------------------------
    gifts = retrieve_gifts(
        query=query,
        user_id=user_id,
        max_price=max_price,
        preferences=merged_preferences
    )

    return generate_gift_response(
        query=query,
        gifts=gifts,
        preferences=merged_preferences
    )
