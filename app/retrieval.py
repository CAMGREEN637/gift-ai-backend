import os
import logging
import traceback
import re
import json
import time
from typing import Any, List, Dict, Optional, Set, Tuple
from collections import defaultdict
from dotenv import load_dotenv

from app.embeddings import generate_embedding
from app.persistence import get_feedback
from app.schemas import RecommendRequest

load_dotenv()
logger = logging.getLogger(__name__)

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
    "named", "called",
    "cozy", "warm", "comfortable", "home",
    "luxury", "premium", "high", "end",
    "indulgent", "range", "mid"
}

VECTOR_MATCH_THRESHOLD = 0.0
SEMANTIC_BYPASS_THRESHOLD = 0.72

# --------------------------------------------------
# SCORING WEIGHTS — ORIGINAL
# --------------------------------------------------

VECTOR_WEIGHT = 35
INTENT_WEIGHT = 40
SESSION_WEIGHT = 80
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

MIN_VECTOR_SCORE_FOR_FULL_SCORING = 0.35
CONFIDENT_INTEREST_MISMATCH_PENALTY = -80

# --------------------------------------------------
# SCORING WEIGHTS — QUIZ SIGNALS
# --------------------------------------------------

WEIGHT_VECTOR_SIMILARITY = 0.25
WEIGHT_VIBE_MATCH = 0.20
WEIGHT_INTEREST_MATCH = 0.20
WEIGHT_OVERLAP_BONUS = 0.12
WEIGHT_OCCASION_MATCH = 0.10
MALE_SKEW_PENALTY = 0.15

# Raised to 0.35 so discouraged gifts take a ~15pt hit (0.35 * -1.5 * 30)
# — enough to reorder results meaningfully without overriding strong interest matches.
WEIGHT_GIFT_TYPE_AFFINITY = 0.35

# --------------------------------------------------
# NICHE INTEREST HARD FILTER
# --------------------------------------------------

NICHE_INTEREST_TAGS: Set[str] = {"pets"}

# --------------------------------------------------
# OCCASION → VIBE AFFINITY
# --------------------------------------------------

OCCASION_VIBE_AFFINITY: Dict[str, List[str]] = {
    "birthday": ["luxe", "fun", "thoughtful"],
    "valentines": ["romantic", "sentimental", "pampering"],
    "anniversary": ["sentimental", "romantic", "luxe"],
    "christmas": ["cozy", "fun", "luxe"],
    "mothers_day": ["pampering", "luxe", "cozy", "sentimental"],
    "just_because": ["romantic", "cozy", "fun"],
    "apology": ["pampering", "sentimental", "thoughtful"],
}

# --------------------------------------------------
# OCCASION → GIFT TYPE AFFINITY
# --------------------------------------------------
# All tags verified against actual DB values from:
#   SELECT DISTINCT gift_type FROM gifts;
#
# Confirmed DB tags: tech, home, outdoors, fitness, hobby, beauty, kitchen, book, fashion
#
# Original table used "jewelry" (→ beauty) and "loungewear" (→ home) which
# don't exist in the DB. Remapped to nearest real equivalents.

GIFT_TYPE_OCCASION_AFFINITY: Dict[str, Dict[str, List[str]]] = {
    "valentines": {
        # Personal, warm, pampering. Beauty and home cover the bulk of what
        # lands well. Fashion works for style-conscious partners.
        "recommended": ["beauty", "home", "fashion"],
        # Tech rarely feels romantic. Fitness risks reading as a comment on
        # her body. Outdoors lacks intimacy. Kitchen feels utilitarian.
        "discouraged": ["tech", "fitness", "outdoors", "kitchen"],
    },
    "anniversary": {
        "recommended": ["beauty", "home", "fashion"],
        "discouraged": ["tech", "fitness", "outdoors", "kitchen"],
    },
    "birthday": {
        # Most permissive occasion — almost any type lands if interest-matched.
        "recommended": ["beauty", "hobby", "book", "home", "fashion"],
        "discouraged": [],
    },
    "christmas": {
        # Cozy, indulgent, unwrappable. Home and beauty are the sweet spot.
        "recommended": ["home", "beauty", "hobby", "book"],
        "discouraged": [],
    },
    "mothers_day": {
        "recommended": ["beauty", "home", "fashion"],
        "discouraged": ["tech", "fitness", "outdoors"],
    },
    "just_because": {
        # Spontaneous gifts should feel warm and personal, not utilitarian.
        "recommended": ["beauty", "home", "book"],
        "discouraged": ["tech", "fitness", "outdoors", "kitchen"],
    },
    "apology": {
        # Needs to feel warm and personal. Kitchen implies domestic expectations.
        # Tech signals you grabbed something easy.
        "recommended": ["beauty", "home", "fashion"],
        "discouraged": ["tech", "fitness", "outdoors", "kitchen"],
    },
}

