# app/retrieval.py

import os
import logging
import traceback
import re
from typing import List, Dict, Optional, Set
from collections import defaultdict
from dotenv import load_dotenv

from app.embeddings import generate_embedding
from app.persistence import get_feedback

load_dotenv()
logger = logging.getLogger(__name__)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

GENERIC_TOKENS = {
    "gift", "present", "birthday", "anniversary", "christmas", "valentines",
    "girlfriend", "boyfriend", "wife", "husband", "partner", "spouse",
    "friend", "family", "mom", "dad", "sister", "brother",
    "for", "her", "him", "them", "woman", "man", "person",
    "who", "loves", "likes", "enjoys", "into",
    "named", "called"
}

VECTOR_MATCH_THRESHOLD = 0.15
VECTOR_WEIGHT = 100
INTENT_WEIGHT = 15
SESSION_WEIGHT = 5
PROFILE_WEIGHT = 3

DIVERSITY_PENALTY = 20
NOVELTY_BOOST = 10
MAX_CATEGORY_DOMINANCE = 3


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def get_supabase_client():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise Exception("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


def tokenize(text: str) -> Set[str]:
    tokens = re.split(r"\W+", text.lower())
    return {t for t in tokens if len(t) > 2}


def extract_meaningful_intent_tokens(query: str) -> Set[str]:
    all_tokens = tokenize(query)
    words = query.split()
    capitalized_words = {word.lower() for word in words if word and word[0].isupper()}
    meaningful = all_tokens - GENERIC_TOKENS - capitalized_words
    logger.info("Query: '%s' -> Meaningful tokens: %s" % (query, meaningful))
    return meaningful


def normalize_list(value):
    if isinstance(value, list):
        return [v.strip().lower() for v in value if v]
    if isinstance(value, str):
        return [v.strip().lower() for v in value.split(",") if v.strip()]
    return []


def normalize_preferences(preferences: Optional[Dict]) -> Dict:
    if not preferences:
        return {"interests": []}
    return {
        "interests": [i.lower() for i in preferences.get("interests", [])]
    }


# --------------------------------------------------
# SCORING
# --------------------------------------------------

def compute_enhanced_score(
        gift: Dict,
        meaningful_intent_tokens: Set[str],
        preferences: Dict,
        user_id: Optional[str],
        partner_profile: Optional[Dict],
        partner_gift_history: List[str]
):
    gift_text = (
            gift.get("name", "") + " " +
            gift.get("description", "") + " " +
            " ".join(gift.get("interests", [])) + " " +
            " ".join(gift.get("categories", []))
    ).lower()

    matched_intent = [t for t in meaningful_intent_tokens if t in gift_text]
    intent_score = len(matched_intent) * INTENT_WEIGHT

    interest_matches = set(gift.get("interests", [])) & set(preferences.get("interests", []))
    session_score = len(interest_matches) * SESSION_WEIGHT

    profile_score = 0
    if partner_profile:
        profile_interests = set(partner_profile.get("interests", []))
        profile_vibe = set(partner_profile.get("vibe", []))
        gift_interests = set(gift.get("interests", []))
        gift_vibe = set(gift.get("vibe", []))

        profile_score = (
                len(gift_interests & profile_interests) * PROFILE_WEIGHT +
                len(gift_vibe & profile_vibe) * (PROFILE_WEIGHT * 0.7)
        )

    history_penalty = -50 if gift.get("id") in partner_gift_history else 0

    feedback_score = 0
    if user_id:
        history = get_feedback(user_id)
        for entry in history:
            if entry["gift_name"] == gift["name"]:
                feedback_score += 10 if entry["liked"] else -20

    total_boost = intent_score + session_score + profile_score + history_penalty + feedback_score

    return {
        "total_boost": total_boost,
        "intent_match_count": len(matched_intent),
        "matched_intent": matched_intent,
        "already_purchased": gift.get("id") in partner_gift_history
    }


def compute_confidence(vector_similarity: float, intent_match_count: int):
    if intent_match_count >= 1 and vector_similarity >= 0.75:
        return 0.92
    if intent_match_count >= 1 and vector_similarity >= 0.65:
        return 0.87
    if intent_match_count >= 1:
        return 0.85
    return min(vector_similarity, 0.84)


# --------------------------------------------------
# MAIN RETRIEVAL
# --------------------------------------------------

def retrieve_gifts(
        query: str,
        user_id: Optional[str] = None,
        k: int = 10,
        max_price: Optional[int] = None,
        days_until_needed: Optional[int] = None,
        preferences: Optional[Dict] = None,
        partner_profile: Optional[Dict] = None,
        partner_gift_history: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Retrieve gifts with SOFT filtering and display_name support.
    """

    preferences = normalize_preferences(preferences)
    meaningful_intent_tokens = extract_meaningful_intent_tokens(query)
    partner_gift_history = partner_gift_history or []

    try:
        supabase = get_supabase_client()
        embedding = generate_embedding(query)
        if not embedding:
            logger.error("Embedding generation failed")
            return []

        response = supabase.rpc(
            "match_gifts",
            {
                "query_embedding": embedding,
                "match_threshold": VECTOR_MATCH_THRESHOLD,
                "match_count": 50
            }
        ).execute()

        raw_gifts = response.data or []
        logger.info("Retrieved %d candidates from vector search" % len(raw_gifts))

        # ✅ DEBUG: Log if display_name is coming from database
        if raw_gifts:
            sample = raw_gifts[0]
            logger.info("Sample gift fields: %s" % list(sample.keys()))
            logger.info("Sample display_name: '%s'" % sample.get('display_name', 'NOT FOUND'))

    except Exception as e:
        logger.error("Vector search error: %s" % str(e))
        logger.error(traceback.format_exc())
        return []

    scored = []

    for g in raw_gifts:
        # ✅ FIX: Ensure display_name is set properly
        # If database returns display_name, use it; otherwise fall back to name
        if 'display_name' not in g or not g['display_name']:
            g['display_name'] = g.get('name', 'Unknown Gift')

        # ✅ DEBUG: Log what we're using
        logger.debug("Gift: %s | Display: %s" % (g.get('name', '')[:50], g.get('display_name', '')[:50]))

        # Normalize fields
        g["interests"] = normalize_list(g.get("interests"))
        g["categories"] = normalize_list(g.get("categories"))
        g["vibe"] = normalize_list(g.get("vibe", []))

        vec_sim = g.get("similarity", 0)
        vector_score = vec_sim * VECTOR_WEIGHT

        score_data = compute_enhanced_score(
            g, meaningful_intent_tokens, preferences,
            user_id, partner_profile, partner_gift_history
        )

        novelty_score = NOVELTY_BOOST if g.get("id") not in partner_gift_history else 0

        on_time_bonus = 0
        delivery_status = "unknown"
        if days_until_needed is not None:
            shipping_max = g.get("shipping_max_days", 8)
            if shipping_max <= days_until_needed:
                on_time_bonus = 50
                delivery_status = "on_time"
            elif shipping_max <= days_until_needed + 3:
                on_time_bonus = 20
                delivery_status = "tight"
            else:
                delivery_status = "late"

        final_score = vector_score + score_data["total_boost"] + novelty_score + on_time_bonus
        confidence = compute_confidence(vec_sim, score_data["intent_match_count"])

        reasons = []
        if score_data["matched_intent"]:
            reasons.append("Matches: " + ", ".join(score_data["matched_intent"][:2]))
        if len(set(g["interests"]) & set(preferences.get("interests", []))) > 0:
            reasons.append("Fits interests")
        if delivery_status == "on_time":
            reasons.append("Arrives on time")
        if not reasons:
            reasons.append("Good match")

        g.update({
            "score": final_score,
            "confidence": confidence,
            "ranking_reasons": reasons,
            "delivery_status": delivery_status,
            "already_purchased": score_data.get("already_purchased", False)
        })
        scored.append(g)

    # Diversity Pass
    scored.sort(key=lambda x: x["score"], reverse=True)
    category_counter = defaultdict(int)
    for gift in scored:
        categories = gift.get("categories", [])
        for cat in categories:
            if category_counter[cat] >= MAX_CATEGORY_DOMINANCE:
                gift["score"] -= DIVERSITY_PENALTY
                break
            category_counter[cat] += 1

    # Final Sort and Filter
    scored.sort(key=lambda x: x["score"], reverse=True)
    final_results = scored[:k]

    if max_price is not None:
        final_results = [g for g in final_results if g.get("price", 0) <= max_price]

    # ✅ FINAL CHECK: Log what we're returning
    logger.info("Returning %d gifts. First gift display_name: '%s'" % (
        len(final_results),
        final_results[0].get('display_name', 'NOT SET') if final_results else 'NO RESULTS'
    ))

    return final_results