import os
import logging
import traceback
import re
import json
import time
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict
from dotenv import load_dotenv

from app.embeddings import generate_embedding
from app.persistence import get_feedback
from app.schemas import RecommendRequest

load_dotenv()
logger = logging.getLogger(__name__)

# Module-level singleton — avoids recreating the client on every request
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

# FIX #1: Raised from 0.15 → 0.30 to filter out weak semantic matches
# (e.g. microphones appearing in skincare queries due to generic token overlap)
VECTOR_MATCH_THRESHOLD = 0.30

# --------------------------------------------------
# SCORING WEIGHTS — ORIGINAL
# --------------------------------------------------

VECTOR_WEIGHT            = 60
INTENT_WEIGHT            = 40
SESSION_WEIGHT           = 35
PROFILE_WEIGHT           = 3
DIVERSITY_PENALTY        = 20
NOVELTY_BOOST            = 10
MAX_CATEGORY_DOMINANCE   = 3
PRICE_AFFINITY_MAX_BONUS = 25
SHIPPING_ON_TIME_BONUS   = 15
SHIPPING_TIGHT_BONUS     = 5
SHIPPING_LATE_PENALTY    = -20
PRICE_FLOOR_RATIO        = 0.08
PRICE_FLOOR_MAX_BUDGET   = 2000

# FIX #2: Minimum vector similarity for full scoring.
# Gifts below this threshold still enter the loop (they passed VECTOR_MATCH_THRESHOLD)
# but have price affinity suppressed and intent score capped to 1 match worth of points.
# This prevents weak semantic matches from accumulating full bonus scores.
MIN_VECTOR_SCORE_FOR_FULL_SCORING = 0.35

# FIX #3: Additional penalty applied when confidence == "confident" and
# the gift's interests have zero overlap with the user's requested interests.
# Prevents topically irrelevant gifts from surviving on generic token hits.
CONFIDENT_INTEREST_MISMATCH_PENALTY = -40

# --------------------------------------------------
# SCORING WEIGHTS — NEW QUIZ SIGNALS
# Additive on top of the original scoring system.
# Scaled by 30x at the end to be ~15% of total score range.
# --------------------------------------------------

WEIGHT_VECTOR_SIMILARITY = 0.25  # Fix #5 — always use vector sim in final score
WEIGHT_VIBE_MATCH        = 0.20
WEIGHT_INTEREST_MATCH    = 0.20
WEIGHT_OVERLAP_BONUS     = 0.12  # Fix #2 — proportional, not flat
WEIGHT_OCCASION_MATCH    = 0.10
MALE_SKEW_PENALTY        = 0.15  # Fix #1 — soft penalty, not hard filter

# --------------------------------------------------
# NICHE INTEREST HARD FILTER
# Gift interests that should ONLY appear in results
# if the user explicitly selected that interest.
# Prevents e.g. "dog mom candle" from appearing for
# someone who never indicated they have a pet.
# Add to this set as new niche tags are introduced.
# --------------------------------------------------

NICHE_INTEREST_TAGS: Set[str] = {"pets"}

# --------------------------------------------------
# OCCASION → VIBE AFFINITY
# Boosts gifts whose vibe aligns with the occasion
# even if the user didn't explicitly select that vibe
# --------------------------------------------------

OCCASION_VIBE_AFFINITY: Dict[str, List[str]] = {
    "birthday":    ["luxe", "fun", "thoughtful"],
    "valentines":  ["romantic", "sentimental", "pampering"],
    "anniversary": ["sentimental", "romantic", "luxe"],
    "christmas":   ["cozy", "fun", "luxe"],
    "mothers_day": ["pampering", "luxe", "cozy", "sentimental"],
    "just_because":["romantic", "cozy", "fun"],
    "apology":     ["pampering", "sentimental", "thoughtful"],
}

# Soft price ceiling for apology occasion
APOLOGY_PRICE_CEILING = 150.0