# Stage amplifies the affinity signal — higher commitment = sharper penalties.
STAGE_AFFINITY_MULTIPLIER: Dict[str, float] = {
    "new": 0.5,
    "dating": 1.0,
    "serious": 1.3,
    "committed": 1.5,
    "complicated": 0.7,
}

APOLOGY_PRICE_CEILING = 150.0

# --------------------------------------------------
# CONFIDENCE LEVEL MULTIPLIERS
# --------------------------------------------------

CONFIDENCE_MULTIPLIERS = {
    "confident": {"interest": 1.4, "vibe": 0.8, "overlap": 1.5},
    "somewhat": {"interest": 1.0, "vibe": 1.0, "overlap": 1.2},
    "lost": {"interest": 0.0, "vibe": 1.3, "overlap": 0.0},
}

# --------------------------------------------------
# RESULTS PAGE COPY
# --------------------------------------------------

RESULTS_HEADLINES: Dict[str, Dict[str, str]] = {
    "valentines": {
        "new": "Some low-pressure picks she'll actually love.",
        "dating": "Warm, intentional, and made for Valentine's Day.",
        "serious": "Personal gifts that go beyond the occasion.",
        "committed": "For the person who already has your heart.",
        "complicated": "Warm without saying too much.",
    },
    "anniversary": {
        "new": "Celebrating the milestone without overdoing it.",
        "dating": "Gifts that say you've been paying attention.",
        "serious": "Something as meaningful as the time you've spent.",
        "committed": "For the person you keep choosing.",
        "complicated": "A gesture that's warm without being heavy.",
    },
    "birthday": {
        "new": "Something fun and personal for her big day.",
        "dating": "Specific to her. That's the whole point.",
        "serious": "The treat-herself gift she'd never buy.",
        "committed": "Her day. Make it count.",
        "complicated": "Keep it personal. Keep it light.",
    },
    "christmas": {
        "new": "Warm, cozy, and just right for the season.",
        "dating": "Something she'll love unwrapping.",
        "serious": "An upgrade she didn't know she needed.",
        "committed": "Warm, generous, and unmistakably thoughtful.",
        "complicated": "Seasonal and warm — no strings attached.",
    },
    "mothers_day": {
        "new": "A thoughtful gesture for a special day.",
        "dating": "Pampering picks she deserves.",
        "serious": "For the woman who does everything.",
        "committed": "Celebrate her — fully.",
        "complicated": "Appreciation, no strings.",
    },
    "just_because": {
        "new": "A spontaneous gift that says you were thinking of her.",
        "dating": "The most romantic move? Doing it for no reason.",
        "serious": "She'll remember this one.",
        "committed": "Show her you still think about her unprompted.",
        "complicated": "Warm and genuine. No agenda.",
    },
    "apology": {
        "new": "Sincere, thoughtful, and the right size for right now.",
        "dating": "Personal over pricey. Always.",
        "serious": "Something that shows you actually know her.",
        "committed": "Make it right. Make it personal.",
        "complicated": "Warm, modest, and genuine.",
    },
}


def get_results_headline(occasion: str, stage: Optional[str]) -> Tuple[str, str]:
    headlines = RESULTS_HEADLINES.get(occasion, {})
    headline = headlines.get(stage or "dating", "Here are some great options for her.")
    sublines = {
        "confident": "Matched to her specific interests.",
        "somewhat": "A mix of specific and crowd-pleasing picks.",
        "lost": "Top-rated gifts for the occasion — no guesswork needed.",
    }
    subline = sublines.get("somewhat", "")
    return headline, subline


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
    return {t for t in tokens if len(t) > 3}


