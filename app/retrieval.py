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
    if not text:
        return set()
    tokens = re.split(r"\W+", text.lower())
    return {t for t in tokens if len(t) > 2}


def extract_meaningful_intent_tokens(query: str) -> Set[str]:
    all_tokens = tokenize(query)
    words = query.split()
    # Identifying potential names or specific brands
    capitalized_words = {word.lower() for word in words if word and word[0].isupper()}
    meaningful = all_tokens - GENERIC_TOKENS - capitalized_words
    logger.info(f"Query: '{query}' -> Meaningful tokens: {meaningful}")
    return meaningful


def normalize_jsonb_to_list(value) -> List[str]:
    """Convert JSONB field to Python list of strings safely"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip().lower() for v in value if v]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip().lower() for v in parsed if v]
        except (json.JSONDecodeError, TypeError):
            return [v.strip().lower() for v in value.split(",") if v.strip()]
    return []


def normalize_preferences(preferences: Optional[Dict]) -> Dict:
    if not preferences:
        return {"interests": []}
    interests = preferences.get("interests", [])
    if isinstance(interests, str):
        interests = [i.strip() for i in interests.split(",")]
    return {
        "interests": [str(i).lower() for i in interests if i]
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
    # Ensure we are using the normalized lists created in the main loop
    g_interests = gift.get("interests") or []
    g_categories = gift.get("categories") or []
    g_vibes = gift.get("vibe") or []

    gift_text = (
            str(gift.get("name") or "") + " " +
            str(gift.get("description") or "") + " " +
            " ".join(g_interests) + " " +
            " ".join(g_categories)
    ).lower()

    matched_intent = [t for t in meaningful_intent_tokens if t in gift_text]
    intent_score = len(matched_intent) * INTENT_WEIGHT

    interest_matches = set(g_interests) & set(preferences.get("interests", []))
    session_score = len(interest_matches) * SESSION_WEIGHT

    profile_score = 0
    if partner_profile:
        p_interests = set(normalize_jsonb_to_list(partner_profile.get("interests")))
        p_vibe = set(normalize_jsonb_to_list(partner_profile.get("vibe")))

        profile_score = (
                len(set(g_interests) & p_interests) * PROFILE_WEIGHT +
                len(set(g_vibes) & p_vibe) * (PROFILE_WEIGHT * 0.7)
        )

    # Use IDs for history check to be precise
    history_penalty = -50 if str(gift.get("id")) in [str(id) for id in partner_gift_history] else 0

    feedback_score = 0
    if user_id:
        try:
            history = get_feedback(user_id)
            for entry in history:
                # Compare names or IDs if available
                if entry.get("gift_name") == gift.get("name"):
                    feedback_score += 15 if entry.get("liked") else -25
        except Exception as e:
            logger.warning(f"Could not fetch feedback for scoring: {e}")

    total_boost = intent_score + session_score + profile_score + history_penalty + feedback_score

    return {
        "total_boost": total_boost,
        "intent_match_count": len(matched_intent),
        "interest_match_count": len(interest_matches),
        "matched_intent": matched_intent,
        "already_purchased": history_penalty < 0
    }


def compute_confidence(vector_similarity: float, intent_match_count: int, interest_match_count: int):
    """
    Creates a dynamic, spread-out confidence score rather than clustering at 85%.
    """
    # Base confidence mapped from vector similarity.
    # Assumes vector similarities are usually between 0.10 and 0.60.
    base_conf = 0.72 + (max(0, vector_similarity) * 0.35)

    # Add fluid boosts for explicit keyword/interest matches
    base_conf += (intent_match_count * 0.04)
    base_conf += (interest_match_count * 0.02)

    # Cap logically at 98% to leave room for a "perfect" 100% manually if ever needed
    return min(round(base_conf, 2), 0.98)


# --------------------------------------------------
# MAIN RETRIEVAL
# --------------------------------------------------

def retrieve_gifts(
        query: str,
        user_id: Optional[str] = None,
        k: int = 10,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        days_until_needed: Optional[int] = None,
        preferences: Optional[Dict] = None,
        partner_profile: Optional[Dict] = None,
        partner_gift_history: Optional[List[str]] = None,
) -> List[Dict]:
    preferences = normalize_preferences(preferences)
    meaningful_intent_tokens = extract_meaningful_intent_tokens(query)
    partner_gift_history = partner_gift_history or []

    try:
        supabase = get_supabase_client()
        embedding = generate_embedding(query)
        if not embedding or len(embedding) == 0:
            logger.error("Embedding generation returned empty result.")
            return []

        response = supabase.rpc(
            "match_gifts",
            {
                "query_embedding": embedding,
                "match_threshold": VECTOR_MATCH_THRESHOLD,
                "match_count": 80  # High pool size for better diversity filtering
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
        # 1. Clean Data First
        g["interests"] = normalize_jsonb_to_list(g.get("interests"))
        g["categories"] = normalize_jsonb_to_list(g.get("categories"))
        g["vibe"] = normalize_jsonb_to_list(g.get("vibe"))
        g["occasions"] = normalize_jsonb_to_list(g.get("occasions"))

        if not g.get('display_name'):
            g['display_name'] = g.get('name', 'Unique Gift')

        g["product_url"] = g.get("link") or g.get("product_url")

        # 2. Hard Filter: Max Price
        current_price = 0
        try:
            if g.get("price") is not None:
                current_price = float(g["price"])
            if max_price is not None and current_price > max_price:
                continue
        except (ValueError, TypeError):
            pass  # Keep if price is missing or malformed

        # 3. Calculate Base Scores
        vec_sim = g.get("similarity", 0)
        vector_score = vec_sim * VECTOR_WEIGHT

        score_data = compute_enhanced_score(
            g, meaningful_intent_tokens, preferences,
            user_id, partner_profile, partner_gift_history
        )

        novelty_score = NOVELTY_BOOST if str(g.get("id")) not in [str(id) for id in partner_gift_history] else 0

        # 4. The "Sweet Spot" Price Edge
        price_boost = 0
        if current_price > 0 and max_price is not None:
            if min_price is not None and current_price >= min_price:
                # It's inside the user's specific range (e.g., 100-200) -> Flat boost
                price_boost += 15

                # Proportional boost based on how close it is to the max_price
                range_span = max_price - min_price
                if range_span > 0:
                    position_in_range = (current_price - min_price) / range_span
                    price_boost += (position_in_range * 15)  # Up to 15 extra points

            elif min_price is None:
                # If they only gave a max price, just favor items closer to it
                price_boost += ((current_price / max_price) * 15)

        # 5. Shipping Logic
        on_time_bonus = 0
        delivery_status = "unknown"
        if days_until_needed is not None:
            shipping_max = int(g.get("shipping_max_days") or 7)
            if shipping_max <= days_until_needed:
                on_time_bonus = 40
                delivery_status = "on_time"
            elif shipping_max <= days_until_needed + 2:
                on_time_bonus = 10
                delivery_status = "tight"
            else:
                on_time_bonus = -30  # Penalty for late items
                delivery_status = "late"

        # 6. Final Tally
        final_score = vector_score + score_data["total_boost"] + novelty_score + on_time_bonus + price_boost

        # Calculate the new, dynamic confidence metric
        confidence = compute_confidence(vec_sim, score_data["intent_match_count"], score_data["interest_match_count"])

        # 7. Generate User-Facing Reasons
        reasons = []
        if score_data["matched_intent"]:
            reasons.append(f"Matches: {', '.join(score_data['matched_intent'][:2])}")

        if score_data["interest_match_count"] > 0:
            reasons.append("Matches your interests")

        if delivery_status == "on_time":
            reasons.append("Fast shipping")

        g.update({
            "score": final_score,
            "confidence": confidence,  # Already rounded to 2 decimals
            "ranking_reasons": reasons if reasons else ["Highly rated match"],
            "delivery_status": delivery_status,
            "already_purchased": score_data.get("already_purchased", False)
        })
        scored.append(g)

    # Diversity Logic
    scored.sort(key=lambda x: x["score"], reverse=True)
    category_counter = defaultdict(int)
    for gift in scored:
        cats = gift.get("categories", [])
        for cat in cats:
            if category_counter[cat] >= MAX_CATEGORY_DOMINANCE:
                gift["score"] -= DIVERSITY_PENALTY
            category_counter[cat] += 1

    # Final Sort
    scored.sort(key=lambda x: x["score"], reverse=True)
    final_results = scored[:k]

    logger.info(f"Final Selection: {[f.get('display_name') for f in final_results]}")

    return final_results