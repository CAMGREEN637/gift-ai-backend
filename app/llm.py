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


def generate_display_name(product_name: str, description: str = "") -> str:
    """
    Generate a clean, short display name from Amazon's SEO-filled product name
    """
    prompt = f"""You are a product naming expert. Convert this Amazon product name into a clean, retail-ready display name.

Amazon Product Name: {product_name}

Rules:
1. Maximum 6 words
2. Keep the core product type and key feature
3. Remove SEO filler, marketing hype, and brand names (unless it's a well-known brand like Apple, Nike, etc.)
4. Keep important specs (size, capacity, material) if relevant
5. Make it sound natural, not robotic
6. Capitalize like a proper product title

Examples:
- "Insulated Stainless Steel Water Bottle, 32oz, Leak Proof, BPA Free, Hot & Cold, Double Wall Vacuum..." → "32oz Insulated Water Bottle"
- "Premium Wireless Bluetooth Headphones with Noise Cancelling, 30 Hour Battery, Comfortable Over-Ear..." → "Noise Cancelling Wireless Headphones"
- "Personalized Custom Engraved Photo Frame, Wooden Picture Frame, Holds 4x6 Photos, Perfect Gift..." → "Personalized Wooden Photo Frame"

Return ONLY the clean display name, nothing else."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=20
        )

        display_name = response.choices[0].message.content.strip()
        display_name = display_name.strip('"').strip("'")

        words = display_name.split()
        if len(words) > 6:
            display_name = " ".join(words[:6])

        logger.info(f"✅ Generated display name: '{display_name}'")
        return display_name

    except Exception as e:
        logger.error(f"❌ Error generating display name: {e}")
        words = product_name.split()[:6]
        return " ".join(words)


def _fuzzy_match_reason(orig_name: str, llm_gifts: List[Dict]) -> Optional[str]:
    """
    Match a gift's original name to the closest LLM response entry.

    Strategy (in order of preference):
      1. Exact lowercase match
      2. LLM name is a substring of original name (or vice versa)
      3. Most shared words (token overlap) — picks the best scoring entry
    Returns None if no reasonable match is found.
    """
    if not llm_gifts:
        return None

    orig_lower = orig_name.lower()
    orig_tokens = set(orig_lower.split())

    # 1. Exact match
    for g in llm_gifts:
        if g.get("name", "").lower() == orig_lower:
            return g.get("reason")

    # 2. Substring match
    for g in llm_gifts:
        llm_name = g.get("name", "").lower()
        if llm_name and (llm_name in orig_lower or orig_lower in llm_name):
            return g.get("reason")

    # 3. Best token overlap
    best_reason = None
    best_score = 0
    for g in llm_gifts:
        llm_tokens = set(g.get("name", "").lower().split())
        shared = len(orig_tokens & llm_tokens)
        # Require at least 2 shared words to avoid false positives
        if shared > best_score and shared >= 2:
            best_score = shared
            best_reason = g.get("reason")

    return best_reason


def generate_gift_response(
        query: str,
        gifts: List[Dict],
        preferences: Optional[Dict] = None,
        partner_context: Optional[Dict] = None,
        session_context: Optional[Dict] = None
) -> tuple[Dict, int]:
    """
    Generates personalized gift recommendations with rich, non-repetitive context.
    """

    if not gifts:
        recipient = partner_context.get("name") if partner_context else "them"
        return {
            "intro": "I couldn't find any perfect matches for %s. Try adjusting your search!" % recipient,
            "gifts": []
        }, 0

    recipient_name = partner_context.get("name") if partner_context else None
    partner_interests = partner_context.get("interests", []) if partner_context else []
    partner_vibe = partner_context.get("vibe", []) if partner_context else []
    partner_personality = partner_context.get("personality", []) if partner_context else []

    relationship = session_context.get("relationship") if session_context else None
    occasion = session_context.get("occasion") if session_context else None
    budget = session_context.get("budget") if session_context else None

    if recipient_name:
        recipient_display = recipient_name
    else:
        recipient_display = "your %s" % relationship if relationship else "them"

    context_text = """
