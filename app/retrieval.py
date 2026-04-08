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

_supabase_client = None

# --------------------------------------------------
# CONFIG (UPDATED)
# --------------------------------------------------

GENERIC_TOKENS = {
    "gift", "present", "birthday", "anniversary", "christmas", "valentines",
    "girlfriend", "boyfriend", "wife", "husband", "partner", "spouse",
    "friend", "family", "mom", "dad", "sister", "brother",
    "for", "her", "him", "them", "woman", "man", "person",
    "who", "loves", "likes", "enjoys", "into",
    "named", "called",

    # 🔥 new
    "cozy", "warm", "comfortable", "home",
    "luxury", "premium", "high", "end",
    "indulgent", "range", "mid"
}

VECTOR_MATCH_THRESHOLD = 0.30
VECTOR_WEIGHT = 35   # ↓ reduced
INTENT_WEIGHT = 40
SESSION_WEIGHT = 80  # ↑ increased
PROFILE_WEIGHT = 3
DIVERSITY_PENALTY = 20
NOVELTY_BOOST = 10
MAX_CATEGORY_DOMINANCE = 3
PRICE_AFFINITY_MAX_BONUS = 25

MIN_VECTOR_SCORE_FOR_FULL_SCORING = 0.35
CONFIDENT_INTEREST_MISMATCH_PENALTY = -80

NICHE_INTEREST_TAGS: Set[str] = {"pets"}

CONFIDENCE_MULTIPLIERS = {
    "confident": {"interest": 1.4, "vibe": 0.8, "overlap": 1.5},
    "somewhat":  {"interest": 1.0, "vibe": 1.0, "overlap": 1.2},
    "lost":      {"interest": 0.0, "vibe": 1.3, "overlap": 0.0},
}

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def get_supabase_client():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        _supabase_client = create_client(url, key)
    return _supabase_client


def tokenize(text: str) -> Set[str]:
    if not text:
        return set()
    tokens = re.split(r"\W+", text.lower())
    return {t for t in tokens if len(t) > 2}


def extract_meaningful_intent_tokens(query: str) -> Set[str]:
    tokens = tokenize(query)
    meaningful = tokens - GENERIC_TOKENS
    meaningful = {t for t in meaningful if len(t) > 3}
    return meaningful


def normalize_jsonb_to_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).lower() for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).lower() for v in parsed]
        except:
            return [v.strip().lower() for v in value.split(",")]
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
    meaningful_tokens: Set[str],
    preferences: Dict,
    confidence_level: str,
    request_interests: Optional[List[str]]
):
    g_interests = gift.get("interests") or []
    text = (gift.get("name","") + " " + gift.get("description","")).lower()

    matched = [t for t in meaningful_tokens if t in text]
    intent_score = len(matched) * INTENT_WEIGHT

    user_interests = preferences.get("interests", [])
    interest_overlap = set(g_interests) & set(user_interests)
    session_score = len(interest_overlap) * SESSION_WEIGHT

    # 🔥 strong boost
    exact_boost = 50 if interest_overlap else 0

    # 🔥 confident penalty
    mismatch_penalty = 0
    if confidence_level == "confident" and request_interests:
        if not interest_overlap:
            mismatch_penalty = CONFIDENT_INTEREST_MISMATCH_PENALTY

    total = intent_score + session_score + exact_boost + mismatch_penalty

    return {
        "score": total,
        "interest_overlap": interest_overlap
    }

# --------------------------------------------------
# MAIN
# --------------------------------------------------

def retrieve_gifts(
    query: str,
    k: int = 10,
    preferences: Optional[Dict] = None,
    request: Optional[RecommendRequest] = None
) -> List[Dict]:

    preferences = normalize_preferences(preferences)
    meaningful_tokens = extract_meaningful_intent_tokens(query)

    confidence_level = getattr(request, "confidence", "somewhat") if request else "somewhat"
    request_interests = list(request.interests or []) if request else []

    try:
        supabase = get_supabase_client()
        embedding = generate_embedding(query)

        response = supabase.rpc(
            "match_gifts",
            {
                "query_embedding": embedding,
                "match_threshold": VECTOR_MATCH_THRESHOLD,
                "match_count": 80,
            }
        ).execute()

        raw = response.data or []

    except Exception as e:
        logger.error(e)
        return []

    scored = []

    for g in raw:
        g["interests"] = normalize_jsonb_to_list(g.get("interests"))

        # 🔥 HARD FILTER
        if confidence_level == "confident" and request_interests:
            if not set(g["interests"]) & set(request_interests):
                continue

        vec_sim = float(g.get("similarity") or 0)
        vector_score = vec_sim * VECTOR_WEIGHT

        score_data = compute_enhanced_score(
            g,
            meaningful_tokens,
            preferences,
            confidence_level,
            request_interests
        )

        final_score = vector_score + score_data["score"]

        g["score"] = final_score
        scored.append(g)

    # 🔥 FINAL SAFETY FILTER
    if confidence_level == "confident" and request_interests:
        scored = [
            g for g in scored
            if set(g["interests"]) & set(request_interests)
        ]

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]