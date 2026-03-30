import os
import logging
import traceback
import re
import json
import time
from typing import List, Dict, Optional, Set
from collections import defaultdict
from dotenv import load_dotenv

from app.embeddings import generate_embedding
from app.persistence import get_feedback

load_dotenv()
logger = logging.getLogger(__name__)

# Module-level singleton — avoids recreating the client (and its HTTP session) on every request
_supabase_client = None

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
VECTOR_WEIGHT = 60
INTENT_WEIGHT = 40
SESSION_WEIGHT = 35
PROFILE_WEIGHT = 3

DIVERSITY_PENALTY = 20
NOVELTY_BOOST = 10
MAX_CATEGORY_DOMINANCE = 3

PRICE_AFFINITY_MAX_BONUS = 25

SHIPPING_ON_TIME_BONUS = 15
SHIPPING_TIGHT_BONUS = 5
SHIPPING_LATE_PENALTY = -20

PRICE_FLOOR_RATIO = 0.08
PRICE_FLOOR_MAX_BUDGET = 2000


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def get_supabase_client():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise Exception("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _supabase_client = create_client(url, key)
        logger.info("Supabase client initialized (singleton)")
    return _supabase_client


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
    if max_price is None or price is None or price == 0.0:
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

    user_interests = [i.lower().strip() for i in preferences.get("interests", []) if i]
    gift_tag_blob = " ".join(g_interests + g_categories).lower()
    gift_tag_tokens = set(gift_tag_blob.split())

    broad_interest_matches = set()
    for interest in user_interests:
        for token in interest.split():
            if len(token) > 2 and token in gift_tag_tokens:
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

    # NEW: The Ignored Intent Penalty
    # If the user asked for specifics (e.g. "coffee") and the gift matches NONE of them, tank the score.
    intent_penalty = 0
    if len(meaningful_intent_tokens) > 0 and len(matched_intent) == 0 and len(broad_interest_matches) == 0:
        intent_penalty = -60  # This ensures generic items drop below the top K threshold
        logger.debug(f"Penalized {gift.get('name')} for ignoring intent tokens: {meaningful_intent_tokens}")

    total_boost = intent_score + session_score + profile_score + history_penalty + feedback_score + intent_penalty

    return {
        "total_boost": total_boost,
        "intent_match_count": len(matched_intent),
        "matched_intent": matched_intent,
        "already_purchased": history_penalty < 0,
        "broad_interest_matches": broad_interest_matches,
        "missed_intent": intent_penalty < 0  # Flag for confidence logic
    }


def compute_confidence(vector_similarity: float, intent_match_count: int):
    if intent_match_count >= 1:
        if vector_similarity >= 0.75: return 0.95
        if vector_similarity >= 0.65: return 0.89
        return 0.85
    return min(vector_similarity, 0.82)


def assign_ranked_confidence(results: List[Dict]) -> List[Dict]:
    for i, gift in enumerate(results):
        # NEW: Do not give a rank-based confidence boost to items that missed the core intent
        if gift.get("missed_intent", False):
            continue

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

        t_embed = time.time()
        embedding = generate_embedding(query)
        logger.info(f"[PERF] Embedding: {(time.time() - t_embed)*1000:.0f}ms (cache_info={generate_embedding.__wrapped__.__name__ if hasattr(generate_embedding, '__wrapped__') else 'n/a'})")
        if not embedding or len(embedding) == 0:
            logger.error("Embedding generation returned empty result.")
            return []

        t_search = time.time()
        response = supabase.rpc(
            "match_gifts",
            {
                "query_embedding": embedding,
                "match_threshold": VECTOR_MATCH_THRESHOLD,
                "match_count": 80
            }
        ).execute()
        logger.info(f"[PERF] Vector search: {(time.time() - t_search)*1000:.0f}ms")

        raw_gifts = response.data or []
        logger.info(f"Retrieved {len(raw_gifts)} candidates from vector search")

    except Exception as e:
        logger.error(f"Vector search error: {e}")
        logger.error(traceback.format_exc())
        return []

    scored = []

    for g in raw_gifts:
        g["interests"] = normalize_jsonb_to_list(g.get("interests"))
        g["categories"] = normalize_jsonb_to_list(g.get("categories"))
        g["vibe"] = normalize_jsonb_to_list(g.get("vibe"))
        g["occasions"] = normalize_jsonb_to_list(g.get("occasions"))

        if not g.get('display_name'):
            g['display_name'] = g.get('name', 'Unique Gift')

        g["product_url"] = g.get("link") or g.get("product_url")

        try:
            raw_price = g.get("price")
            current_price = float(raw_price) if raw_price is not None else 0.0
        except (ValueError, TypeError):
            current_price = 0.0

        if max_price is not None and current_price > max_price:
            continue

        if (max_price is not None
                and max_price <= PRICE_FLOOR_MAX_BUDGET
                and current_price > 0
                and current_price < max_price * PRICE_FLOOR_RATIO):
            continue

        vec_sim = g.get("similarity", 0)
        vector_score = vec_sim * VECTOR_WEIGHT

        score_data = compute_enhanced_score(
            g, meaningful_intent_tokens, preferences,
            user_id, partner_profile, partner_gift_history
        )

        novelty_score = NOVELTY_BOOST if str(g.get("id")) not in [str(id) for id in partner_gift_history] else 0

        try:
            price_affinity = compute_price_affinity_bonus(
                price=current_price,
                min_price=min_price,
                max_price=max_price
            )
        except (ValueError, TypeError):
            price_affinity = 0.0

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

        has_relevance = (
                score_data["intent_match_count"] > 0
                or len(score_data["broad_interest_matches"]) > 0
        )
        gated_price_affinity = price_affinity if has_relevance else 0.0

        final_score = vector_score + score_data["total_boost"] + novelty_score + on_time_bonus + gated_price_affinity
        confidence = compute_confidence(vec_sim, score_data["intent_match_count"])

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
            "already_purchased": score_data.get("already_purchased", False),
            "missed_intent": score_data.get("missed_intent", False)  # Pass flag to main loop
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
                break
            category_counter[cat] += 1

    # Final Sort
    scored.sort(key=lambda x: x["score"], reverse=True)
    final_results = scored[:k]

    final_results = assign_ranked_confidence(final_results)

    logger.info(f"Final Selection: {[f.get('display_name') for f in final_results]}")

    return final_results