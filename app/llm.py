# app/llm.py

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
        preferences: Optional[Dict] = None,
        partner_context: Optional[Dict] = None
) -> tuple[Dict, int]:

    if not gifts:
        recipient = partner_context.get("name") if partner_context else "them"
        return {
            "intro": f"I couldn't find any perfect matches for {recipient}. Try adjusting your search!",
            "gifts": []
        }, 0

    # ----------------------------
    # Build preference context
    # ----------------------------
    interests = preferences.get("interests", []) if preferences else []
    vibe = preferences.get("vibe", []) if preferences else []
    occasion = preferences.get("occasion", "a special occasion") if preferences else "a special occasion"
    relationship_stage = preferences.get("relationship_stage", "your relationship") if preferences else "your relationship"

    pref_text = f"""
Session Context:
- Occasion: {occasion}
- Relationship Stage: {relationship_stage}
- Interests Mentioned: {", ".join(interests) if interests else "None"}
- Desired Vibe: {", ".join(vibe) if vibe else "Not specified"}
"""

    # ----------------------------
    # Partner context
    # ----------------------------
    if partner_context:
        name = partner_context.get("name", "your partner")
        partner_interests = partner_context.get("interests", [])
        partner_vibe = partner_context.get("vibe", [])
        partner_personality = partner_context.get("personality", [])
    else:
        name = "your partner"
        partner_interests = []
        partner_vibe = []
        partner_personality = []

    partner_summary = f"""
Partner Profile:
- Name: {name}
- Core Interests: {", ".join(partner_interests[:5]) if partner_interests else "Not specified"}
- Vibe: {", ".join(partner_vibe[:3]) if partner_vibe else "Not specified"}
- Personality: {", ".join(partner_personality[:3]) if partner_personality else "Not specified"}
"""

    # ----------------------------
    # Gift context
    # ----------------------------
    gift_context = ""
    for i, gift in enumerate(gifts, 1):
        gift_context += f"""
Gift #{i}:
Name: {gift.get('name')}
Confidence Score: {round(gift.get('confidence', 0) * 100)}%
Key Features: {", ".join(gift.get('ranking_reasons', []))}
Description: {gift.get('description', '')[:250]}
Already Purchased: {gift.get('already_purchased', False)}
---
"""

    # ----------------------------
    # System prompt
    # ----------------------------
    system_prompt = f"""
You are an emotionally intelligent personal gift strategist.

Your job is to:
- Reduce anxiety about gift-giving
- Reassure the buyer
- Make the recommendation feel personal and thoughtful
- Explain WHY this gift works for {name}
- Reference the occasion AND relationship stage naturally

STRICT RULES:
1. ALWAYS use {name}'s name in each gift explanation.
2. Mention either the occasion OR relationship stage in each explanation.
3. Keep each explanation 2-3 sentences.
4. Sound confident and reassuring.
5. If already purchased = true, mention that they've bought it before.
6. Output valid JSON only.
"""

    user_prompt = f"""
User Query: "{query}"

{pref_text}

{partner_summary}

Return JSON in this format:

{{
  "intro": "1 warm sentence reassuring the buyer and mentioning {name}",
  "gifts": [
    {{
      "name": "exact gift name",
      "reason": "2-3 sentence personalized emotional explanation"
    }}
  ]
}}

Gifts (ranked highest to lowest):
{gift_context}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.4
        )

        tokens_used = response.usage.total_tokens if response.usage else 0
        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(content)

    except Exception as e:
        logger.error("LLM failed: %s", str(e))
        parsed = {
            "intro": f"Here are some thoughtful gift ideas for {name}.",
            "gifts": []
        }
        tokens_used = 0

    # ----------------------------
    # Merge LLM results back to original gifts
    # ----------------------------
    llm_map = {g["name"].lower(): g["reason"] for g in parsed.get("gifts", [])}

    enriched = []

    for original in gifts:
        gift_name_lower = original["name"].lower()
        reason = llm_map.get(gift_name_lower)

        # Stronger fallback (never generic)
        if not reason:
            fallback_interest = original.get("interests", [])[:1]
            interest_text = fallback_interest[0] if fallback_interest else "what she enjoys"

            reason = (
                f"Since this is for {occasion}, this feels meaningful without being over-the-top. "
                f"{name} appreciates {interest_text}, so this shows you pay attention — and it fits naturally into your {relationship_stage}."
            )

        enriched.append({
            "name": original["name"],
            "price": original["price"],
            "confidence": original.get("confidence", 0),
            "description": original.get("description", ""),
            "image_url": original.get("image_url", ""),
            "product_url": original.get("link") or original.get("product_url"),
            "ranking_reasons": original.get("ranking_reasons", []),
            "reason": reason,
            "already_purchased": original.get("already_purchased", False),
            "shipping_min_days": original.get("shipping_min_days"),
            "shipping_max_days": original.get("shipping_max_days"),
            "is_prime_eligible": original.get("is_prime_eligible"),
        })

    intro = parsed.get("intro", f"Here are some great options for {name}.")

    logger.info("Generated personalized response for %s", name)

    return {"intro": intro, "gifts": enriched}, tokens_used