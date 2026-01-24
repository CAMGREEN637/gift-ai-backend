# app/retrieval.py

from openai import OpenAI
import os
from app.vector_store import collection
from dotenv import load_dotenv
from typing import List, Dict, Optional
from app.persistence import get_feedback

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --------------------------------------------------
# Normalization Helpers
# --------------------------------------------------

def normalize_list_field(value) -> List[str]:
    if isinstance(value, list):
        return [v.strip().lower() for v in value]
    if isinstance(value, str):
        return [v.strip().lower() for v in value.split(",") if v.strip()]
    return []

def normalize_preferences(preferences: Optional[Dict]) -> Dict:
    if not preferences:
        return {"interests": [], "vibe": []}

    return {
        "interests": [i.lower() for i in preferences.get("interests", [])],
        "vibe": [v.lower() for v in preferences.get("vibe", [])],
    }

# --------------------------------------------------
# Scoring Logic
# --------------------------------------------------

def compute_score(
    gift: Dict,
    preferences: Dict,
    user_id: Optional[str]
) -> Dict:
    interest_matches = set(gift["interests"]) & set(preferences["interests"])
    vibe_matches = set(gift["vibe"]) & set(preferences["vibe"])

    interest_score = len(interest_matches) * 3
    vibe_score = len(vibe_matches) * 2

    feedback_score = 0
    if user_id:
        history = get_feedback(user_id)
        for entry in history:
            if entry["gift_name"] == gift["name"]:
                feedback_score += 4 if entry["liked"] else -6

    total_score = interest_score + vibe_score + feedback_score

    return {
        "total": total_score,
        "breakdown": {
            "interest_match": len(interest_matches),
            "vibe_match": len(vibe_matches),
            "feedback": feedback_score
        }
    }

def compute_confidence(score: float) -> float:
    # Smooth mapping: score → confidence
    confidence = 0.5 + (score * 0.07)
    return round(min(max(confidence, 0.5), 0.95), 2)

def build_ranking_reasons(gift: Dict, score_data: Dict) -> List[str]:
    reasons = []

    if score_data["breakdown"]["interest_match"] > 0:
        reasons.append("Matches your interests")

    if score_data["breakdown"]["vibe_match"] > 0:
        reasons.append("Fits your preferred vibe")

    if score_data["breakdown"]["feedback"] > 0:
        reasons.append("You liked something similar before")

    if not reasons:
        reasons.append("Popular and generally well-reviewed")

    return reasons

# --------------------------------------------------
# Main Retrieval Pipeline
# --------------------------------------------------

def retrieve_gifts(
    query: str,
    user_id: Optional[str] = None,
    k: int = 5,
    max_price: Optional[int] = None,
    preferences: Optional[Dict] = None
) -> List[Dict]:

    preferences = normalize_preferences(preferences)

    # 1. Embed query
    embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    ).data[0].embedding

    # 2. Vector search
    results = collection.query(
        query_embeddings=[embedding],
        n_results=20
    )

    gifts = results["metadatas"][0]

    # 3. Normalize gift metadata
    for g in gifts:
        g["interests"] = normalize_list_field(g.get("interests"))
        g["vibe"] = normalize_list_field(g.get("vibe"))

    # 4. Price filter
    if max_price is not None:
        gifts = [g for g in gifts if g.get("price", 0) <= max_price]

    enriched = []

    # 5. Score + enrich
    for gift in gifts:
        score_data = compute_score(gift, preferences, user_id)
        confidence = compute_confidence(score_data["total"])

        enriched.append({
            **gift,
            "score": score_data["total"],
            "confidence": confidence,
            "score_breakdown": score_data["breakdown"],
            "ranking_reasons": build_ranking_reasons(gift, score_data)
        })

    # 6. Sort + return top-k
    enriched.sort(key=lambda g: g["score"], reverse=True)
    return enriched[:k]







