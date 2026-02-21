# app/embeddings.py

from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict
import logging
import json

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding for a piece of text using OpenAI.
    Returns a 1536-dimensional vector.
    """
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error("Error generating embedding: " + str(e))
        return None


def normalize_jsonb_field(value) -> List[str]:
    """Convert JSONB field to list of strings"""
    if value is None:
        return []

    # If it's already a list
    if isinstance(value, list):
        return [str(item) for item in value]

    # If it's a string (JSON string), parse it
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            return [str(parsed)]
        except:
            return [value]

    # If it's some other type, convert to string
    return [str(value)]


def create_gift_text_for_embedding(gift: Dict) -> str:
    """
    Create a rich text representation of a gift for embedding.
    This is what gets converted to a vector.
    """
    parts = []

    # Name (most important)
    if gift.get("name"):
        parts.append(gift["name"])

    # Description
    if gift.get("description"):
        # Truncate to first 500 chars to save tokens
        parts.append(gift["description"][:500])

    # Interests (very important for matching)
    interests = normalize_jsonb_field(gift.get("interests"))
    if interests:
        parts.append("Interests: " + ", ".join(interests))

    # Categories
    categories = normalize_jsonb_field(gift.get("categories"))
    if categories:
        parts.append("Categories: " + ", ".join(categories))

    # Occasions
    occasions = normalize_jsonb_field(gift.get("occasions"))
    if occasions:
        parts.append("Occasions: " + ", ".join(occasions))

    # Vibe
    vibe = normalize_jsonb_field(gift.get("vibe"))
    if vibe:
        parts.append("Vibe: " + ", ".join(vibe))

    # Combine everything
    result = " | ".join(parts)
    logger.debug("Created embedding text: " + result[:100] + "...")
    return result


def update_gift_embedding(gift_id: str, embedding: List[float]):
    """
    Update a gift's embedding in Supabase.
    """
    from app.retrieval import get_supabase_client

    try:
        supabase = get_supabase_client()

        # Convert list to format Supabase expects
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