def extract_meaningful_intent_tokens(query: str, partner_name: Optional[str] = None) -> Set[str]:
    all_tokens = tokenize(query)
    partner_name_tokens = set()
    if partner_name:
        partner_name_tokens = {t.lower() for t in partner_name.split() if len(t) > 2}
    meaningful = all_tokens - GENERIC_TOKENS - partner_name_tokens
    logger.info(f"Query: '{query}' -> Meaningful tokens: {meaningful}")
    return meaningful


def normalize_jsonb_to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip().lower() for v in value if v]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip().lower() for v in parsed if v]
        except (json.JSONDecodeError, TypeError, AttributeError):
            return [v.strip().lower() for v in str(value).split(",") if v.strip()]
    return []


def normalize_preferences(preferences: Optional[Dict]) -> Dict:
    if not preferences:
        return {"interests": []}
    interests = preferences.get("interests", [])
    if isinstance(interests, str):
        interests = [i.strip() for i in interests.split(",")]
    return {"interests": [str(i).lower() for i in interests if i]}


def compute_price_affinity_bonus(
        price: float,
        min_price: Optional[float],
        max_price: Optional[float],
) -> float:
    if max_price is None or price is None or price == 0.0:
        return 0.0
    effective_min = min_price if min_price is not None else 0.0
    price_range = max_price - effective_min
    if price_range <= 0:
        return 0.0
    position = max(0.0, min(1.0, (price - effective_min) / price_range))
    if position >= 0.75:
        return float(PRICE_AFFINITY_MAX_BONUS)
    elif position >= 0.50:
        return float(PRICE_AFFINITY_MAX_BONUS * 0.5)
    return 0.0


def build_search_query(request: RecommendRequest) -> str:
    parts = []
    occasion_phrases = {
        "birthday": "birthday gift",
        "valentines": "Valentine's Day gift",
        "anniversary": "anniversary gift",
        "christmas": "Christmas gift",
        "mothers_day": "Mother's Day gift",
        "just_because": "surprise gift",
        "apology": "apology gift sincere",
    }
    if request.confidence == "confident" and request.interests:
        parts.append(" ".join(request.interests[:5]))
        if request.overlap_interests:
            parts.append(" ".join(request.overlap_interests))
        if request.niche_keywords:
            parts.append(" ".join(request.niche_keywords))
        parts.append(occasion_phrases.get(request.occasion or "", "gift for her"))
    else:
        parts.append(occasion_phrases.get(request.occasion or "", "gift for her"))
        stage_phrases = {
            "new": "new relationship", "dating": "girlfriend",
            "serious": "girlfriend", "committed": "wife",
            "complicated": "girlfriend",
        }
        if request.relationship_stage:
            parts.append(stage_phrases.get(request.relationship_stage, ""))
        if request.confidence != "lost" and request.interests:
            parts.append(" ".join(request.interests[:5]))
        if request.overlap_interests:
            parts.append(" ".join(request.overlap_interests))
        if request.niche_keywords:
            parts.append(" ".join(request.niche_keywords))
    return " ".join(filter(None, parts))


# --------------------------------------------------
# GIFT-TYPE AFFINITY
# --------------------------------------------------

def _gift_type_affinity_score(
        gift_categories: List[str],
        occasion: Optional[str],
        stage: Optional[str],
) -> Tuple[float, str]:
    """
    Returns (score, classification).
    score          ∈ [-1.5, 1.5] after stage multiplier
    classification ∈ "recommended" | "discouraged" | "neutral"
    """
    if not occasion or not gift_categories:
        return 0.0, "neutral"

    affinity = GIFT_TYPE_OCCASION_AFFINITY.get(occasion, {})
    recommended = set(affinity.get("recommended", []))
    discouraged = set(affinity.get("discouraged", []))

    if not recommended and not discouraged:
        return 0.0, "neutral"

    gift_cats = {str(c).lower() for c in gift_categories}

    if gift_cats & recommended:
        base_score = 1.0
        classification = "recommended"
    elif gift_cats & discouraged:
        base_score = -1.0
        classification = "discouraged"
    else:
        return 0.0, "neutral"

    multiplier = STAGE_AFFINITY_MULTIPLIER.get(stage or "dating", 1.0)
    return base_score * multiplier, classification


