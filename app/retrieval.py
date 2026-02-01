# app/retrieval.py

from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Optional

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
            "feedback": feedback_score,
        },
    }

def semantic_score_from_distance(distance: float) -> float:
    """
    Convert vector distance into a positive score.
    Lower distance = higher relevance.
    """
    return max(0.0, 1.5 - distance) * 10

def compute_relative_confidences(scores: List[float]) -> List[float]:
    """
    Convert raw scores into relative confidence values (0.55–0.95).
    """
    if not scores:
        return []

    min_score = min(scores)
    max_score = max(scores)

    # All equal → default confidence
    if min_score == max_score:
        return [0.6 for _ in scores]

    confidences = []
    for s in scores:
        normalized = (s - min_score) / (max_score - min_score)
        confidence = 0.55 + normalized * 0.4
        confidences.append(round(confidence, 2))

    return confidences

def build_ranking_reasons(gift: Dict, score_data: Dict) -> List[str]:
    reasons = []

    if score_data["breakdown"]["interest_match"] > 0:
        reasons.append("Matches your interests")

    if score_data["breakdown"]["vibe_match"] > 0:
        reasons.append("Fits your preferred vibe")

    if score_data["breakdown"]["feedback"] > 0:
        reasons.append("You liked something similar before")

    if not reasons:
        reasons.append("Relevant to your search")

    return reasons

# --------------------------------------------------
# Main Retrieval Pipeline
# --------------------------------------------------

def retrieve_gifts(
    query: str,
    user_id: Optional[str] = None,
    k: int = 5,
    max_price: Optional[int] = None,
    preferences: Optional[Dict] = None,
) -> List[Dict]:

    preferences = normalize_preferences(preferences)

    # 1. Embed query
    embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    ).data[0].embedding

    # 2. Vector search (include distances!)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=20,
        include=["metadatas", "distances"],
    )

    gifts = results["metadatas"][0]
    distances = results["distances"][0]

    # 3. Normalize gift metadata
    for g in gifts:
        g["interests"] = normalize_list_field(g.get("interests"))
        g["vibe"] = normalize_list_field(g.get("vibe"))

    # 4. Price filter
    if max_price is not None:
        gifts = [g for g in gifts if g.get("price", 0) <= max_price]

    # 5. Score gifts (semantic + heuristic)
    scored = []
    for gift, distance in zip(gifts, distances):
        score_data = compute_score(gift, preferences, user_id)
        semantic_score = semantic_score_from_distance(distance)

        total_score = score_data["total"] + semantic_score

        scored.append({
            **gift,
            "score": total_score,
            "ranking_reasons": build_ranking_reasons(gift, score_data),
        })

    # 6. Sort by score
    scored.sort(key=lambda g: g["score"], reverse=True)

    # 7. Compute relative confidence
    scores = [g["score"] for g in scored]
    confidences = compute_relative_confidences(scores)

    # 8. Attach confidence
    for gift, conf in zip(scored, confidences):
        gift["confidence"] = conf

    return scored[:k]