# --------------------------------------------------
# CONFIDENCE LEVEL MULTIPLIERS
# Adjusts how much quiz signals are weighted based on
# how well the user knows her interests
# --------------------------------------------------

CONFIDENCE_MULTIPLIERS = {
    "confident": {"interest": 1.4, "vibe": 0.8,  "overlap": 1.5},
    "somewhat":  {"interest": 1.0, "vibe": 1.0,  "overlap": 1.2},
    "lost":      {"interest": 0.0, "vibe": 1.3,  "overlap": 0.0},
}

# --------------------------------------------------
# RESULTS PAGE COPY
# --------------------------------------------------

RESULTS_HEADLINES: Dict[str, Dict[str, str]] = {
    "valentines": {
        "new":         "Some low-pressure picks she'll actually love.",
        "dating":      "Warm, intentional, and made for Valentine's Day.",
        "serious":     "Personal gifts that go beyond the occasion.",
        "committed":   "For the person who already has your heart.",
        "complicated": "Warm without saying too much.",
    },
    "anniversary": {
        "new":         "Celebrating the milestone without overdoing it.",
        "dating":      "Gifts that say you've been paying attention.",
        "serious":     "Something as meaningful as the time you've spent.",
        "committed":   "For the person you keep choosing.",
        "complicated": "A gesture that's warm without being heavy.",
    },
    "birthday": {
        "new":         "Something fun and personal for her big day.",
        "dating":      "Specific to her. That's the whole point.",
        "serious":     "The treat-herself gift she'd never buy.",
        "committed":   "Her day. Make it count.",
        "complicated": "Keep it personal. Keep it light.",
    },
    "christmas": {
        "new":         "Warm, cozy, and just right for the season.",
        "dating":      "Something she'll love unwrapping.",
        "serious":     "An upgrade she didn't know she needed.",
        "committed":   "Warm, generous, and unmistakably thoughtful.",
        "complicated": "Seasonal and warm — no strings attached.",
    },
    "mothers_day": {
        "new":         "A thoughtful gesture for a special day.",
        "dating":      "Pampering picks she deserves.",
        "serious":     "For the woman who does everything.",
        "committed":   "Celebrate her — fully.",
        "complicated": "Appreciation, no strings.",
    },
    "just_because": {
        "new":         "A spontaneous gift that says you were thinking of her.",
        "dating":      "The most romantic move? Doing it for no reason.",
        "serious":     "She'll remember this one.",
        "committed":   "Show her you still think about her unprompted.",
        "complicated": "Warm and genuine. No agenda.",
    },
    "apology": {
        "new":         "Sincere, thoughtful, and the right size for right now.",
        "dating":      "Personal over pricey. Always.",
        "serious":     "Something that shows you actually know her.",
        "committed":   "Make it right. Make it personal.",
        "complicated": "Warm, modest, and genuine.",
    },
}


