from openai import OpenAI
import os
import time
import textwrap
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from typing import List, Dict, Optional
import json
import logging

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)


# =============================================================================
# GIFT INTELLIGENCE — OCCASION × STAGE
# =============================================================================

OCCASION_EMOTIONAL_REGISTER = {
    "birthday":    "Her birthday is about celebrating who she is as an individual — not the relationship.",
    "valentines":  "Valentine's Day is her holiday. The gift should feel warm and intentional.",
    "anniversary": "Anniversaries reward depth and personalisation above all else.",
    "christmas":   "Christmas gifts should feel warm, generous, and indulgent.",
    "mothers_day": "Mother's Day is about appreciation and pampering.",
    "just_because":"An unexpected gift should feel spontaneous and personal.",
    "apology":     "An apology gift must feel genuine, not expensive.",
}

STAGE_GIFT_STRATEGY = {
    "new": "Keep it thoughtful but low-pressure.",
    "dating": "Show you were paying attention to her specifically.",
    "serious": "Reflect that you truly know her.",
    "committed": "High bar — must feel deeply personal or indulgent.",
    "complicated": "Keep it warm, light, and pressure-free.",
}

VIBE_EXPLANATIONS = {
    "pampering":   "makes her feel taken care of",
    "romantic":    "signals desire and intentionality",
    "sentimental": "shows you've been paying attention",
    "luxe":        "feels indulgent and special",
    "cozy":        "makes her downtime feel better",
    "fun":         "playful and surprising",
    "thoughtful":  "specific to who she is",
}

OCCASION_PITFALLS = {
    "valentines":  "Avoid practical gifts framed as romantic.",
    "anniversary": "Avoid generic luxury items.",
    "birthday":    "Do not make it about the relationship.",
    "mothers_day": "Avoid fitness gifts.",
    "apology":     "Do not make it feel like compensation.",
}


def _build_gift_intelligence_block(occasion, stage, vibe, confidence):
    lines = ["GIFT INTELLIGENCE:"]

    if occasion in OCCASION_EMOTIONAL_REGISTER:
        lines.append(OCCASION_EMOTIONAL_REGISTER[occasion])

    if stage in STAGE_GIFT_STRATEGY:
        lines.append(STAGE_GIFT_STRATEGY[stage])

    if vibe:
        lines.append("Vibe intent:")
        for v in vibe:
            if v in VIBE_EXPLANATIONS:
                lines.append(f"- {v}: {VIBE_EXPLANATIONS[v]}")

    if occasion in OCCASION_PITFALLS:
        lines.append(f"Avoid: {OCCASION_PITFALLS[occasion]}")

    if confidence == "lost":
        lines.append("He doesn't know her well — rely on vibe + occasion.")
    elif confidence == "confident":
        lines.append("He knows her well — be specific.")

    return "\n".join(lines)


def _build_reason_instruction(target, occasion, stage):
    return f"Explain why this is the right move for {target} right now."


# =============================================================================
# HELPERS
# =============================================================================

def generate_display_name(product_name: str, description: str = "") -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Clean product name (max 6 words): {product_name}"
            }],
            temperature=0.3,
            max_tokens=20,
        )
        name = response.choices[0].message.content.strip()
        return " ".join(name.split()[:6])
    except Exception:
        return " ".join(product_name.split()[:6])


def _fuzzy_match_reason(orig_name: str, llm_gifts: List[Dict]) -> Optional[str]:
    if not llm_gifts:
        return None

    orig_lower = orig_name.lower()
    orig_tokens = set(orig_lower.split())

    for g in llm_gifts:
        if g.get("name", "").lower() == orig_lower:
            return g.get("reason")

    for g in llm_gifts:
        llm_name = g.get("name", "").lower()
        if llm_name and (llm_name in orig_lower or orig_lower in llm_name):
            return g.get("reason")

    best_reason, best_score = None, 0
    for g in llm_gifts:
        tokens = set(g.get("name", "").lower().split())
        score = len(orig_tokens & tokens)
        if score > best_score and score >= 2:
            best_score = score
            best_reason = g.get("reason")

    return best_reason


