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
VECTOR_WEIGHT = 60       # Vector alone can't override explicit interest matches
INTENT_WEIGHT = 40       # Strong bonus per keyword match in gift text
SESSION_WEIGHT = 35      # Strong bonus when gift interests overlap with quiz interests
PROFILE_WEIGHT = 3

DIVERSITY_PENALTY = 20
NOVELTY_BOOST = 10
MAX_CATEGORY_DOMINANCE = 3

# Price affinity: max bonus awarded when a gift price is at the top of the range
PRICE_AFFINITY_MAX_BONUS = 25

# Shipping: fast shipping is a tiebreaker, not a primary signal
SHIPPING_ON_TIME_BONUS = 15   # was 40 — reduced so cheap fast-shipping items don't dominate
SHIPPING_TIGHT_BONUS = 5
SHIPPING_LATE_PENALTY = -20

# Price floor: exclude gifts priced below this fraction of max_price
# e.g. 0.10 means an $8 gift won't surface on a $200 budget
PRICE_FLOOR_RATIO = 0.10


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


def compute_price_affinity_bonus(
        price: float,
        min_price: Optional[float],
        max_price: Optional[float]
) -> float:
    """
    Reward gifts that sit in the upper portion of the user's price range.
    Returns a score bonus between 0 and PRICE_AFFINITY_MAX_BONUS.

    Scoring curve:
      - Price at or above 75% of the range  → full bonus
      - Price between 50%-75% of the range  → half bonus
      - Price below 50% of the range        → no bonus
      - No range specified                  → no bonus
    """
    if max_price is None or price is None:
        return 0.0

    effective_min = min_price if min_price is not None else 0.0
    price_range = max_price - effective_min

    if price_range <= 0:
        return 0.0

    position = (price - effective_min) / price_range
    position = max(0.0, min(1.0, position))

    if position >= 0.75:
        return float(PRICE_AFFINITY_MAX_BONUS)
    elif position >= 0.50:
        return float(PRICE_AFFINITY_MAX_BONUS * 0.5)
    else:
        return 0.0


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

    # Interest matching: only score against structured tags (interests + categories),
    # NOT the free-text description. This prevents "travel" in "great for travel or home use"
    # from giving the same boost as a gift actually tagged with travel.
    user_interests = [i.lower().strip() for i in preferences.get("interests", []) if i]
    gift_tag_blob = " ".join(g_interests + g_categories).lower()

    broad_interest_matches = set()
    for interest in user_interests:
        for token in interest.split():
            if len(token) > 2 and token in gift_tag_blob:
                broad_interest_matches.add(interest)
                break

    session_score = len(broad_interest_matches) * SESSION_WEIGHT

    profile_score = 0
    if partner_profile:
        p_interests = set(normalize_jsonb_to_list(partner_profile.get("interests")))
        p_vibe = set(normalize_jsonb_to_list(partner_profile.get("vibe")))

        profile_score = (
                len(set(g_interests) & p_interests) * PROFILE_WEIGHT +
                len(set(g_vibes) & p_vibe) * (PROFILE_WEIGHT * 0.7)
        )

    history_penalty = -50 if str(gift.get("id")) in [str(id) for id in partner_gift_history] else 0

    feedback_score = 0
    if user_id:
        try:
            history = get_feedback(user_id)
            for entry in history:
                if entry.get("gift_name") == gift.get("name"):
                    feedback_score += 15 if entry.get("liked") else -25
        except Exception as e:
            logger.warning(f"Could not fetch feedback for scoring: {e}")

    total_boost = intent_score + session_score + profile_score + history_penalty + feedback_score

    return {
        "total_boost": total_boost,
        "intent_match_count": len(matched_intent),
        "matched_intent": matched_intent,
        "already_purchased": history_penalty < 0,
        "broad_interest_matches": broad_interest_matches,
    }


def compute_confidence(vector_similarity: float, intent_match_count: int):
    if intent_match_count >= 1:
        if vector_similarity >= 0.75: return 0.95
        if vector_similarity >= 0.65: return 0.89
        return 0.85
    return min(vector_similarity, 0.82)


def assign_ranked_confidence(results: List[Dict]) -> List[Dict]:
    """
    Re-assigns confidence scores based on final rank:
      - Rank 1  → 0.90
      - Rank 2  → 0.88
      - Rank 3  → 0.86
      - Rank 4+ → drops 0.02 per position, floor at 0.65
    Takes the higher of rank-based and signal-derived values.
    """
    for i, gift in enumerate(results):
        rank_confidence = max(0.65, round(0.90 - (i * 0.02), 2))
        gift["confidence"] = max(rank_confidence, gift.get("confidence", 0))
    return results


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
                "match_count": 80
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

        # 2. Hard Filters: Price ceiling and price floor
        try:
            current_price = float(g.get("price", 0))
        except (ValueError, TypeError):
            current_price = 0.0

        if max_price is not None and current_price > max_price:
            continue

        # Exclude gifts that are implausibly cheap for the stated budget.
        # e.g. an $8 gift won't appear on a $200 budget (floor = $20).
        if max_price is not None and current_price < max_price * PRICE_FLOOR_RATIO:
            logger.debug(f"Filtered out '{g.get('name')}' — price ${current_price:.2f} below floor for budget ${max_price}")
            continue

        # 3. Calculate Scores
        vec_sim = g.get("similarity", 0)
        vector_score = vec_sim * VECTOR_WEIGHT

        score_data = compute_enhanced_score(
            g, meaningful_intent_tokens, preferences,
            user_id, partner_profile, partner_gift_history
        )

        novelty_score = NOVELTY_BOOST if str(g.get("id")) not in [str(id) for id in partner_gift_history] else 0

        # 4. Price affinity bonus — rewards gifts near the top of the user's range
        try:
            price_affinity = compute_price_affinity_bonus(
                price=current_price,
                min_price=min_price,
                max_price=max_price
            )
        except (ValueError, TypeError):
            price_affinity = 0.0

        # 5. Shipping Logic — tiebreaker only, not a primary ranking signal
        on_time_bonus = 0
        delivery_status = "unknown"
        if days_until_needed is not None:
            shipping_max = int(g.get("shipping_max_days") or 7)
            if shipping_max <= days_until_needed:
                on_time_bonus = SHIPPING_ON_TIME_BONUS
                delivery_status = "on_time"
            elif shipping_max <= days_until_needed + 2:
                on_time_bonus = SHIPPING_TIGHT_BONUS
                delivery_status = "tight"
            else:
                on_time_bonus = SHIPPING_LATE_PENALTY
                delivery_status = "late"

        final_score = vector_score + score_data["total_boost"] + novelty_score + on_time_bonus + price_affinity
        confidence = compute_confidence(vec_sim, score_data["intent_match_count"])

        # 6. Generate User-Facing Reasons
        reasons = []
        if score_data["matched_intent"]:
            reasons.append(f"Matches: {', '.join(score_data['matched_intent'][:2])}")

        if score_data["broad_interest_matches"]:
            reasons.append("Matches your interests")

        if delivery_status == "on_time":
            reasons.append("Fast shipping")

        g.update({
            "score": final_score,
            "confidence": round(confidence, 2),
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

    # Re-assign confidence based on final rank so scores vary meaningfully
    final_results = assign_ranked_confidence(final_results)

    logger.info(f"Final Selection: {[f.get('display_name') for f in final_results]}")

    return final_results