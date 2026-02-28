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
    """
    Generates personalized gift recommendations.
    Partner name injection happens HERE (not in retrieval).
    """

    if not gifts:
        recipient = partner_context.get("name") if partner_context else "them"
        return {
            "intro": "I couldn't find any perfect matches for %s. Try adjusting your search!" % recipient,
            "gifts": []
        }, 0

    # Build preference context
    if preferences:
        interests = preferences.get('interests', [])
        vibes = preferences.get('vibe', [])
        pref_text = "Session Interests: " + str(interests) + ", Vibe: " + str(vibes)
    else:
        pref_text = "None provided"

    # Build RICH partner context
    if partner_context:
        name = partner_context.get("name", "your recipient")
        partner_interests = partner_context.get("interests", [])
        partner_vibe = partner_context.get("vibe", [])
        partner_personality = partner_context.get("personality", [])

        partner_summary = """
Partner Profile:
- Name: %s
- Loves: %s
- Vibe: %s
- Personality: %s
""" % (
            name,
            ", ".join(partner_interests[:5]) if partner_interests else "Not specified",
            ", ".join(partner_vibe[:3]) if partner_vibe else "Not specified",
            ", ".join(partner_personality[:3]) if partner_personality else "Not specified"
        )
        recipient = name
    else:
        partner_summary = "No partner profile available"
        recipient = "your recipient"

    # Build gift context
    gift_context = ""
    for i, gift in enumerate(gifts, 1):
        reasons = ", ".join(gift.get('ranking_reasons', []))
        name_str = gift.get('name', '')
        conf = gift.get('confidence', 0) * 100
        desc = gift.get('description', '')[:250]
        already_purchased = gift.get('already_purchased', False)

        gift_context += """
Gift #%d:%s
Name: %s
Confidence: %.0f%%
Key Features: %s
Description: %s
---
""" % (i, " [ALREADY PURCHASED - Note this]" if already_purchased else "", name_str, conf, reasons, desc)

    system_prompt = """
You are an expert personal shopper helping find the perfect gift for %s.

%s

SESSION CONTEXT: %s

STRICT RULES:
1. Use %s's name naturally and warmly in your explanations
2. Reference their specific interests/personality when relevant
3. Explain gifts in the EXACT order provided
4. Keep explanations personal and concise (1-2 sentences)
5. If a gift was already purchased, note "You've gotten them this before - maybe try something new?"
6. You must respond in valid JSON format
""" % (recipient, partner_summary, pref_text, recipient)

    user_prompt = """
User query: "%s"

JSON Structure:
{
  "intro": "A warm 1-sentence opening mentioning %s by name and their interests",
  "gifts": [
    {
      "name": "exact gift name",
      "reason": "personalized explanation using %s's name and profile"
    }
  ]
}

Gifts (ALREADY RANKED):
%s
""" % (query, recipient, recipient, gift_context)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )

        tokens_used = response.usage.total_tokens if response.usage else 0
        content = response.choices[0].message.content

        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(content)

    except Exception as e:
        logger.error("LLM Generation or Parsing failed: %s" % str(e))
        import traceback
        logger.error(traceback.format_exc())
        parsed = {"intro": "Here are some gifts I found for %s:" % recipient, "gifts": []}
        tokens_used = 0

    # Re-sync with retrieval order
    enriched = []
    llm_results = {}

    for g in parsed.get("gifts", []):
        name = g.get("name", "").lower()
        reason = g.get("reason", "")
        llm_results[name] = reason

    for original in gifts:
        reason = llm_results.get(original["name"].lower())

        if not reason:
            interests = original.get('interests', [])[:2]
            if interests:
                reason = "A great choice that aligns with their interest in " + ", ".join(interests) + "."
            else:
                reason = "A thoughtful gift that matches your search criteria."

        enriched.append({
            "name": original["name"],
            "price": original["price"],
            "confidence": original.get("confidence", 0),
            "description": original.get("description", ""),
            "image_url": original.get("image_url", ""),
            "product_url": original.get("link", "") or original.get("product_url", ""),
            "ranking_reasons": original.get("ranking_reasons", []),
            "reason": reason,
            "already_purchased": original.get("already_purchased", False),
            "shipping_min_days": original.get("shipping_min_days"),
            "shipping_max_days": original.get("shipping_max_days"),
            "is_prime_eligible": original.get("is_prime_eligible"),
        })

    intro = parsed.get("intro", "Here are some great gifts for %s:" % recipient)

    logger.info("Generated response with %d gifts for %s" % (len(enriched), recipient))

    return {"intro": intro, "gifts": enriched}, tokens_used