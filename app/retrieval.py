import os
import logging
import traceback
from typing import List, Dict, Optional
from dotenv import load_dotenv

# We no longer need OpenAI here for embeddings generation 
# if we import the helper, but we keep the client setup just in case.
from app.embeddings import generate_embedding
from app.persistence import get_feedback

load_dotenv()
logger = logging.getLogger(__name__)


# --------------------------------------------------
# Supabase Client
# --------------------------------------------------

def get_supabase_client():
    """Get Supabase client directly"""
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")

    if not url or not key:
        raise Exception("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

    return create_client(url, key)


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
# Scoring Logic (Personalization)
# --------------------------------------------------

def compute_profile_score(
        gift: Dict,
        preferences: Dict,
        user_id: Optional[str]
) -> Dict:
    """
    Compute preference-based scoring (interests/vibe from user profile).
    This adds a 'boost' to the vector similarity score.
    """
    interest_matches = set(gift["interests"]) & set(preferences["interests"])
    vibe_matches = set(gift["vibe"]) & set(preferences["vibe"])

    # Weighting: Interests are worth more than vibes
    interest_score = len(interest_matches) * 5.0
    vibe_score = len(vibe_matches) * 3.0

    feedback_score = 0
    if user_id:
        history = get_feedback(user_id)
        for entry in history:
            if entry["gift_name"] == gift["name"]:
                feedback_score += 5 if entry["liked"] else -10

    total_score = interest_score + vibe_score + feedback_score

    return {
        "total": total_score,
        "breakdown": {
            "interest_match": len(interest_matches),
            "vibe_match": len(vibe_matches),
            "feedback": feedback_score,
        },
    }


def compute_hybrid_confidence(scores: List[float]) -> List[float]:
    """
    Convert raw scores into confidence values.
    Uses 'Absolute' quality + 'Relative' ranking.
    Prevents the 'everything is 60%' issue.
    """
    if not scores:
        return []

    # ANCHOR_SCORE: What we consider a "Great" match.
    # Vector similarity is 0-100. A similarity of 80 (0.8) is usually very good.
    # Plus profile points (e.g., +10). So ~85 is a strong anchor.
    ANCHOR_SCORE = 82.0

    confidences = []
    max_score = max(scores)

    for s in scores:
        # 1. Absolute Score: How good is this mathematically?
        # If score is > Anchor, we approach 95%. If low, we drop.
        # Logic: 0.50 base + up to 0.45 based on closeness to anchor
        ratio = min(s / ANCHOR_SCORE, 1.2)  # Cap at 1.2x anchor
        absolute_conf = 0.50 + (0.45 * ratio)

        # 2. Relative Boost: Is this the specific winner?
        # If this is the #1 result and it has a decent gap, boost it.
        relative_boost = 0.0
        if s == max_score and len(scores) > 1:
            relative_boost = 0.03

        final_conf = min(0.98, absolute_conf + relative_boost)
        confidences.append(round(final_conf, 2))

    return confidences


def build_ranking_reasons(gift: Dict, score_data: Dict) -> List[str]:
    reasons = []

    if score_data["breakdown"]["interest_match"] > 0:
        reasons.append("Matches your interests")

    if score_data["breakdown"]["vibe_match"] > 0:
        reasons.append("Fits your preferred vibe")

    if score_data["breakdown"]["feedback"] > 0:
        reasons.append("You liked something similar before")

    # If no specific profile reasons, fallback to vector context
    if not reasons:
        reasons.append("Matches your search description")

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
    """
    Retrieve gifts using vector similarity search (Supabase pgvector).
    """
    preferences = normalize_preferences(preferences)

    try:
        supabase = get_supabase_client()
        logger.info("✓ Supabase client initialized")

        # 1. Generate embedding for the query
        query_embedding = generate_embedding(query)

        if not query_embedding:
            logger.error("Failed to generate query embedding")
            return []

        # 2. Vector Search (RPC Call)
        # We lower the threshold slightly (0.3) to ensure we get enough candidates
        # to filter through, but high enough to exclude total junk.
        response = supabase.rpc(
            'match_gifts',
            {
                'query_embedding': query_embedding,
                'match_threshold': 0.3,
                'match_count': 20
            }
        ).execute()

        if not response.data:
            logger.warning("No gifts found via vector search")
            return []

        gifts = response.data
        logger.info("✓ Retrieved %d gifts via vector search" % len(gifts))

    except Exception as e:
        logger.error("Error in vector search: " + str(e))
        logger.error(traceback.format_exc())
        return []

    # 3. Process and Score Results
    scored = []

    for g in gifts:
        # Normalize fields
        g["interests"] = normalize_list_field(g.get("interests", []))
        g["vibe"] = normalize_list_field(g.get("vibe", []))
        g["categories"] = normalize_list_field(g.get("categories", []))
        g["occasions"] = normalize_list_field(g.get("occasions", []))

        # Base Vector Score (Convert 0-1 float to 0-100 score)
        # OpenAI embeddings usually range 0.70-0.90 for relevant items.
        # We multiply by 100 to make it easier to work with.
        vector_score = g.get('similarity', 0) * 100

        # Personalization Score (Profile Matches)
        profile_data = compute_profile_score(g, preferences, user_id)

        # Final Combined Score
        total_score = vector_score + profile_data["total"]

        scored.append({
            **g,
            "score": total_score,
            "vector_similarity": g.get('similarity', 0),
            "ranking_reasons": build_ranking_reasons(g, profile_data),
        })

    # 4. Sort by Score
    scored.sort(key=lambda g: g["score"], reverse=True)

    # 5. Apply Hard Filters (Price)
    if max_price is not None:
        scored = [g for g in scored if g.get("price", 0) <= max_price]

    # 6. Calculate Confidence
    # We take the scores and map them to a user