RECIPIENT: %s
RELATIONSHIP: %s
OCCASION: %s
BUDGET: %s

RECIPIENT PROFILE:
- Interests: %s
- Style/Vibe: %s
- Personality: %s
""" % (
        recipient_name or "Not specified",
        relationship or "Not specified",
        occasion or "General gift",
        "$%s" % budget if budget else "Flexible",
        ", ".join(partner_interests[:5]) if partner_interests else "Not specified",
        ", ".join(partner_vibe[:3]) if partner_vibe else "Not specified",
        ", ".join(partner_personality[:3]) if partner_personality else "Not specified"
    )

    gift_context = ""
    for i, gift in enumerate(gifts, 1):
        reasons = ", ".join(gift.get('ranking_reasons', []))
        name = gift.get('name', '')
        conf = gift.get('confidence', 0) * 100
        desc = gift.get('description', '')[:200]
        price = gift.get('price', 0)

        gift_context += """
GIFT #%d:
Name: %s
Price: $%.2f
Confidence: %.0f%%
Why It Ranked High: %s
Description: %s
---
""" % (i, name, price, conf, reasons, desc)

    system_prompt = """
You are an expert gift consultant helping someone choose a meaningful gift for %s.
%s
RULES:
1. UNIQUENESS IS MANDATORY: Each explanation must be completely different. Never reuse phrases across gifts.
2. USE THE RECIPIENT'S NAME: Always mention "%s" in every reason.
3. Be specific to each product — reference its actual features, not generic praise.
4. OUTPUT FORMAT: Valid JSON only. Use the exact gift name from the list in your response.
""" % (recipient_display, context_text, recipient_name or "the recipient")

    user_prompt = """
User's search: "%s"

Return a JSON object in this exact format:
{
  "intro": "One warm, natural sentence mentioning the recipient and the occasion",
  "gifts": [
    {
      "name": "use the EXACT gift name from the list below",
      "reason": "Unique 2-3 sentence explanation referencing the specific product and recipient"
    }
  ]
}

You MUST include a reason for every gift in the list. Use the exact name as given.

Gifts:
%s
""" % (query, gift_context)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )

        tokens_used = response.usage.total_tokens if response.usage else 0
        content = response.choices[0].message.content.strip()
        parsed = json.loads(content)
        logger.info(f"LLM returned reasons for {len(parsed.get('gifts', []))} gifts")

    except Exception as e:
        logger.error("LLM Generation failed: %s" % str(e))
        parsed = {"intro": "Here are some gifts for %s:" % recipient_display, "gifts": []}
        tokens_used = 0

    llm_gifts = parsed.get("gifts", [])

    enriched = []
    for idx, original in enumerate(gifts):
        orig_name = original.get("name", "")

        # Use fuzzy matching so shortened/paraphrased LLM names still resolve correctly
        reason = _fuzzy_match_reason(orig_name, llm_gifts)

        if not reason:
            logger.warning(f"No LLM reason matched for gift: '{orig_name}'")
            reason = "A highly relevant pick based on their interests and your search."

        # Ensure we have a clean display name for the frontend
        display_name = original.get("display_name")
        if not display_name:
            display_name = generate_display_name(orig_name, original.get("description", ""))

        enriched.append({
            "name": orig_name,
            "display_name": display_name,
            "price": original.get("price", 0),
            "confidence": original.get("confidence", 0),
            "description": original.get("description", ""),
            "image_url": original.get("image_url", ""),
            "product_url": original.get("product_url", "") or original.get("link", ""),
            "reason": reason,
            "ranking_reasons": original.get("ranking_reasons", []),
            "already_purchased": original.get("already_purchased", False),
            "shipping_min_days": original.get("shipping_min_days"),
            "shipping_max_days": original.get("shipping_max_days"),
            "is_prime_eligible": original.get("is_prime_eligible"),
        })

    return {"intro": parsed.get("intro", ""), "gifts": enriched}, tokens_used