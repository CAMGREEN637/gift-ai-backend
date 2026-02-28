# app/retrieval.py

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


def normalize_list(value):
    if isinstance(value, list):
        return [v.strip().lower() for v in value]
    if isinstance(value, str):
        return [v.strip().lower() for v in value.split(",") if v.strip()]
    return []


def normalize_preferences(preferences: Optional[Dict]) -> Dict:
    if not preferences:
        return {"interests": []}
    return {
        "interests": [i.lower() for i in preferences.get("interests", [])]
    }


def compute_enhanced_score(
        gift: Dict,
        intent_tokens: Set[str],
        preferences: Dict,
        user_id: Optional[str],
        partner_profile: Optional[Dict],
        partner_gift_history: List[str]
):
    """
    Compute score with clean separation:
    - intent_tokens: PRIMARY signal (from query)
    - preferences: SESSION preferences boost
    - partner_profile: PERSISTENT soft boost (much smaller weight)
    - partner_gift_history: Penalty for already purchased
    """

    gift_text = (
            gift.get("name", "") + " " +
            gift.get("description", "") + " " +
            " ".join(gift.get("interests", [])) + " " +
            " ".join(gift.get("categories", []))
    ).lower()

    # 1. Intent Match (PRIMARY)
    matched_intent = [t for t in intent_tokens if t in gift_text]
    intent_match_count = len(matched_intent)

    if intent_tokens and intent_match_count == 0:
        return None  # Hard filter for relevance

    intent_bonus = intent_match_count * 15

    # 2. Session Preferences (MEDIUM weight)
    interest_matches = set(gift.get("interests", [])) & set(preferences.get("interests", []))
    session_score = len(interest_matches) * 5

    # 3. Partner Profile (SOFT boost - avoid staleness)
    profile_boost = 0
    if partner_profile:
        profile_interests = set(partner_profile.get("interests", []))
        profile_vibe = set(partner_profile.get("vibe", []))

        gift_interests = set(gift.get("interests", []))
        gift_vibe = set(gift.get("vibe", []))

        interest_matches_profile = len(gift_interests & profile_interests)
        vibe_matches = len(gift_vibe & profile_vibe)

        # Much smaller weights than session
        profile_boost = (interest_matches_profile * 3.0) + (vibe_matches * 2.0)

    # 4. Gift History Penalty
    history_penalty = 0
    gift_id = gift.get("id")
    if gift_id and gift_id in partner_gift_history:
        history_penalty = -50.0

    # 5. Feedback
    feedback_score = 0
    if user_id:
        history = get_feedback(user_id)
        for entry in history:
            if entry["gift_name"] == gift["name"]:
                feedback_score += 5 if entry["liked"] else -10

    total_boost = intent_bonus + session_score + profile_boost + history_penalty + feedback_score

    return {
        "total_boost": total_boost,
        "intent_match_count": intent_match_count,
        "matched_intent": matched_intent,
        "profile_boost": profile_boost,
        "already_purchased": gift_id in partner_gift_history
    }


def compute_confidence(vector_similarity: float, intent_match_count: int):
    """Compute confidence based on vector similarity and intent matches"""
    if intent_match_count > 0:
        if vector_similarity >= 0.75:
            return 0.92
        if vector_similarity >= 0.65:
            return 0.87
        return 0.85
    else:
        return min(vector_similarity, 0.84)


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
    Retrieve gifts with CLEAN separation of concerns:
    - query: PRIMARY intent signal
    - preferences: SESSION-specific boosts
    - partner_profile: PERSISTENT soft boost (separate!)
    - partner_gift_history: Gift IDs to penalize
    """

    preferences = normalize_preferences(preferences)
    intent_tokens = tokenize(query)
    partner_gift_history = partner_gift_history or []

    try:
        supabase = get_supabase_client()

        # Vector search uses QUERY ONLY
        embedding = generate_embedding(query)
        if not embedding:
            logger.error("Failed to generate embedding")
            return []

        match_count = 50 if days_until_needed else 30

        response = supabase.rpc(
            "match_gifts",
            {
                "query_embedding": embedding,
                "match_threshold": 0.15,
                "match_count": match_count
            }
        ).execute()

        raw_gifts = response.data or []
        logger.info("✓ Retrieved %d candidates from DB" % len(raw_gifts))

    except Exception as e:
        logger.error("Vector search error: %s" % str(e))
        logger.error(traceback.format_exc())
        return []

    scored = []

    for g in raw_gifts:
        g["interests"] = normalize_list(g.get("interests"))
        g["categories"] = normalize_list(g.get("categories"))
        g["vibe"] = normalize_list(g.get("vibe", []))

        vec_sim = g.get("similarity", 0)
        vector_score = vec_sim * 100

        # Score with clean separation
        score_data = compute_enhanced_score(
            g,
            intent_tokens,
            preferences,
            user_id,
            partner_profile,
            partner_gift_history
        )

        if not score_data:
            continue

        # Soft delivery boost
        shipping_max = g.get("shipping_max_days", 8)
        on_time_bonus = 0
        delivery_status = "unknown"

        if days_until_needed is not None:
            if shipping_max <= days_until_needed:
                on_time_bonus = 50.0
                delivery_status = "on_time"
            elif shipping_max <= days_until_needed + 3:
                on_time_bonus = 20.0
                delivery_status = "tight"
            else:
                delivery_status = "late"

        final_score = vector_score + score_data["total_boost"] + on_time_bonus

        confidence = compute_confidence(vec_sim, score_data["intent_match_count"])

        # Build reasons
        reasons = []
        if score_data["matched_intent"]:
            reasons.append("Directly matches: " + ", ".join(score_data["matched_intent"][:2]))
        if score_data.get("profile_boost", 0) > 5:
            reasons.append("Fits their style")
        if delivery_status == "on_time":
            reasons.append("Arrives on time")
        if not reasons:
            reasons.append("Strong match")

        g.update({
            "score": final_score,
            "confidence": confidence,
            "ranking_reasons": reasons,
            "delivery_status": delivery_status,
            "already_purchased": score_data.get("already_purchased", False)
        })

        scored.append(g)

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Hard price filter
    if max_price is not None:
        scored = [g for g in scored if g.get("price", 0) <= max_price]

    logger.info("Returning %d gifts (partner: %s, delivery: %s)" % (
        len(scored[:k]),
        "yes" if partner_profile else "no",
        "enabled" if days_until_needed else "disabled"
    ))

    return scored[:k]