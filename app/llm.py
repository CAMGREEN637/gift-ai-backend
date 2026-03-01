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
        partner_context: Optional[Dict] = None,
        session_context: Optional[Dict] = None
) -> tuple[Dict, int]:
    """
    Generates personalized gift recommendations with rich, non-repetitive context.
    Each explanation must be genuinely unique - no template filling.
    """

    if not gifts:
        recipient = partner_context.get("name") if partner_context else "them"
        return {
            "intro": "I couldn't find any perfect matches for %s. Try adjusting your search!" % recipient,
            "gifts": []
        }, 0

    # Extract rich context
    recipient_name = partner_context.get("name") if partner_context else None
    partner_interests = partner_context.get("interests", []) if partner_context else []
    partner_vibe = partner_context.get("vibe", []) if partner_context else []
    partner_personality = partner_context.get("personality", []) if partner_context else []

    # Session context
    relationship = session_context.get("relationship") if session_context else None
    occasion = session_context.get("occasion") if session_context else None
    budget = session_context.get("budget") if session_context else None

    # Build recipient display name
    if recipient_name:
        recipient_display = recipient_name
        possessive = "%s's" % recipient_name
    else:
        recipient_display = "your %s" % relationship if relationship else "them"
        possessive = "their"

    # Build comprehensive context text
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

    # Build detailed gift context
    gift_context = ""
    for i, gift in enumerate(gifts, 1):
        reasons = ", ".join(gift.get('ranking_reasons', []))
        name = gift.get('name', '')
        conf = gift.get('confidence', 0) * 100
        desc = gift.get('description', '')[:200]
        already_purchased = gift.get('already_purchased', False)
        interests_match = gift.get('interests', [])
        categories = gift.get('categories', [])
        price = gift.get('price', 0)

        gift_context += """
GIFT #%d:%s
Name: %s
Price: $%.2f
Confidence: %.0f%%
Categories: %s
Matches These Interests: %s
Why It Ranked High: %s
Description: %s
---
""" % (
            i,
            " [PREVIOUSLY PURCHASED]" if already_purchased else "",
            name,
            price,
            conf,
            ", ".join(categories[:3]) if categories else "general",
            ", ".join(interests_match[:3]) if interests_match else "broad appeal",
            reasons,
            desc
        )

    # Enhanced system prompt emphasizing uniqueness
    system_prompt = """
You are an expert gift consultant helping someone choose a meaningful gift for %s.

%s

CRITICAL INSTRUCTIONS FOR WRITING EXPLANATIONS:

1. UNIQUENESS IS MANDATORY
   - Each gift explanation must be COMPLETELY DIFFERENT from the others
   - Never use the same sentence structure twice
   - Vary your approach: sometimes focus on the occasion, sometimes the relationship, sometimes the specific feature of the gift
   - Use different vocabulary and phrasing for each explanation

2. USE THE RECIPIENT'S NAME
   - Always use "%s" (or "%s" when possessive) in EVERY explanation
   - Never say "them" or "the recipient"

3. CONNECT TO CONTEXT
   - Weave in the occasion (%s) naturally - but do it differently each time
   - Reference the relationship (%s) meaningfully - with variety
   - Connect to specific interests when relevant - but change how you frame it

4. VARY YOUR ANGLES
   For different gifts, try different approaches:
   - Gift 1: Focus on emotional impact
   - Gift 2: Focus on practical use
   - Gift 3: Focus on shared memories or experiences
   - Gift 4: Focus on quality/craftsmanship
   - Gift 5: Focus on surprise factor or uniqueness

5. BE SPECIFIC TO THE ACTUAL GIFT
   - Don't just say "this matches their interests"
   - Explain HOW and WHY this specific item works
   - Reference actual features or benefits from the description

6. TONE GUIDELINES
   - Warm and reassuring (help the buyer feel confident)
   - Personal and conversational
   - 2-3 sentences per explanation
   - Avoid corporate/salesy language

7. ALREADY PURCHASED ITEMS
   - If previously purchased, acknowledge it naturally: "Since %s loved this before, it's a safe bet - though you might also try [different angle]"

FORBIDDEN PHRASES (do not use these repetitive templates):
- "Perfect for [name] who loves..."
- "This shows you really know..."
- "A great choice for..."
- "[Name] will love this because..."
- "Shows you pay attention..."

Instead, write naturally as if explaining to a friend why each specific gift makes sense.

OUTPUT FORMAT: Valid JSON only.
""" % (
        recipient_display,
        context_text,
        recipient_name or possessive,
        possessive,
        occasion or "this special moment",
        relationship or "your connection"
    )

    user_prompt = """
User's search: "%s"

Create explanations that are:
1. Genuinely unique for each gift (no repeated structures)
2. Specific to what each gift actually is and does
3. Personal to %s and the %s occasion
4. Varied in approach and tone

JSON Format:
{
  "intro": "One warm, natural sentence mentioning %s and the occasion",
  "gifts": [
    {
      "name": "exact gift name from the list",
      "reason": "Unique 2-3 sentence explanation that uses %s and is COMPLETELY DIFFERENT from all other explanations"
    }
  ]
}

Gifts to explain (in this order):
%s

Remember: Each explanation must feel like it was written fresh, not filled from a template. Vary sentence structure, vocabulary, and approach.
""" % (
        query,
        recipient_name or "the recipient",
        occasion or "special",
        recipient_name or "them",
        recipient_name or possessive,
        gift_context
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7  # Higher temperature for more variety
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
        parsed = {
            "intro": "Here are some thoughtful gifts for %s:" % recipient_display,
            "gifts": []
        }
        tokens_used = 0

    # Re-sync with retrieval order and create diverse fallbacks
    enriched = []
    llm_results = {}

    for g in parsed.get("gifts", []):
        name = g.get("name", "").lower()
        reason = g.get("reason", "")
        llm_results[name] = reason

    # Fallback templates with high variety
    fallback_templates = [
        lambda name, interest, occ,
               rel: "%s has been into %s lately - this fits right into that passion while being practical enough for everyday use. For %s, it hits the sweet spot between thoughtful and useful." % (
            name, interest, occ),
        lambda name, interest, occ,
               rel: "This caught my eye because %s mentioned %s, and this is something that actually enhances that experience rather than just sitting on a shelf. It's the kind of gift that gets used and appreciated." % (
            name, interest),
        lambda name, interest, occ,
               rel: "Knowing %s's taste in %s, this feels like something they'd pick out themselves - which is always the goal. It's personal without being over-the-top, especially for %s." % (
            name, interest, occ),
        lambda name, interest, occ,
               rel: "This works because it connects to %s's interest in %s, but in a way that adds something new to it. Given it's for %s, it strikes the right balance between meaningful and practical." % (
            name, interest, occ),
        lambda name, interest, occ,
               rel: "The quality here is noticeable, and %s will definitely pick up on that. It's not just about the %s angle - it's about getting something that feels considered and well-chosen for this %s." % (
            name, interest, occ)
    ]

    for idx, original in enumerate(gifts):
        reason = llm_results.get(original["name"].lower())

        if not reason:
            # Create diverse fallback
            interests = original.get('interests', [])
            interest_text = interests[0] if interests else "what they enjoy"

            # Rotate through different fallback templates
            template_func = fallback_templates[idx % len(fallback_templates)]
            reason = template_func(
                recipient_name or "They",
                interest_text,
                occasion or "this occasion",
                relationship or "your relationship"
            )

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

    intro = parsed.get("intro", "Here are some thoughtful gifts for %s:" % recipient_display)

    logger.info("Generated %d unique explanations for %s (%s, %s)" % (
        len(enriched),
        recipient_name or "recipient",
        occasion or "no occasion",
        relationship or "no relationship"
    ))

    return {"intro": intro, "gifts": enriched}, tokens_used