# --------------------------------------------------
# ORIGINAL SCORING
# --------------------------------------------------

def compute_enhanced_score(
        gift: Dict,
        meaningful_intent_tokens: Set[str],
        preferences: Dict,
        user_id: Optional[str],
        partner_profile: Optional[Dict],
        partner_gift_history: List[str],
        confidence_level: str = "somewhat",
        weak_vector_match: bool = False,
        feedback_lookup: Optional[Dict[str, int]] = None,
        niche_keywords: Optional[List[str]] = None,
) -> Dict:
    g_interests = gift.get("interests") or []
    g_categories = gift.get("gift_type") or gift.get("categories") or []
    g_vibes = gift.get("vibe") or []

    gift_text = (
            str(gift.get("name") or "") + " " +
            str(gift.get("description") or "") + " " +
            " ".join(g_interests) + " " +
            " ".join(g_categories)
    ).lower()

    matched_intent = [t for t in meaningful_intent_tokens if t in gift_text]
    effective_intent_count = min(len(matched_intent), 1) if weak_vector_match else len(matched_intent)
    intent_score = effective_intent_count * INTENT_WEIGHT

    user_interests = [i.lower().strip() for i in preferences.get("interests", []) if i]
    interest_overlap = set(g_interests) & set(user_interests)
    session_score = len(interest_overlap) * SESSION_WEIGHT
    exact_boost = 50 if interest_overlap else 0

    gift_tag_blob = " ".join(g_interests + g_categories).lower()
    gift_tag_tokens = set(gift_tag_blob.split())
    broad_interest_matches = set()
    for interest in user_interests:
        for token in interest.split():
            if len(token) > 2 and token in gift_tag_tokens:
                broad_interest_matches.add(interest)
                break

    profile_score = 0
    if partner_profile:
        p_interests = set(normalize_jsonb_to_list(partner_profile.get("interests")))
        p_vibe = set(normalize_jsonb_to_list(partner_profile.get("vibe")))
        profile_score = (
                len(set(g_interests) & p_interests) * PROFILE_WEIGHT +
                len(set(g_vibes) & p_vibe) * (PROFILE_WEIGHT * 0.7)
        )

    history_penalty = -50 if str(gift.get("id")) in [str(id) for id in partner_gift_history] else 0
    feedback_score = feedback_lookup.get(gift.get("name", ""), 0) if feedback_lookup else 0

    intent_penalty = 0
    if (len(meaningful_intent_tokens) > 0
            and len(matched_intent) == 0
            and len(broad_interest_matches) == 0):
        intent_penalty = -60

    niche_bonus = 0
    if niche_keywords:
        for kw in niche_keywords:
            if kw.lower() in gift_text:
                niche_bonus += 55
                break

    total_boost = (
            intent_score + session_score + exact_boost + profile_score
            + history_penalty + feedback_score + intent_penalty + niche_bonus
    )

    return {
        "total_boost": total_boost,
        "intent_match_count": len(matched_intent),
        "matched_intent": matched_intent,
        "already_purchased": history_penalty < 0,
        "broad_interest_matches": broad_interest_matches,
        "missed_intent": intent_penalty < 0,
        "interest_overlap": interest_overlap,
        "niche_bonus": niche_bonus,
    }


def compute_confidence(vector_similarity: float, intent_match_count: int) -> float:
    if intent_match_count >= 1:
        if vector_similarity >= 0.75: return 0.95
        if vector_similarity >= 0.65: return 0.89
        return 0.85
    return min(vector_similarity, 0.82)


def assign_ranked_confidence(results: List[Dict]) -> List[Dict]:
    for i, gift in enumerate(results):
        if gift.get("missed_intent", False):
            continue
        rank_confidence = max(0.65, round(0.90 - (i * 0.02), 2))
        gift["confidence"] = max(rank_confidence, gift.get("confidence", 0))
    return results


