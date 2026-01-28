# app/retrieval.py

from openai import OpenAI
import os
from typing import List, Dict, Optional
from dotenv import load_dotenv

from app.vector_store import collection
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
# Scoring Helpers
# --------------------------------------------------

def distance_to_relevance(distance: float) -> float:
    """
    Convert Chroma distance (lower = better)
    into relevance score (0–1)
    """
    return max(0.0, 1.0 - distance)


def compute_confidence(
    gift: Dict,
    distance: float,
    preferences: Dict,
    user_id: Optional[str]
) -> Dict:
    """
    Compute final confidence score using:
    - semantic relevance (primary)
    - interest matches
    - vibe matches
    - feedback history
    """

    relevance = distance_to_relevance(distance)

    interest_matches = set(gift["interests"]) & set(preferences["interests"])
    vibe_matches = set(gift["vibe"]) & set(preferences["vibe"])

    interest_score = len(interest_matches) * 0.15
    vibe_score = len(vibe_matches) * 0.10

    feedback_score = 0.0
    if user_id:
        history = get_feedback(user_id)
        for entry in history:
            if entry["gift_name"] == gift["name"]:
                feedback_score += 0.2 if entry["liked"] else -0.3

    confidence = (
        0.55 * relevance +
        interest_score +
        vibe_score +
        feedback_score
    )

    confidence = round(min(max(confidence, 0.35), 0.95), 2)

    return {
        "confidence": confidence,
        "breakdown": {
            "relevance": round(relevance, 2),
            "interest_match": len(interest_matches),
            "vibe_match": len(vibe_matches),
            "feedback": feedback_score
        }
    }


def build_ranking_reasons(gift: Dict, breakdown: Dict) -> List[str]:
    reasons = []

    if breakdown["interest_match"] > 0:
        reasons.append("Matches their interests")

    if breakdown["vibe_match"] > 0:
        reasons.append("Fits the desired vibe")

    if breakdown["feedback"] > 0:
        reasons.append("Based on past likes")

    if not reasons:
        reasons.append("Strong match for this request")

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

    # 2. Vector search (INCLUDE distances)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=20,
        include=["metadatas", "distances"]
    )

    gifts = results["metadatas"][0]
    distances = results["distances"][0]

    # 3. Normalize gift metadata
    for g in gifts:
        g["interests"] = normalize_list_field(g.get("interests"))
        g["vibe"] = normalize_list_field(g.get("vibe"))

    # 4. Price filter
    if max_price is not None:
        gifts_with_distances = [
            (g, d) for g, d in zip(gifts, distances)
            if g.get("price", 0) <= max_price
        ]
    else:
        gifts_with_distances = list(zip(gifts, distances))

    enriched = []

    # 5. Score + enrich
    for gift, distance in gifts_with_distances:
        score_data = compute_confidence(
            gift=gift,
            distance=distance,
            preferences=preferences,
            user_id=user_id
        )

        enriched.append({
            **gift,
            "confidence": score_data["confidence"],
            "ranking_reasons": build_ranking_reasons(
                gift,
                score_data["breakdown"]
            )
        })

    # 6. Sort by confidence + return top-k
    enriched.sort(key=lambda g: g["confidence"], reverse=True)
    return enriched[:k]







