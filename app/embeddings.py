# app/embeddings.py

from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict
import logging
import json
from functools import lru_cache

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)


@lru_cache(maxsize=500)
def _embedding_cache(text: str) -> tuple:
    """Internal cached embedding call — returns tuple so lru_cache can store it."""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return tuple(response.data[0].embedding)


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding for a piece of text using OpenAI.
    Returns a 1536-dimensional vector.
    Results are cached by normalized query text (saves 200-500ms on repeated queries).
    """
    try:
        # Normalize before caching so minor variations (case, whitespace) share cache entries
        normalized = " ".join(text.lower().split())[:500]
        info_before = _embedding_cache.cache_info()
        result = _embedding_cache(normalized)
        info_after = _embedding_cache.cache_info()
        if info_after.hits > info_before.hits:
            logger.info("Embedding cache HIT  (size=%d/%d) query=%.60s", info_after.currsize, 500, normalized)
        else:
            logger.info("Embedding cache MISS (size=%d/%d) query=%.60s", info_after.currsize, 500, normalized)
        return list(result)
    except Exception as e:
        logger.error("Error generating embedding: " + str(e))
        return None


def normalize_jsonb_field(value) -> List[str]:
    """Convert JSONB field to list of strings."""
    if value is None:
        return []

    if isinstance(value, list):
        return [str(item) for item in value]

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            return [str(parsed)]
        except:
            return [value]

    return [str(value)]


def create_gift_text_for_embedding(gift: Dict) -> str:
    """
    Create a rich text representation of a gift for embedding.
    This is what gets converted to a vector and stored in Supabase.

    FIX (v2): reads gift_type (not categories) since that is the actual
    column name in Supabase. The old version used gift.get("categories")
    which always returned empty, silently dropping the gift-type dimension
    from every embedding in the catalog.
    """
    parts = []

    # Name (most important — anchors the semantic space)
    if gift.get("name"):
        parts.append(gift["name"])

    # Description (truncated to save tokens)
    if gift.get("description"):
        parts.append(gift["description"][:500])

    # Interests (critical for confident-mode interest matching)
    interests = normalize_jsonb_field(gift.get("interests"))
    if interests:
        parts.append("Interests: " + ", ".join(interests))

    # Gift type — FIX: was gift.get("categories") which doesn't exist in Supabase.
    # Fall back to "categories" only for legacy callers that pre-normalize the field.
    gift_type = normalize_jsonb_field(gift.get("gift_type") or gift.get("categories"))
    if gift_type:
        parts.append("Categories: " + ", ".join(gift_type))

    # Occasions (helps vector search surface occasion-appropriate gifts)
    occasions = normalize_jsonb_field(gift.get("occasions"))
    if occasions:
        parts.append("Occasions: " + ", ".join(occasions))

    # Vibe (drives vibe-match scoring in compute_quiz_signal_score)
    vibe = normalize_jsonb_field(gift.get("vibe"))
    if vibe:
        parts.append("Vibe: " + ", ".join(vibe))

    result = " | ".join(parts)
    logger.debug("Created embedding text: " + result[:100] + "...")
    return result


def update_gift_embedding(gift_id: str, embedding: List[float]) -> bool:
    """
    Update a gift's embedding in Supabase.
    """
    from app.retrieval import get_supabase_client

    try:
        supabase = get_supabase_client()
        response = supabase.table('gifts').update({
            'embedding': embedding
        }).eq('id', gift_id).execute()

        logger.debug("Update response for " + gift_id + ": " + str(len(response.data)) + " rows")
        return True
    except Exception as e:
        logger.error("Error updating embedding for gift " + gift_id + ": " + str(e))
        import traceback
        logger.error(traceback.format_exc())
        return False