# --------------------------------------------------
# NEW QUIZ-SIGNAL SCORING
# --------------------------------------------------

def compute_quiz_signal_score(
        gift: Dict,
        request: RecommendRequest,
        conf_multipliers: Dict,
) -> Tuple[float, str]:
    """Returns (score, gift_type_classification)."""
    score = 0.0

    g_vibes = gift.get("vibe") or []
    g_interests = gift.get("interests") or []
    g_occasions = gift.get("occasions") or []
    g_categories = gift.get("gift_type") or gift.get("categories") or []
    gender_skew = gift.get("gender_skew") or "unisex"
    gift_price = float(gift.get("price") or 0)

    if gender_skew == "male":
        score -= MALE_SKEW_PENALTY

    vec_sim = float(gift.get("similarity") or 0)
    score += WEIGHT_VECTOR_SIMILARITY * vec_sim

    requested_vibes = list(request.vibe or [])
    occasion_vibes = OCCASION_VIBE_AFFINITY.get(request.occasion or "", [])
    all_vibes = list(set(requested_vibes + occasion_vibes))
    if g_vibes and all_vibes:
        matched_vibe = sum(1 for v in g_vibes if v in all_vibes)
        vibe_score = matched_vibe / max(len(g_vibes), 1)
        score += WEIGHT_VIBE_MATCH * vibe_score * conf_multipliers["vibe"]

    if conf_multipliers["interest"] > 0:
        requested_interests = list(request.interests or [])
        overlap_interests = list(request.overlap_interests or [])
        if g_interests and requested_interests:
            matched_interest = sum(1 for i in g_interests if i in requested_interests)
            interest_score = matched_interest / max(len(g_interests), 1)
            score += WEIGHT_INTEREST_MATCH * interest_score * conf_multipliers["interest"]
        if g_interests and overlap_interests:
            overlap_matched = sum(1 for i in g_interests if i in overlap_interests)
            if overlap_matched > 0:
                overlap_score = overlap_matched / max(len(g_interests), 1)
                score += WEIGHT_OVERLAP_BONUS * overlap_score * conf_multipliers["overlap"]

    if request.occasion and g_occasions:
        if request.occasion in g_occasions:
            score += WEIGHT_OCCASION_MATCH

    gift_type_classification = "neutral"
    if request.occasion:
        affinity_score, gift_type_classification = _gift_type_affinity_score(
            gift_categories=g_categories,
            occasion=request.occasion,
            stage=request.relationship_stage,
        )
        score += WEIGHT_GIFT_TYPE_AFFINITY * affinity_score

    if request.relationship_stage:
        score += _relationship_stage_bonus(
            request.relationship_stage, g_vibes, gift_price, request
        )

    return score, gift_type_classification


def _relationship_stage_bonus(
        stage: str,
        gift_vibes: List[str],
        gift_price: float,
        request: RecommendRequest,
) -> float:
    bonus = 0.0
    if stage == "new":
        if any(v in gift_vibes for v in ["fun", "cozy", "thoughtful"]):
            bonus += 0.05
        if any(v in gift_vibes for v in ["sentimental", "luxe", "romantic"]):
            bonus -= 0.05
        if gift_price > 75:
            bonus -= 0.10
    elif stage == "dating":
        if any(v in gift_vibes for v in ["thoughtful", "fun", "romantic"]):
            bonus += 0.05
    elif stage == "serious":
        if any(v in gift_vibes for v in ["luxe", "sentimental", "pampering"]):
            bonus += 0.05
    elif stage == "committed":
        if any(v in gift_vibes for v in ["sentimental", "pampering", "luxe"]):
            bonus += 0.08
        if getattr(request, "occasion", None) in ["valentines", "anniversary"] and gift_price < 50:
            bonus -= 0.08
    elif stage == "complicated":
        if any(v in gift_vibes for v in ["cozy", "fun", "thoughtful"]):
            bonus += 0.05
        if any(v in gift_vibes for v in ["romantic", "sentimental"]):
            bonus -= 0.03
        if gift_price > 100:
            bonus -= 0.08
    return bonus