# =============================================================================
# MAIN
# =============================================================================

def generate_gift_response(query, gifts, preferences=None, partner_context=None, session_context=None):

    if not gifts:
        return {"intro": "Couldn't find good matches.", "gifts": []}, 0

    recipient_name = partner_context.get("name") if partner_context else None
    partner_interests = partner_context.get("interests", []) if partner_context else []
    partner_vibe = partner_context.get("vibe", []) if partner_context else []

    relationship = session_context.get("relationship") if session_context else None
    occasion = session_context.get("occasion") if session_context else None
    confidence = session_context.get("confidence") if session_context else None

    target = recipient_name or "her"

    context_text = f"""
RECIPIENT: {target}
OCCASION: {occasion}
RELATIONSHIP: {relationship}
INTERESTS: {", ".join(partner_interests[:5])}
VIBE GOAL: {", ".join(partner_vibe[:3])}
"""

    gift_intelligence = _build_gift_intelligence_block(
        occasion,
        relationship,
        partner_vibe,
        confidence
    )

    # 🔥 FEW-SHOT EXAMPLES
    examples = """
GOOD REASON:
"This feels like you're leaning into how much she values slow, cozy downtime, not just giving her something generic for the house. It matches her personality in a way that feels intentional instead of safe. For her birthday, that lands because it’s about her specifically, not just checking a box."

BAD REASON:
"This blanket is soft, warm, and great for relaxing at home. It’s a perfect gift she will love."
"""

    system_prompt = f"""
You are an elite gift advisor.

Your job is to explain WHY a gift is the right decision.

{context_text}

{gift_intelligence}

{examples}

RULES:

- If it sounds like a product description, it is wrong.
- Focus on what the gift COMMUNICATES.
- Be specific to her, the relationship, and the moment.

REASON STRUCTURE (MANDATORY):
1. What it signals emotionally
2. Why it fits her
3. Why it fits now

A great answer makes him think:
"I wouldn’t have thought of this, but it’s exactly right."

Return JSON only.
"""

    # 🔥 RICH GIFT CONTEXT (RESTORED)
    gift_context = ""
    for i, g in enumerate(gifts, 1):
        name = g.get("name", "")
        desc = textwrap.shorten(g.get("description", ""), width=140, placeholder="...")
        price = g.get("price", 0)
        ranking = ", ".join(g.get("ranking_reasons", []))
        vibe_tags = ", ".join(g.get("vibe", []))

        gift_context += f"""
{i}. {name} (${price})
Vibe tags: {vibe_tags}
Why it surfaced: {ranking}
Description: {desc}
---
"""

    user_prompt = f"""
Query: {query}

Write reasons for each gift.

Gifts:
{gift_context}

Return JSON:
{{
  "intro": "one sentence",
  "gifts": [
    {{
      "name": "<exact name>",
      "reason": "2-3 sentences"
    }}
  ]
}}
"""

    try:
        start = time.time()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.85,
            max_tokens=900,
        )

        parsed = json.loads(response.choices[0].message.content.strip())
        tokens = response.usage.total_tokens if response.usage else 0

        logger.info(f"LLM call {(time.time() - start)*1000:.0f}ms")

    except Exception as e:
        logger.error(e)
        parsed = {"intro": "", "gifts": []}
        tokens = 0

    llm_gifts = parsed.get("gifts", [])

    enriched = []
    for g in gifts:
        reason = _fuzzy_match_reason(g.get("name", ""), llm_gifts) or "Strong contextual match."

        enriched.append({
            "name": g.get("name"),
            "display_name": generate_display_name(g.get("name")),
            "price": g.get("price"),
            "reason": reason,
            "image_url": g.get("image_url"),
            "product_url": g.get("product_url"),
        })

    return {"intro": parsed.get("intro", ""), "gifts": enriched}, tokens