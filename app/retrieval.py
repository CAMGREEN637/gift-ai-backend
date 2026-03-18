# app/retrieval.py

import os
import logging
import traceback
import re
import json
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

# Rebalanced weights for better discovery
VECTOR_WEIGHT = 60
INTENT_WEIGHT = 25
SESSION_WEIGHT = 5
PROFILE_WEIGHT = 3
PRICE_WEIGHT = 20

DIVERSITY_PENALTY = 15
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


def normalize_jsonb_to_list(value):
    """Safely converts Supabase JSONB or string fields into Python lists."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip().lower() for v in value if v]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip().lower() for v in parsed if v]
        except:
            return [v.strip().lower() for v in value.split(",") if v.strip()]
    return []


def normalize_preferences(preferences: Optional[Dict]) -> Dict:
    if not preferences:
        return {"interests": []}
    return {
        "interests": [i.lower() for i in preferences.get("interests", [])]
    }


# --------------------------------------------------
# PRICE SCORING (SOFT BIAS)
# --------------------------------------------------

def compute_price_score(price: float, max_price: Optional[int]) -> float:
    if not max_price or not price:
        return 0

    ratio = price / max_price

    # Boost if near top of range (best value/quality match)
    if 0.7 <= ratio <= 1.0:
        return PRICE_WEIGHT * ratio

    # Mid-range boost
    if 0.4 <= ratio < 0.7:
        return PRICE_WEIGHT * (ratio * 0.6)

    # Small boost for budget-friendly items
    if ratio < 0.4:
        return PRICE_WEIGHT * 0.1

    # Slight penalty if over max (soft filtering)
    if ratio > 1.0:
        return -5

    return 0


# --------------------------------------------------
# SCORING
# --------------------------------------------------

def compute_enhanced_score(
        gift: Dict,
        meaningful_intent_tokens: Set[str],
        preferences: Dict,
        feedback_history: List[Dict],
        partner_profile: Optional[Dict],
        partner_gift_history: List[str]
):
    # Safety: Coerce None values to empty strings/lists to prevent concatenation errors
    gift_text = (
            str(gift.get("name") or "") + " " +
            str(gift.get("description") or "") + " " +
            " ".join(gift.get("interests") or []) + " " +
            " ".join(gift.get("categories") or [])
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

    history_penalty = -40 if gift.get("id") in partner_gift_history else 0

    feedback_score = 0
    for entry in feedback_history:
        if entry.get("gift_name") == gift.get("name"):
            feedback_score += 10 if entry.get("liked") else -15

    total_boost = intent_score + session_score + profile_score + history_penalty + feedback_score

    return {
        "total_boost": total_boost,
        "intent_match_count": len(matched_intent),
        "matched_intent": matched_intent,
        "already_purchased": gift.get("id") in partner_gift_history
    }


def compute_confidence(vector_similarity: float, intent_match_count: int, price_score: float):
    base = vector_similarity
    base += min(intent_match_count * 0.05, 0.15)
    base += min(price_score / 100, 0.08)

    # Clamp to realistic range for UI display
    base = max(0.6, min(base, 0.96))
    return round(base, 2)


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
    Main entry point for fetching and ranking gift recommendations.
    """
    preferences = normalize_preferences(preferences)
    meaningful_intent_tokens = extract_meaningful_intent_tokens(query)
    partner_gift_history = partner_gift_history or []

    # Optimize: Fetch feedback history once to avoid N+1 queries in the loop
    user_feedback = []
    if user_id:
        try:
            user_feedback = get_feedback(user_id)
        except Exception as e:
            logger.error(f"Failed to fetch user feedback: {e}")

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
                "match_count": 80  # Fetch more than k to allow for diversity/price filtering
            }
        ).execute()

        raw_gifts = response.data or []
        logger.info(f"Retrieved {len(raw_gifts)} candidates from vector search")

    except Exception as e:
        logger.error(f"Vector search error: {e}")
        logger.error(traceback.format_exc())
        return []

    scored = []

    for g in raw_gifts:
        # Field Normalization
        if not g.get("display_name"):
            g["display_name"] = g.get("name", "Unknown Gift")

        for field in ["interests", "categories", "vibe", "occasions", "personality_traits"]:
            g[field] = normalize_jsonb_to_list(g.get(field))

        g["product_url"] = g.get("link")

        # Scoring Logic
        vec_sim = g.get("similarity", 0)
        vector_score = vec_sim * VECTOR_WEIGHT

        score_data = compute_enhanced_score(
            g, meaningful_intent_tokens, preferences,
            user_feedback, partner_profile, partner_gift_history
        )

        price_score = compute_price_score(g.get("price", 0), max_price)
        novelty_score = NOVELTY_BOOST if g.get("id") not in partner_gift_history else 0

        # Delivery logic
        on_time_bonus = 0
        delivery_status = "unknown"
        if days_until_needed is not None:
            shipping_max = g.get("shipping_max_days", 8)
            if shipping_max <= days_until_needed:
                on_time_bonus = 40
                delivery_status = "on_time"
            elif shipping_max <= days_until_needed + 3:
                on_time_bonus = 15
                delivery_status = "tight"
            else:
                delivery_status = "late"

        final_score = (
                vector_score +
                score_data["total_boost"] +
                novelty_score +
                on_time_bonus +
                price_score
        )

        confidence = compute_confidence(
            vec_sim,
            score_data["intent_match_count"],
            price_score
        )

        # Build ranking reasons for the frontend UI
        reasons = []
        if score_data["matched_intent"]:
            reasons.append("Matches: " + ", ".join(score_data["matched_intent"][:2]))
        if set(g["interests"]) & set(preferences.get("interests", [])):
            reasons.append("Fits interests")
        if delivery_status == "on_time":
            reasons.append("Arrives on time")
        if price_score > 10:
            reasons.append("Great value in budget")

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

    # --------------------------------------------------
    # DIVERSITY PASS
    # --------------------------------------------------
    scored.sort(key=lambda x: x["score"], reverse=True)

    category_counter = defaultdict(int)
    for gift in scored:
        for cat in gift.get("categories", []):
            if category_counter[cat] >= MAX_CATEGORY_DOMINANCE:
                gift["score"] -= DIVERSITY_PENALTY
                break
            category_counter[cat] += 1

    # --------------------------------------------------
    # FINAL FILTER & SORT
    # --------------------------------------------------
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Soft price filter: Prioritize in-range, but keep strong outliers to reach 'k'
    if max_price is not None:
        in_range = [g for g in scored if g.get("price", 0) <= max_price]
        out_of_range = [g for g in scored if g.get("price", 0) > max_price]
        scored = in_range + out_of_range

    final_results = scored[:k]

    # Slight visual confidence boost for top 3 matches
    for i, gift in enumerate(final_results[:3]):
        gift["confidence"] = min(gift["confidence"] + 0.02, 0.96)

    logger.info(f"Returning {len(final_results)} gifts.")
    return final_results