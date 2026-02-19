# app/retrieval.py - FIXED VERSION

from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Optional
import logging
import traceback

from app.persistence import get_feedback

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)


# --------------------------------------------------
# FIX: Get Supabase client correctly
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
# Scoring Logic - FIXED
# --------------------------------------------------

def compute_score(
        gift: Dict,
        preferences: Dict,
        user_id: Optional[str]
) -> Dict:
    """
    Compute preference-based scoring (interests/vibe from user profile).
    Reduced weight so query relevance takes priority.
    """
    interest_matches = set(gift["interests"]) & set(preferences["interests"])
    vibe_matches = set(gift["vibe"]) & set(preferences["vibe"])

    # Lower weight for preferences so they don't override query match
    interest_score = len(interest_matches) * 2.0  # Reduced from 3
    vibe_score = len(vibe_matches) * 1.0  # Reduced from 2

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


def semantic_score_from_query_match(gift: Dict, query: str) -> float:
    """
    Score based on keyword matching with query.
    Start at 0 to ensure only relevant gifts score high.
    """
    score = 0.0  # Start at 0 instead of 5.0
    query_lower = query.lower()
    query_words = query_lower.split()

    # Extract searchable text from gift
    name = gift.get("name", "").lower()
    description = gift.get("description", "").lower()
    categories = [str(c).lower() for c in gift.get("categories", [])]
    interests = [str(i).lower() for i in gift.get("interests", [])]
    occasions = [str(o).lower() for o in gift.get("occasions", [])]

    # Track if ANY word matches (to avoid scoring irrelevant items)
    has_any_match = False

    # Check each query word
    for word in query_words:
        if len(word) < 3:  # Skip very short words like "a", "is", "of"
            continue

        # Name match (highest weight)
        if word in name:
            score += 15.0
            has_any_match = True

        # Description match (medium weight)
        if word in description:
            score += 8.0
            has_any_match = True

        # Interest match (HIGHEST weight - this is key!)
        for interest in interests:
            if word in interest or interest in word:
                score += 20.0  # Interests are very important
                has_any_match = True

        # Category match (high weight)
        for category in categories:
            if word in category or category in word:
                score += 12.0
                has_any_match = True

        # Occasion match (medium weight)
        for occasion in occasions:
            if word in occasion or occasion in word:
                score += 5.0
                has_any_match = True

    # If NO words matched at all, return very low score
    if not has_any_match:
        return 0.0

    # Boost if multiple query words match
    matched_words = sum(1 for word in query_words if len(word) >= 3 and (
            word in name or
            word in description or
            any(word in interest for interest in interests)
    ))

    if matched_words > 1:
        score += matched_words * 3.0  # Bonus for multiple matches

    logger.debug(f"Gift: {gift.get('name')[:40]} | Query score: {score:.1f}")

    return score


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
    """
    Retrieve gifts from Supabase database and score them.
    """

    preferences = normalize_preferences(preferences)

    try:
        # 1. Get Supabase client
        supabase = get_supabase_client()
        logger.info("✓ Supabase client initialized")

        # 2. Query gifts from Supabase
        db_query = supabase.table('gifts').select('*')

        # Apply price filter at database level if specified
        if max_price is not None:
            db_query = db_query.lte('price', max_price)

        # Only get in-stock items
        db_query = db_query.eq('in_stock', True)

        # Get more results for better filtering (50 max)
        db_query = db_query.order('created_at', desc=True).limit(50)

        # Execute query
        response = db_query.execute()

        if not response.data:
            logger.warning("No gifts found in Supabase database")
            return []

        gifts = response.data
        logger.info(f"✓ Retrieved {len(gifts)} gifts from Supabase")

    except Exception as e:
        logger.error(f"Error retrieving gifts from Supabase: {str(e)}")
        logger.error(traceback.format_exc())
        return []

    # 3. Normalize gift metadata
    for g in gifts:
        g["interests"] = normalize_list_field(g.get("interests", []))
        g["vibe"] = normalize_list_field(g.get("vibe", []))
        g["categories"] = normalize_list_field(g.get("categories", []))
        g["occasions"] = normalize_list_field(g.get("occasions", []))

    # 4. Score gifts (semantic + heuristic)
    scored = []
    for gift in gifts:
        # Compute heuristic score (interests, vibe, feedback)
        score_data = compute_score(gift, preferences, user_id)

        # Compute semantic score based on query matching
        semantic_score = semantic_score_from_query_match(gift, query)

        # Combine scores
        total_score = score_data["total"] + semantic_score

        scored.append({
            **gift,
            "score": total_score,
            "ranking_reasons": build_ranking_reasons(gift, score_data),
        })

        logger.debug(f"Gift: {gift.get('name', '')[:30]}... Score: {total_score}")

    # 5. Sort by score (highest first)
    scored.sort(key=lambda g: g["score"], reverse=True)

    # ⭐ NEW: Filter out gifts with zero or negative scores
    scored = [g for g in scored if g["score"] > 0]

    logger.info(f"✓ After filtering: {len(scored)} relevant gifts remain")

    # 6. If we have fewer than k relevant gifts, that's OK - return what we have
    if len(scored) < k:
        logger.info(f"Only {len(scored)} relevant gifts found (requested {k})")

    # 7. Compute relative confidence
    scores = [g["score"] for g in scored]
    confidences = compute_relative_confidences(scores)

    # 8. Attach confidence to each gift
    for gift, conf in zip(scored, confidences):
        gift["confidence"] = conf

    # 9. Return top k results (or fewer if not enough relevant gifts)
    top_gifts = scored[:k]

    logger.info(f"✓ Returning {len(top_gifts)} top-scored gifts")
    if top_gifts:
        logger.info(f"Top gift: {top_gifts[0].get('name', '')} (score: {top_gifts[0].get('score')})")

    return top_gifts