# --------------------------------------------------
# MAIN RETRIEVAL
# --------------------------------------------------

def retrieve_gifts(
        query: str,
        user_id: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        days_until_needed: Optional[int] = None,
        preferences: Optional[Dict] = None,
        partner_profile: Optional[Dict] = None,
        partner_gift_history: Optional[List[str]] = None,
        request: Optional[RecommendRequest] = None,
        k: int = 5,
) -> List[Dict]:
    """
    Two-pass scoring system:
      Pass 1 — interest-matched gifts (hard filter in confident mode)
      Pass 2 — vibe/occasion fallbacks when Pass 1 yields fewer than k results
    """
    preferences = normalize_preferences(preferences)
    partner_name = getattr(request, "partner_name", None) if request else None
    meaningful_intent_tokens = extract_meaningful_intent_tokens(query, partner_name)
    partner_gift_history = partner_gift_history or []

    confidence_level = "somewhat"
    if request is not None:
        confidence_level = getattr(request, "confidence", None) or "somewhat"
    conf_multipliers = CONFIDENCE_MULTIPLIERS.get(confidence_level, CONFIDENCE_MULTIPLIERS["somewhat"])

    effective_max = max_price
    if request is not None and getattr(request, "occasion", None) == "apology":
        effective_max = min(max_price or 999999, APOLOGY_PRICE_CEILING)

    user_interests_set = set(preferences.get("interests", []))

    request_interests: Optional[List[str]] = None
    if request is not None and confidence_level == "confident":
        niche_kw_set = set(kw.lower() for kw in (request.niche_keywords or []))
        all_interests = list(request.interests or [])
        request_interests = [i for i in all_interests if i.lower() not in niche_kw_set]
        # If ONLY niche keywords were provided (no taxonomy tags),
        # request_interests is now empty, which correctly disables
        # the Pass 1 hard filter and lets vector similarity + scoring decide.

    feedback_lookup: Dict[str, int] = {}
    if user_id:
        try:
            history = get_feedback(user_id)
            for entry in history:
                name = entry.get("gift_name", "")
                if name:
                    feedback_lookup[name] = feedback_lookup.get(name, 0) + (
                        15 if entry.get("liked") else -25
                    )
        except Exception as e:
            logger.warning(f"Could not fetch feedback history: {e}")

    try:
        supabase = get_supabase_client()
        t_embed = time.time()
        embedding = generate_embedding(query)
        logger.info(f"[PERF] Embedding: {(time.time() - t_embed) * 1000:.0f}ms")
        if not embedding or len(embedding) == 0:
            logger.error("Embedding generation returned empty result.")
            return []

        t_search = time.time()
        response = supabase.rpc(
            "match_gifts",
            {"query_embedding": embedding, "match_threshold": VECTOR_MATCH_THRESHOLD, "match_count": 80},
        ).execute()
        logger.info(f"[PERF] Vector search: {(time.time() - t_search) * 1000:.0f}ms")
        raw_gifts = response.data or []
        logger.info(f"Retrieved {len(raw_gifts)} candidates from vector search")

    except Exception as e:
        logger.error(f"Vector search error: {e}")
        logger.error(traceback.format_exc())
        return []

    # --------------------------------------------------
    # NORMALISE RAW GIFTS
    # --------------------------------------------------
    normalised = []
    for g in raw_gifts:
        g["interests"] = normalize_jsonb_to_list(g.get("interests"))
        g["gift_type"] = normalize_jsonb_to_list(g.get("gift_type") or g.get("categories"))
        g["categories"] = g["gift_type"]
        g["vibe"] = normalize_jsonb_to_list(g.get("vibe"))
        g["occasions"] = normalize_jsonb_to_list(g.get("occasions"))

        if not g.get("display_name"):
            g["display_name"] = g.get("name", "Unique Gift")
        g["product_url"] = g.get("link") or g.get("product_url")

        try:
            current_price = float(g.get("price") or 0)
        except (ValueError, TypeError):
            current_price = 0.0

        if effective_max is not None and current_price > effective_max:
            continue
        if (effective_max is not None
                and effective_max <= PRICE_FLOOR_MAX_BUDGET
                and current_price > 0
                and current_price < effective_max * PRICE_FLOOR_RATIO):
            continue

        gift_interests_set = set(g.get("interests") or [])
        unselected_niche = (NICHE_INTEREST_TAGS & gift_interests_set) - (NICHE_INTEREST_TAGS & user_interests_set)
        if unselected_niche:
            continue

        normalised.append((g, current_price))

    # --------------------------------------------------
    # SCORING HELPER
    # --------------------------------------------------
    def _score_gift(g: Dict, current_price: float, is_fallback: bool = False) -> Dict:
        vec_sim = float(g.get("similarity") or 0)
        weak_vector_match = vec_sim < MIN_VECTOR_SCORE_FOR_FULL_SCORING
        vector_score = vec_sim * VECTOR_WEIGHT

        niche_kws = list(request.niche_keywords or []) if request else []

        score_data = compute_enhanced_score(
            g, meaningful_intent_tokens, preferences,
            user_id, partner_profile, partner_gift_history,
            confidence_level=confidence_level,
            weak_vector_match=weak_vector_match,
            feedback_lookup=feedback_lookup,
            niche_keywords=niche_kws,
        )

        if score_data.get("niche_bonus", 0) > 0:
            logger.info(
                f"Niche bonus +{score_data['niche_bonus']} for '{g.get('display_name')}' "
                f"(matched niche keyword in gift text)"
            )

        novelty_score = NOVELTY_BOOST if str(g.get("id")) not in [str(gid) for gid in partner_gift_history] else 0

        try:
            price_affinity = compute_price_affinity_bonus(current_price, min_price, effective_max)
        except (ValueError, TypeError):
            price_affinity = 0.0

        on_time_bonus = 0
        delivery_status = "unknown"
        if days_until_needed is not None:
            shipping_max = int(g.get("shipping_max_days") or 7)
            if shipping_max <= days_until_needed:
                on_time_bonus, delivery_status = SHIPPING_ON_TIME_BONUS, "on_time"
            elif shipping_max <= days_until_needed + 2:
                on_time_bonus, delivery_status = SHIPPING_TIGHT_BONUS, "tight"
            else:
                on_time_bonus, delivery_status = SHIPPING_LATE_PENALTY, "late"

        has_relevance = (
                score_data["intent_match_count"] >= 2
                or (score_data["intent_match_count"] >= 1 and len(score_data["broad_interest_matches"]) > 0)
        )
        gated_price_affinity = price_affinity if (has_relevance and not weak_vector_match) else 0.0

        original_score = (
                vector_score + score_data["total_boost"] + novelty_score
                + on_time_bonus + gated_price_affinity
        )

        quiz_signal_score = 0.0
        gift_type_classification = "neutral"
        if request is not None:
            raw_quiz_score, gift_type_classification = compute_quiz_signal_score(g, request, conf_multipliers)
            quiz_signal_score = raw_quiz_score * 30

        final_score = original_score + quiz_signal_score

        # Fallbacks are by definition non-interest-matches — they were promoted
        # because Pass 1 came up short. Suppress the missed_intent flag for them
        # so assign_ranked_confidence() will lift their confidence above the
        # 0.65 threshold based on rank position. Otherwise they get filtered out
        # in main.py and the user sees an empty results page.
        effective_missed_intent = (
            False if is_fallback else score_data.get("missed_intent", False)
        )

        confidence_val = compute_confidence(vec_sim, score_data["intent_match_count"])

        reasons = []
        if score_data["matched_intent"]:
            reasons.append(f"Matches: {', '.join(score_data['matched_intent'][:2])}")
        if score_data["broad_interest_matches"]:
            reasons.append("Matches your interests")
        if delivery_status == "on_time":
            reasons.append("Fast shipping")
        if gift_type_classification == "recommended":
            reasons.append("A safe bet for this occasion")
        elif gift_type_classification == "discouraged":
            reasons.append("Unusual pick — but her interests made it work")
        if is_fallback:
            reasons.append("Great for the occasion")

        g.update({
            "score": final_score,
            "confidence": round(confidence_val, 2),
            "ranking_reasons": reasons if reasons else ["Highly rated match"],
            "delivery_status": delivery_status,
            "already_purchased": score_data.get("already_purchased", False),
            "missed_intent": effective_missed_intent,
            "fallback": is_fallback,
            "gift_type_classification": gift_type_classification,
        })
        return g

    # --------------------------------------------------
    # PASS 1 — interest hard filter in confident mode
    # --------------------------------------------------
    scored = []
    niche_kws_pass1 = set(kw.lower() for kw in (request.niche_keywords or [])) if request else set()

    for g, current_price in normalised:
        gift_interests_set = set(g.get("interests") or [])
        if confidence_level == "confident" and (request_interests or niche_kws_pass1):
            has_tag_match = bool(request_interests and (gift_interests_set & set(request_interests)))

            # Check for niche keyword text match
            text_blob = (str(g.get("name") or "") + " " + str(g.get("description") or "")).lower()
            has_niche_match = any(kw in text_blob for kw in niche_kws_pass1)

            has_semantic_match = float(g.get("similarity") or 0) >= SEMANTIC_BYPASS_THRESHOLD

            if not (has_tag_match or has_niche_match or has_semantic_match):
                continue
            if not has_tag_match and not has_niche_match and has_semantic_match:
                logger.info(
                    f"Semantic bypass: '{g.get('display_name')}' "
                    f"(sim={float(g.get('similarity') or 0):.3f}, "
                    f"tags={list(gift_interests_set)})"
                )
        scored.append(_score_gift(g, current_price, is_fallback=False))

    logger.info(f"Pass 1 yielded {len(scored)} interest-matched gifts")

    # --------------------------------------------------
    # PASS 2 — fallback (only when Pass 1 < k)
    # --------------------------------------------------
    if len(scored) < k and confidence_level == "confident" and (request_interests or niche_kws_pass1):
        needed = k - len(scored)
        pass1_ids = {str(g.get("id")) for g in scored}
        requested_vibes = set(request.vibe or []) if request else set()
        occasion_vibes = set(OCCASION_VIBE_AFFINITY.get(getattr(request, "occasion", "") or "", []))
        request_occasion = getattr(request, "occasion", None) if request else None

        fallback_candidates = []
        for g, current_price in normalised:
            if str(g.get("id")) in pass1_ids:
                continue
            g_vibes = set(g.get("vibe") or [])
            g_occasions = set(g.get("occasions") or [])
            if g_vibes & requested_vibes:
                fallback_tier = 1
            elif g_vibes & occasion_vibes:
                fallback_tier = 2
            elif request_occasion and request_occasion in g_occasions:
                fallback_tier = 3
            else:
                fallback_tier = 4
            sim_score = float(g.get("similarity") or 0)
            fallback_candidates.append((fallback_tier, sim_score, g, current_price))

        fallback_candidates.sort(key=lambda x: (x[0], -x[1]))

        added = 0
        for tier, sim_score, g, current_price in fallback_candidates:
            if added >= needed:
                break
            _score_gift(g, current_price, is_fallback=True)
            scored.append(g)
            added += 1
            logger.info(f"Pass 2 (tier {tier}, sim {sim_score:.2f}) added fallback: '{g.get('display_name')}'")

    # --------------------------------------------------
    # DIVERSITY + FINAL SORT
    # --------------------------------------------------
    scored.sort(key=lambda x: x["score"], reverse=True)
    category_counter = defaultdict(int)
    for gift in scored:
        cats = gift.get("gift_type") or gift.get("categories") or []
        for cat in cats:
            if category_counter[cat] >= MAX_CATEGORY_DOMINANCE:
                gift["score"] -= DIVERSITY_PENALTY
                break
            category_counter[cat] += 1

    scored.sort(key=lambda x: x["score"], reverse=True)
    final_results = scored[:k]
    final_results = assign_ranked_confidence(final_results)

    pass1_count = sum(1 for g in final_results if not g.get("fallback"))
    pass2_count = sum(1 for g in final_results if g.get("fallback"))
    logger.info(
        f"Final selection ({pass1_count} interest-matched, {pass2_count} fallback): "
        f"{[f.get('display_name') for f in final_results]}"
    )
    return final_results