def get_results_headline(occasion: str, stage: Optional[str]) -> Tuple[str, str]:
    """Returns (headline, subline) for the results page."""
    headlines = RESULTS_HEADLINES.get(occasion, {})
    headline = headlines.get(stage or "dating", "Here are some great options for her.")
    sublines = {
        "confident": "Matched to her specific interests.",
        "somewhat":  "A mix of specific and crowd-pleasing picks.",
        "lost":      "Top-rated gifts for the occasion — no guesswork needed.",
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
    return {t for t in tokens if len(t) > 2}


def extract_meaningful_intent_tokens(query: str) -> Set[str]:
    all_tokens = tokenize(query)
    words = query.split()
    capitalized_words = {word.lower() for word in words if word and word[0].isupper()}
    meaningful = all_tokens - GENERIC_TOKENS - capitalized_words
    logger.info(f"Query: '{query}' -> Meaningful tokens: {meaningful}")
    return meaningful


def normalize_jsonb_to_list(value) -> List[str]:
    """Convert JSONB field to Python list of strings safely."""
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
# QUERY BUILDER
# Builds a natural language query string for embedding
# from the new quiz signals (occasion, stage, vibe, interests)
# --------------------------------------------------

def build_search_query(request: RecommendRequest) -> str:
    """
    Constructs a rich natural language query for the embedding.
    Used instead of the raw user query when a full RecommendRequest
    is available (i.e. when the user came through the new quiz).
    """
    parts = []

    occasion_phrases = {
        "birthday":    "birthday gift for girlfriend",
        "valentines":  "Valentine's Day gift for her",
        "anniversary": "anniversary gift romantic partner",
        "christmas":   "Christmas gift for girlfriend",
        "mothers_day": "Mother's Day gift pampering",
        "just_because":"surprise gift for girlfriend",
        "apology":     "apology gift for girlfriend sincere thoughtful",
    }
    parts.append(occasion_phrases.get(request.occasion or "", "gift for her"))

    stage_phrases = {
        "new":         "new relationship",
        "dating":      "girlfriend",
        "serious":     "serious girlfriend living together",
        "committed":   "wife or fiancée",
        "complicated": "girlfriend complicated relationship",
    }
    if request.relationship_stage:
        parts.append(stage_phrases.get(request.relationship_stage, ""))

    if request.vibe:
        vibe_phrases = {
            "pampering":   "pampering spa self-care relaxing",
            "romantic":    "romantic love intimate",
            "sentimental": "sentimental personal meaningful keepsake",
            "luxe":        "luxury premium high-end indulgent",
            "cozy":        "cozy warm comfortable home",
            "fun":         "fun playful surprising novelty",
            "thoughtful":  "thoughtful specific personal her interests",
        }
        for v in (request.vibe or []):
            if v in vibe_phrases:
                parts.append(vibe_phrases[v])

    # Interests — skip when confidence is 'lost'
    if request.confidence != "lost" and request.interests:
        parts.append(" ".join(request.interests[:5]))

    # Overlap interests get extra weight in the query itself
    if request.overlap_interests:
        parts.append(" ".join(request.overlap_interests))

    if request.max_price:
        if request.max_price <= 50:
            parts.append("affordable under 50 dollars")
        elif request.max_price <= 100:
            parts.append("mid-range gift")
        elif request.max_price <= 200:
            parts.append("premium gift")
        else:
            parts.append("luxury high-end gift")

    return " ".join(filter(None, parts))


# --------------------------------------------------
# ORIGINAL SCORING (preserved intact)
# --------------------------------------------------

def compute_enhanced_score(
    gift: Dict,
    meaningful_intent_tokens: Set[str],
    preferences: Dict,
    user_id: Optional[str],
    partner_profile: Optional[Dict],
    partner_gift_history: List[str],
    # FIX #3: new parameters for confident-mode interest mismatch penalty
    confidence_level: str = "somewhat",
    request_interests: Optional[List[str]] = None,
    # FIX #2: when True, cap intent score to 1 match worth of points
    weak_vector_match: bool = False,
) -> Dict:
    # Support both old column name (categories) and new (gift_type)
    g_interests  = gift.get("interests") or []
    g_categories = gift.get("gift_type") or gift.get("categories") or []
    g_vibes      = gift.get("vibe") or []

    gift_text = (
        str(gift.get("name") or "") + " " +
        str(gift.get("description") or "") + " " +
        " ".join(g_interests) + " " +
        " ".join(g_categories)
    ).lower()

    matched_intent = [t for t in meaningful_intent_tokens if t in gift_text]

    # FIX #2: cap intent score to 1 match worth of points for weak vector matches,
    # preventing generic token hits in unrelated descriptions from inflating score.
    effective_intent_count = min(len(matched_intent), 1) if weak_vector_match else len(matched_intent)
    intent_score = effective_intent_count * INTENT_WEIGHT

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
        p_vibe      = set(normalize_jsonb_to_list(partner_profile.get("vibe")))
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

    # Ignored Intent Penalty
    # If user asked for specifics and the gift matches none, tank the score
    intent_penalty = 0
    if (len(meaningful_intent_tokens) > 0
            and len(matched_intent) == 0
            and len(broad_interest_matches) == 0):
        intent_penalty = -60
        logger.debug(
            f"Penalized {gift.get('name')} for ignoring intent tokens: "
            f"{meaningful_intent_tokens}"
        )

    # FIX #3: Confident-mode interest mismatch penalty
    # When the user said they know her interests well (confidence == "confident")
    # and the gift's tagged interests share zero overlap with the requested
    # interests, apply an additional penalty. This prevents topically unrelated
    # gifts (e.g. microphones in a skincare query) from surviving on generic
    # token hits alone.
    confident_mismatch_penalty = 0
    if (confidence_level == "confident"
            and request_interests
            and len(broad_interest_matches) == 0):
        confident_mismatch_penalty = CONFIDENT_INTEREST_MISMATCH_PENALTY
        logger.debug(
            f"Confident-mode interest mismatch penalty applied to "
            f"'{gift.get('name')}': no overlap between gift interests "
            f"{g_interests} and requested interests {request_interests}"
        )

    total_boost = (
        intent_score + session_score + profile_score
        + history_penalty + feedback_score + intent_penalty
        + confident_mismatch_penalty
    )

    return {
        "total_boost":            total_boost,
        "intent_match_count":     len(matched_intent),
        "matched_intent":         matched_intent,
        "already_purchased":      history_penalty < 0,
        "broad_interest_matches": broad_interest_matches,
        "missed_intent":          intent_penalty < 0,
    }


def compute_confidence(vector_similarity: float, intent_match_count: int) -> float:
    if intent_match_count >= 1:
        if vector_similarity >= 0.75: return 0.95
        if vector_similarity >= 0.65: return 0.89
        return 0.85
    return min(vector_similarity, 0.82)


def assign_ranked_confidence(results: List[Dict]) -> List[Dict]:
    for i, gift in enumerate(results):
        # Don't give a rank-based confidence boost to items that missed intent
        if gift.get("missed_intent", False):
            continue
        rank_confidence = max(0.65, round(0.90 - (i * 0.02), 2))
        gift["confidence"] = max(rank_confidence, gift.get("confidence", 0))
    return results


# --------------------------------------------------
# NEW QUIZ-SIGNAL SCORING
# Runs alongside the original scoring when a full
# RecommendRequest is available. Returns an additive
# score that is scaled before being added to final_score.
# --------------------------------------------------

def compute_quiz_signal_score(
    gift: Dict,
    request: RecommendRequest,
    conf_multipliers: Dict,
) -> float:
    """
    Returns a normalized boost (0.0–~1.5) from quiz signals.
    Caller scales this by 30 before adding to the original score range.
    """
    score = 0.0

    g_vibes     = gift.get("vibe") or []
    g_interests = gift.get("interests") or []
    g_occasions = gift.get("occasions") or []
    gender_skew = gift.get("gender_skew") or "unisex"
    gift_price  = float(gift.get("price") or 0)

    # Fix #1: soft penalty for male-skewing gifts, not a hard filter
    if gender_skew == "male":
        score -= MALE_SKEW_PENALTY

    # Fix #5: always include vector similarity in the score
    vec_sim = float(gift.get("similarity") or 0)
    score += WEIGHT_VECTOR_SIMILARITY * vec_sim

    # Vibe match — user-selected vibes + occasion affinity vibes combined
    requested_vibes = list(request.vibe or [])
    occasion_vibes  = OCCASION_VIBE_AFFINITY.get(request.occasion or "", [])
    all_vibes       = list(set(requested_vibes + occasion_vibes))

    if g_vibes and all_vibes:
        matched_vibe = sum(1 for v in g_vibes if v in all_vibes)
        vibe_score   = matched_vibe / max(len(g_vibes), 1)
        score += WEIGHT_VIBE_MATCH * vibe_score * conf_multipliers["vibe"]

    # Interest match — skipped entirely when confidence is 'lost'
    if conf_multipliers["interest"] > 0:
        requested_interests = list(request.interests or [])
        overlap_interests   = list(request.overlap_interests or [])

        if g_interests and requested_interests:
            matched_interest = sum(1 for i in g_interests if i in requested_interests)
            interest_score   = matched_interest / max(len(g_interests), 1)
            score += WEIGHT_INTEREST_MATCH * interest_score * conf_multipliers["interest"]

        # Fix #2: proportional overlap bonus
        if g_interests and overlap_interests:
            overlap_matched = sum(1 for i in g_interests if i in overlap_interests)
            if overlap_matched > 0:
                overlap_score = overlap_matched / max(len(g_interests), 1)
                score += WEIGHT_OVERLAP_BONUS * overlap_score * conf_multipliers["overlap"]

    # Occasion match
    if request.occasion and g_occasions:
        if request.occasion in g_occasions:
            score += WEIGHT_OCCASION_MATCH

    # Relationship stage adjustments
    if request.relationship_stage:
        score += _relationship_stage_bonus(
            request.relationship_stage, g_vibes, gift_price, request
        )

    return score


def _relationship_stage_bonus(
    stage: str,
    gift_vibes: List[str],
    gift_price: float,
    request: RecommendRequest,
) -> float:
    """Small score adjustments based on relationship stage."""
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
        occasion = getattr(request, "occasion", None)
        if occasion in ["valentines", "anniversary"] and gift_price < 50:
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
    k: int = 10,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    days_until_needed: Optional[int] = None,
    preferences: Optional[Dict] = None,
    partner_profile: Optional[Dict] = None,
    partner_gift_history: Optional[List[str]] = None,
    # New optional parameter — when provided, quiz signal scoring activates
    request: Optional[RecommendRequest] = None,
) -> List[Dict]:
    """
    Main retrieval function.

    Combines two scoring systems:
      1. Original: intent tokens, broad interests, profile matching,
         feedback history, novelty, price affinity, shipping timing
      2. New quiz signals (additive, only when `request` is provided):
         vibe, occasion, relationship stage, confidence routing,
         interest matching, overlap interest boost, gender skew penalty

    The `request` parameter is optional for full backward compatibility.
    All existing callers that pass only `query` continue to work unchanged.

    Changes in this version:
      - FIX #1: VECTOR_MATCH_THRESHOLD raised from 0.15 → 0.30 to filter
        weak semantic matches before scoring begins.
      - FIX #2: MIN_VECTOR_SCORE_FOR_FULL_SCORING = 0.35 gate — gifts below
        this threshold have intent score capped to 1 match and price affinity
        suppressed, preventing generic token hits from inflating their score.
      - FIX #3: confident-mode interest mismatch penalty (-40 pts) applied
        inside compute_enhanced_score when confidence == "confident" and
        the gift has zero interest overlap with the user's requested interests.
      - FIX #4: price affinity relevance gate tightened to require ≥2 intent
        token matches, or 1 intent match + ≥1 broad interest match (was: any
        single token match).
      - NICHE FILTER: gifts tagged with niche interests (e.g. "pets") are hard-
        filtered out unless the user explicitly selected that interest.
    """
    preferences = normalize_preferences(preferences)
    meaningful_intent_tokens = extract_meaningful_intent_tokens(query)
    partner_gift_history = partner_gift_history or []

    # Determine confidence multipliers for quiz signal scoring
    confidence_level = "somewhat"
    if request is not None:
        confidence_level = getattr(request, "confidence", None) or "somewhat"
    conf_multipliers = CONFIDENCE_MULTIPLIERS.get(
        confidence_level, CONFIDENCE_MULTIPLIERS["somewhat"]
    )

    # Apply apology price ceiling (overrides passed max_price if lower)
    effective_max = max_price
    if request is not None and getattr(request, "occasion", None) == "apology":
        effective_max = min(max_price or 999999, APOLOGY_PRICE_CEILING)

    # Build the set of niche interests the user DID select, for filter use below
    user_interests_set = set(preferences.get("interests", []))

    try:
        supabase = get_supabase_client()

        t_embed = time.time()
        embedding = generate_embedding(query)
        logger.info(
            f"[PERF] Embedding: {(time.time() - t_embed)*1000:.0f}ms "
            f"(cache_info={generate_embedding.__wrapped__.__name__ if hasattr(generate_embedding, '__wrapped__') else 'n/a'})"
        )
        if not embedding or len(embedding) == 0:
            logger.error("Embedding generation returned empty result.")
            return []

        t_search = time.time()
        response = supabase.rpc(
            "match_gifts",
            {
                "query_embedding": embedding,
                "match_threshold": VECTOR_MATCH_THRESHOLD,
                "match_count": 80,
            }
        ).execute()
        logger.info(f"[PERF] Vector search: {(time.time() - t_search)*1000:.0f}ms")

        raw_gifts = response.data or []
        logger.info(f"Retrieved {len(raw_gifts)} candidates from vector search")

    except Exception as e:
        logger.error(f"Vector search error: {e}")
        logger.error(traceback.format_exc())
        return []

    # Resolve request_interests once for use in confident-mode penalty
    request_interests: Optional[List[str]] = None
    if request is not None and confidence_level == "confident":
        request_interests = list(request.interests or [])

    scored = []

    for g in raw_gifts:
        # Normalize all JSONB fields
        g["interests"]  = normalize_jsonb_to_list(g.get("interests"))
        g["gift_type"]  = normalize_jsonb_to_list(g.get("gift_type") or g.get("categories"))
        g["categories"] = g["gift_type"]  # backward compat alias
        g["vibe"]       = normalize_jsonb_to_list(g.get("vibe"))
        g["occasions"]  = normalize_jsonb_to_list(g.get("occasions"))

        if not g.get("display_name"):
            g["display_name"] = g.get("name", "Unique Gift")

        g["product_url"] = g.get("link") or g.get("product_url")

        try:
            current_price = float(g.get("price") or 0)
        except (ValueError, TypeError):
            current_price = 0.0

        # Hard price ceiling (respects apology ceiling)
        if effective_max is not None and current_price > effective_max:
            continue

        # Price floor — skip implausibly cheap gifts relative to budget
        if (effective_max is not None
                and effective_max <= PRICE_FLOOR_MAX_BUDGET
                and current_price > 0
                and current_price < effective_max * PRICE_FLOOR_RATIO):
            continue

        # --------------------------------------------------
        # NICHE INTEREST HARD FILTER
        # If the gift is tagged with any niche interest the user did NOT
        # select, exclude it entirely. This prevents e.g. pet-themed gifts
        # from surfacing for someone who never indicated they have a pet.
        # --------------------------------------------------
        gift_interests_set = set(g.get("interests") or [])
        unselected_niche_tags = NICHE_INTEREST_TAGS & gift_interests_set - NICHE_INTEREST_TAGS & user_interests_set
        if unselected_niche_tags:
            logger.debug(
                f"Niche filter removed '{g.get('name')}' — "
                f"tagged {unselected_niche_tags} but user did not select those interests"
            )
            continue

        vec_sim = float(g.get("similarity") or 0)

        # FIX #2: Gate flag — gifts with weak vector similarity get reduced
        # scoring power: intent score capped to 1 match and price affinity suppressed.
        weak_vector_match = vec_sim < MIN_VECTOR_SCORE_FOR_FULL_SCORING

        # ---- Original scoring ----------------------------------------
        vector_score = vec_sim * VECTOR_WEIGHT

        score_data = compute_enhanced_score(
            g, meaningful_intent_tokens, preferences,
            user_id, partner_profile, partner_gift_history,
            confidence_level=confidence_level,
            request_interests=request_interests,
            weak_vector_match=weak_vector_match,
        )

        novelty_score = (
            NOVELTY_BOOST
            if str(g.get("id")) not in [str(id) for id in partner_gift_history]
            else 0
        )

        try:
            price_affinity = compute_price_affinity_bonus(
                price=current_price,
                min_price=min_price,
                max_price=effective_max,
            )
        except (ValueError, TypeError):
            price_affinity = 0.0

        on_time_bonus  = 0
        delivery_status = "unknown"
        if days_until_needed is not None:
            shipping_max = int(g.get("shipping_max_days") or 7)
            if shipping_max <= days_until_needed:
                on_time_bonus   = SHIPPING_ON_TIME_BONUS
                delivery_status = "on_time"
            elif shipping_max <= days_until_needed + 2:
                on_time_bonus   = SHIPPING_TIGHT_BONUS
                delivery_status = "tight"
            else:
                on_time_bonus   = SHIPPING_LATE_PENALTY
                delivery_status = "late"

        # FIX #4: Tighter relevance gate — require at least 2 intent token matches,
        # or 1 intent match AND a broad interest match, before unlocking price affinity.
        # Previously a single generic token hit (e.g. "fun") was enough to unlock it.
        has_relevance = (
            score_data["intent_match_count"] >= 2
            or (score_data["intent_match_count"] >= 1
                and len(score_data["broad_interest_matches"]) > 0)
        )

        # FIX #2: Also suppress price affinity for weak vector matches regardless
        # of intent token hits, since those hits may be on generic description words.
        gated_price_affinity = price_affinity if (has_relevance and not weak_vector_match) else 0.0

        original_score = (
            vector_score
            + score_data["total_boost"]
            + novelty_score
            + on_time_bonus
            + gated_price_affinity
        )

        # ---- New quiz-signal scoring (additive) ----------------------
        # Only runs when a RecommendRequest is available.
        # Scaled by 30 to be meaningful relative to the original score
        # range (typically 0–200). At max this adds ~45 points (~15%).
        quiz_signal_score = 0.0
        if request is not None:
            quiz_signal_score = compute_quiz_signal_score(
                g, request, conf_multipliers
            ) * 30

        final_score = original_score + quiz_signal_score

        # ---- Confidence and reasons ----------------------------------
        confidence_val = compute_confidence(vec_sim, score_data["intent_match_count"])

        reasons = []
        if score_data["matched_intent"]:
            reasons.append(f"Matches: {', '.join(score_data['matched_intent'][:2])}")
        if score_data["broad_interest_matches"]:
            reasons.append("Matches your interests")
        if delivery_status == "on_time":
            reasons.append("Fast shipping")

        g.update({
            "score":            final_score,
            "confidence":       round(confidence_val, 2),
            "ranking_reasons":  reasons if reasons else ["Highly rated match"],
            "delivery_status":  delivery_status,
            "already_purchased":score_data.get("already_purchased", False),
            "missed_intent":    score_data.get("missed_intent", False),
        })
        scored.append(g)

    # ---- Diversity logic (original — preserved intact) ---------------
    scored.sort(key=lambda x: x["score"], reverse=True)
    category_counter = defaultdict(int)
    for gift in scored:
        cats = gift.get("gift_type") or gift.get("categories") or []
        for cat in cats:
            if category_counter[cat] >= MAX_CATEGORY_DOMINANCE:
                gift["score"] -= DIVERSITY_PENALTY
                break
            category_counter[cat] += 1

    # Final sort and trim
    scored.sort(key=lambda x: x["score"], reverse=True)
    final_results = scored[:k]
    final_results = assign_ranked_confidence(final_results)

    logger.info(f"Final selection: {[f.get('display_name') for f in final_results]}")
    return final_results