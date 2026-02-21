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
# Supabase Client
# --------------------------------------------------

def get_supabase_client():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise Exception("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    return create_client(url, key)


# --------------------------------------------------
# Normalization & Helpers
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


def extract_query_tokens(query: str) -> Set[str]:
    """
    Simple, scalable tokenizer. We rely on the logic that common words
    (the, a, for) exist in ALL gifts, so boosting them creates no bias.
    Rare words (coffee, hiking) only exist in specific gifts, creating the boost we want.
    """
    if not query:
        return set()
    # Split by non-alphanumeric characters and lowercase
    tokens = re.split(r'\W+', query.lower())
    # Only keep tokens longer than 2 chars to avoid noise like 'a', 'is'
    return {t for t in tokens if len(t) > 2}


# --------------------------------------------------
# Scoring Logic
# --------------------------------------------------

def compute_enhanced_score(
        gift: Dict,
        preferences: Dict,
        user_id: Optional[str],
        query_tokens: Set[str]
) -> Dict:
    """
    Computes a composite score based on:
    1. Vector Similarity (Base)
    2. Profile Matches (Interests/Vibe)
    3. Keyword Overlap (The "Coffee" Fix)
    """

    # --- 1. Keyword Boosting (Hybrid Search Logic) ---
    # We construct a "searchable blob" from the gift's metadata
    gift_text = (
            gift.get("name", "") + " " +
            gift.get("description", "") + " " +
            " ".join(gift.get("interests", []) or [])
    ).lower()

    matched_tokens = []
    keyword_boost = 0.0

    for token in query_tokens:
        if token in gift_text:
            # We give a significant boost for direct keyword matches.
            # This ensures "Coffee" query > "Coffee Maker" gift even if vector score is weak.
            keyword_boost += 10.0
            matched_tokens.append(token)

    # --- 2. Profile Matches ---
    interest_matches = set(gift["interests"]) & set(preferences["interests"])
    vibe_matches = set(gift["vibe"]) & set(preferences["vibe"])

    interest_score = len(interest_matches) * 5.0
    vibe_score = len(vibe_matches) * 3.0

    # --- 3. Feedback History ---
    feedback_score = 0
    if user_id:
        history = get_feedback(user_id)
        for entry in history:
            if entry["gift_name"] == gift["name"]:
                feedback_score += 5 if entry["liked"] else -10

    total_boost = interest_score + vibe_score + feedback_score + keyword_boost

    return {
        "total_boost": total_boost,
        "breakdown": {
            "interest_match": len(interest_matches),
            "vibe_match": len(vibe_matches),
            "feedback": feedback_score,
            "keyword_match": len(matched_tokens),
            "matched_keywords": matched_tokens
        },
    }


def compute_confidence(final_score: float, vector_similarity: float) -> float:
    """
    Dynamically calculates confidence.
    A score > 85 is generally 'High Confidence'.
    """
    # 1. Base confidence is the raw vector similarity (e.g. 0.82)
    base_conf = vector_similarity

    # 2. Add confidence based on the boost score (capped at +0.15)
    # If we have keyword matches or profile matches, we are MORE confident.
    boost_conf = min((final_score - (vector_similarity * 100)) / 100.0, 0.15)

    # 3. Sum and cap at 0.99
    return round(min(base_conf + boost_conf, 0.99), 2)


def build_ranking_reasons(gift: Dict, breakdown: Dict) -> List[str]:
    """
    Build ranking reasons for LLM to use.
    This function is required by your LLM.
    """
    reasons = []

    if breakdown.get("keyword_match", 0) > 0:
        keywords = breakdown.get("matched_keywords", [])
        if keywords:
            kws = ", ".join(keywords[:2])
            reasons.append("Contains '" + kws + "'")

    if breakdown.get("interest_match", 0) > 0:
        reasons.append("Matches your interests")

    if breakdown.get("vibe_match", 0) > 0:
        reasons.append("Fits your preferred vibe")

    if breakdown.get("feedback", 0) > 0:
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
    Retrieve gifts using vector similarity + keyword boosting.
    CRITICAL: Always returns a list (never None).
    """
    preferences = normalize_preferences(preferences)
    query_tokens = extract_query_tokens(query)

    try:
        supabase = get_supabase_client()
        query_embedding = generate_embedding(query)

        if not query_embedding:
            logger.error("Failed to generate embedding")
            return []

        # --- STEP 1: Broad Retrieval (Fix for "No Gifts Found") ---
        # We lower the threshold significantly (0.15) to ensure we get candidates.
        # We increase match_count (50) to cast a wider net.
        response = supabase.rpc(
            'match_gifts',
            {
                'query_embedding': query_embedding,
                'match_threshold': 0.15,
                'match_count': 50
            }
        ).execute()

        raw_gifts = response.data or []
        logger.info("✓ Retrieved %d candidates from DB" % len(raw_gifts))

    except Exception as e:
        logger.error("Error in vector search: " + str(e))
        logger.error(traceback.format_exc())
        return []

    # --- STEP 2: Processing & Filtering ---
    scored_candidates = []

    for g in raw_gifts:
        # Normalize fields
        g["interests"] = normalize_list_field(g.get("interests", []))
        g["vibe"] = normalize_list_field(g.get("vibe", []))
        g["categories"] = normalize_list_field(g.get("categories", []))
        g["occasions"] = normalize_list_field(g.get("occasions", []))

        # Base Vector Score (0-100 scale)
        # Note: 'similarity' comes from Supabase (0.0 to 1.0)
        vec_sim = g.get('similarity', 0)
        vector_score = vec_sim * 100

        # Calculate Boosts
        score_data = compute_enhanced_score(g, preferences, user_id, query_tokens)

        # Final Score
        final_score = vector_score + score_data["total_boost"]

        # --- STEP 3: The "Unrelated" Filter (Noise Reduction) ---
        # If a gift has low vector similarity (< 0.78) AND ZERO keyword matches,
        # it is likely random noise (e.g., generic "gift" matches). We skip it.
        # Exception: If it has a strong profile match (interest > 0), we keep it.

        is_weak_vector = vec_sim < 0.78
        has_keywords = score_data["breakdown"]["keyword_match"] > 0
        has_profile_match = score_data["breakdown"]["interest_match"] > 0

        if is_weak_vector and not has_keywords and not has_profile_match:
            continue  # Skip this unrelated item

        # Attach metadata
        scored_candidates.append({
            **g,
            "score": final_score,
            "vector_similarity": vec_sim,
            "breakdown": score_data["breakdown"]
        })

    # --- STEP 4: Sorting & Confidence ---
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)

    # Apply Price Filter
    if max_price is not None:
        scored_candidates = [g for g in scored_candidates if g.get("price", 0) <= max_price]

    # Calculate final confidence and build ranking reasons
    final_results = []
    for g in scored_candidates[:k]:  # Take top K
        g["confidence"] = compute_confidence(g["score"], g["vector_similarity"])

        # Build ranking reasons for LLM (REQUIRED)
        g["ranking_reasons"] = build_ranking_reasons(g, g["breakdown"])

        final_results.append(g)

    logger.info("✓ Returning %d top-scored gifts" % len(final_results))
    if final_results:
        logger.info(
            "Top gift: " + final_results[0].get('name', '') + " (score: " + str(final_results[0].get('score')) + ")")

    return final_results