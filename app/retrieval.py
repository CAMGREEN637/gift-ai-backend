import os
import logging
import traceback
import re
from typing import List, Dict, Optional, Set
from dotenv import load_dotenv

from app.embeddings import generate_embedding
from app.persistence import get_feedback

load_dotenv()
logger = logging.getLogger(__name__)

# --------------------------------------------------
# Constants & Configuration
# --------------------------------------------------

# Common words to ignore when extracting keywords for boosting
STOPWORDS = {
    "a", "an", "the", "for", "of", "in", "to", "with", "who", "that",
    "gift", "gifts", "idea", "ideas", "likes", "loves", "wants", "need",
    "girlfriend", "boyfriend", "wife", "husband", "friend", "best", "good"
}


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


def extract_keywords(query: str) -> Set[str]:
    """Extract meaningful content words from the query for explicit boosting."""
    if not query:
        return set()
    # Remove punctuation and split
    tokens = re.findall(r'\w+', query.lower())
    # Filter out stopwords
    keywords = {t for t in tokens if t not in STOPWORDS and len(t) > 2}
    return keywords


# --------------------------------------------------
# Scoring Logic (Personalization + Keywords)
# --------------------------------------------------

def compute_profile_score(
        gift: Dict,
        preferences: Dict,
        user_id: Optional[str],
        query_keywords: Set[str]
) -> Dict:
    """
    Compute scoring based on:
    1. Profile Matches (Interests/Vibe)
    2. User Feedback History
    3. Explicit Query Keyword Matches (The fix for "coffee")
    """
    # 1. Profile Matches
    interest_matches = set(gift["interests"]) & set(preferences["interests"])
    vibe_matches = set(gift["vibe"]) & set(preferences["vibe"])

    interest_score = len(interest_matches) * 5.0
    vibe_score = len(vibe_matches) * 3.0

    # 2. Feedback History
    feedback_score = 0
    if user_id:
        history = get_feedback(user_id)
        for entry in history:
            if entry["gift_name"] == gift["name"]:
                feedback_score += 5 if entry["liked"] else -10

    # 3. Keyword Boosting (Fix for retrieval relevance)
    # Check if 'coffee' from query is in the gift name or tags
    keyword_score = 0
    matched_keywords = []

    # Combine searchable text fields
    gift_text_blob = (
            gift.get("name", "") + " " +
            " ".join(gift.get("interests", [])) + " " +
            gift.get("description", "")
    ).lower()

    for kw in query_keywords:
        if kw in gift_text_blob:
            # Heavy boost if keyword is found (pushes 'coffee' items to top)
            keyword_score += 15.0
            matched_keywords.append(kw)

    total_score = interest_score + vibe_score + feedback_score + keyword_score

    return {
        "total": total_score,
        "breakdown": {
            "interest_match": len(interest_matches),
            "vibe_match": len(vibe_matches),
            "feedback": feedback_score,
            "keyword_match": len(matched_keywords),
            "matched_keywords": matched_keywords
        },
    }


def compute_hybrid_confidence(scores: List[float]) -> List[float]:
    """
    Convert raw scores into confidence values.
    """
    if not scores:
        return []

    # ANCHOR_SCORE: What we consider a "Great" match.
    # Now that we have Keyword Boosting (+15), a relevant item (Vector ~75 + Boost 15 = 90)
    # will easily beat the Anchor of 82.
    ANCHOR_SCORE = 82.0

    confidences = []
    max_score = max(scores)

    for s in scores:
        # 1. Absolute Score
        ratio = min(s / ANCHOR_SCORE, 1.2)
        absolute_conf = 0.50 + (0.45 * ratio)

        # 2. Relative Boost
        relative_boost = 0.0
        if s == max_score and len(scores) > 1:
            relative_boost = 0.03

        final_conf = min(0.98, absolute_conf + relative_boost)
        confidences.append(round(final_conf, 2))

    return confidences


def build_ranking_reasons(gift: Dict, score_data: Dict) -> List[str]:
    reasons = []

    # Explicit keyword reasons first
    if score_data["breakdown"]["keyword_match"] > 0:
        kws = ", ".join(score_data["breakdown"]["matched_keywords"][:2])
        reasons.append(f"Matches search term '{kws}'")

    if score_data["breakdown"]["interest_match"] > 0:
        reasons.append("Matches your interests")

    if score_data["breakdown"]["vibe_match"] > 0:
        reasons.append("Fits your preferred vibe")

    if score_data["breakdown"]["feedback"] > 0:
        reasons.append("You liked something similar before")

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
    Retrieve gifts using vector similarity search (Supabase pgvector)
    plus Keyword Boosting for relevance.
    """
    preferences = normalize_preferences(preferences)
    query_keywords = extract_keywords(query)

    try:
        supabase = get_supabase_client()
        logger.info("✓ Supabase client initialized")

        # 1. Generate embedding for the query
        query_embedding = generate_embedding(query)

        if not query_embedding:
            logger.error("Failed to generate query embedding")
            return []

        # 2. Vector Search (RPC Call)
        # FIX: Increased threshold from 0.3 to 0.5 to reduce irrelevant noise
        response = supabase.rpc(
            'match_gifts',
            {
                'query_embedding': query_embedding,
                'match_threshold': 0.5,
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

        # Base Vector Score (0-100)
        vector_score = g.get('similarity', 0) * 100

        # Personalization & Keyword Score
        profile_data = compute_profile_score(g, preferences, user_id, query_keywords)

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
    scores = [g["score"] for g in scored]
    confidences = compute_hybrid_confidence(scores)

    # 7. Attach confidence to each gift
    for gift, conf in zip(scored, confidences):
        gift["confidence"] = conf

    # 8. Return top k results
    top_gifts = scored[:k]

    logger.info("✓ Returning %d top-scored gifts" % len(top_gifts))
    if top_gifts:
        logger.info("Top gift: " + top_gifts[0].get('name', '') + " (score: " + str(top_gifts[0].get('score')) + ")")

    return top_gifts