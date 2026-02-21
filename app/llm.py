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
    Uses JSON mode for reliability and enforces strict adherence to retrieval order.
    """

    # Safety check: handle empty or None gifts
    if not gifts:
        logger.warning("No gifts provided to generate_gift_response")
        return {
            "intro": "I couldn't find any perfect matches. Try adjusting your search!",
            "gifts": []
        }, 0

    # ---------- Preference context ----------
    pref_text = "None provided"
    if preferences:
        interests = preferences.get('interests', [])
        vibes = preferences.get('vibe', [])
        pref_text = "Interests: " + str(interests) + ", Vibe: " + str(vibes)

    # ---------- Gift context for LLM ----------
    gift_context = ""
    for i, gift in enumerate(gifts, 1):
        # We pass the 'breakdown' info so the LLM knows WHY it was picked
        reasons = ", ".join(gift.get('ranking_reasons', []))
        name = gift.get('name', '')
        conf = gift.get('confidence', 0) * 100
        desc = gift.get('description', '')[:250]

        gift_context += """
Gift #%d:
Name: %s
Confidence: %.0f%%
Key Features: %s
Description: %s
---
""" % (i, name, conf, reasons, desc)

    # SYSTEM PROMPT: Focused on honesty and rank preservation
    system_prompt = """
You are an expert personal shopper. Use the user's query and profile to explain recommendations.

USER PROFILE: %s

STRICT RULES:
1. EXPLAIN items in the EXACT numerical order provided.
2. If an item has low confidence (e.g., < 70%%), acknowledge it might be a creative alternative.
3. If an item has high confidence, highlight the specific keyword or interest match.
4. Keep explanations to 1-2 punchy, persuasive sentences.
5. You must respond in valid JSON format.
""" % pref_text

    user_prompt = """
User query: "%s"

JSON Structure:
{
  "intro": "A warm 1-sentence opening",
  "gifts": [
    {
      "name": "Exact name from list",
      "reason": "Your personalized explanation"
    }
  ]
}

Gifts to process:
%s
""" % (query, gift_context)

    try:
        # Use response_format={"type": "json_object"} for GPT-4o-mini
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2  # Lower for even more precision
        )

        tokens_used = response.usage.total_tokens if response.usage else 0
        content = response.choices[0].message.content

        # Strip markdown code fences if present
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(content)

    except Exception as e:
        logger.error("LLM Generation or Parsing failed: " + str(e))
        import traceback
        logger.error(traceback.format_exc())
        parsed = {"intro": "Here are some gifts I found for you:", "gifts": []}
        tokens_used = 0

    # ---------- Re-sync with Retrieval Order (The Fail-Safe) ----------
    enriched = []
    llm_results = {}

    for g in parsed.get("gifts", []):
        name = g.get("name", "").lower()
        reason = g.get("reason", "")
        llm_results[name] = reason

    for original in gifts:
        # Fallback if LLM missed an item or renamed it
        reason = llm_results.get(original["name"].lower())

        if not reason:
            # Generate a fallback reason
            interests = original.get('interests', [])[:2]
            if interests:
                reason = "A great choice that aligns with your interest in " + ", ".join(interests) + "."
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
            "reason": reason
        })

    intro = parsed.get("intro", "Here are some great gifts for you:")

    logger.info("Generated response with %d gifts" % len(enriched))

    return {"intro": intro, "gifts": enriched}, tokens_used