from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Optional
import json
import logging

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)


def generate_gift_response(
        query: str,
        gifts: List[Dict],
        preferences: Optional[Dict] = None
) -> tuple[Dict, int]:
    """
    Generates a natural language explanation of gift recommendations.
    CRITICAL: Preserves the exact order from retrieval.

    Returns:
        Tuple of (response_data, tokens_used)
    """

    # ---------- Preference context ----------

    if preferences:
        pref_text = f"""
User preferences (if any):
- Interests: {preferences.get("interests", [])}
- Vibe: {preferences.get("vibe", [])}
"""
    else:
        pref_text = "User did not provide explicit preferences."

    # ---------- Gift context for LLM ----------
    # Number the gifts so LLM knows their rank order

    gift_context = ""
    for i, gift in enumerate(gifts, 1):
        gift_context += f"""
Gift #{i} (Rank {i}):
Name: {gift['name']}
Price: ${gift['price']}
Confidence: {gift['confidence']}
Ranking reasons: {', '.join(gift.get('ranking_reasons', [])) or 'Matches your search'}
Description: {gift.get('description', '')[:200]}...
---
"""

    system_prompt = f"""
You are a thoughtful gift recommendation assistant.

{pref_text}

CRITICAL RULES:
- Gifts are already ranked by relevance (Gift #1 is BEST match)
- You MUST explain gifts in the EXACT order provided
- Do NOT reorder or skip gifts
- Do NOT invent facts or preferences
- Keep explanations concise (1-2 sentences per gift)
"""

    user_prompt = f"""
User query: "{query}"

Return STRICT JSON with gifts in the EXACT same order:

{{
  "intro": "one brief sentence introducing the recommendations",
  "gifts": [
    {{
      "name": "exact gift name from list",
      "reason": "1-2 sentence explanation of why this gift matches the query"
    }}
  ]
}}

Gifts (ALREADY RANKED - explain in this order):
{gift_context}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3  # Lower temperature for more consistent ordering
    )

    # Extract token usage from response
    tokens_used = response.usage.total_tokens if response.usage else 0

    content = response.choices[0].message.content

    try:
        # Strip markdown code fences if present
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(content)
    except Exception as e:
        logger.error(f"Failed to parse LLM response: {e}")
        parsed = {"intro": "", "gifts": []}

    # ---------- CRITICAL: Preserve retrieval order ----------
    # Do NOT use LLM's order - use the original gifts order

    enriched = []

    for original in gifts:
        # Find the matching LLM explanation (if any)
        llm_match = next(
            (g for g in parsed.get("gifts", [])
             if g.get("name", "").lower() == original["name"].lower()),
            None
        )

        # Build enriched gift preserving ALL fields
        enriched_gift = {
            "name": original["name"],
            "price": original["price"],
            "confidence": original.get("confidence", 0),
            "description": original.get("description", ""),
            "image_url": original.get("image_url", ""),
            "product_url": original.get("link", ""),  # Map 'link' to 'product_url'
            "ranking_reasons": original.get("ranking_reasons", []),
            "reason": llm_match.get("reason") if llm_match else
            f"This gift matches your search for {query}.",
        }

        enriched.append(enriched_gift)

        logger.debug(f"Gift #{len(enriched)}: {original['name']} (conf: {original.get('confidence')})")

    response_data = {
        "intro": parsed.get(
            "intro",
            f"Here are some thoughtful gifts for your search:"
        ),
        "gifts": enriched
    }

    logger.info(f"Returning {len(enriched)} gifts in retrieval order")

    return response_data, tokens_used