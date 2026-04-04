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
# These rules are injected into the LLM prompt so the "Why this works"
# reasoning is grounded in the same logic as the quiz recommendations.
# =============================================================================

# What each occasion is really about emotionally
OCCASION_EMOTIONAL_REGISTER = {
    "birthday":    "Her birthday is about celebrating who she is as an individual — not the relationship. The gift should feel like it was chosen specifically for her.",
    "valentines":  "Valentine's Day is her holiday. The gift should feel warm and intentional — something that signals desire and care, not convenience.",
    "anniversary": "Anniversaries reward depth and personalisation above all else. The gift should reference your shared history or show you've been paying attention.",
    "christmas":   "Christmas gifts should feel warm, generous, and indulgent — things she'd love but wouldn't splurge on herself.",
    "mothers_day": "Mother's Day is about appreciation and pampering. The gift should say 'I see how much you do' and let her rest and feel celebrated.",
    "just_because":"An unexpected gift is one of the most romantic moves there is. It should feel spontaneous and personal — not like a grand gesture.",
    "apology":     "An apology gift must feel genuine, not expensive. It should say 'I was thinking about you specifically' — personal and warm without looking like a bribe.",
}

# What each relationship stage means for gift strategy
STAGE_GIFT_STRATEGY = {
    "new": (
        "This is an early relationship. The gift should feel thoughtful but low-pressure — "
        "nothing that implies too much too soon. Consumables, experiences, and things tied to "
        "her specific interests work well. Avoid anything sentimental, personalised with both names, "
        "or expensive. The gesture matters more than the price tag."
    ),
    "dating": (
        "They know each other well enough to be specific. The gift should show he was paying "
        "attention to what she's into — a generic gift is actually a miss at this stage. "
        "Interest-driven gifts outperform expensive generic ones here."
    ),
    "serious": (
        "This is a serious relationship — living together or close to it. She expects him to know "
        "her well, so the gift should reflect that. Something she'd never buy herself, tied to her "
        "interests or lifestyle, is the sweet spot. Generic or practical gifts feel like a miss."
    ),
    "committed": (
        "They're married or engaged. The bar is high because there's no excuse for not knowing her. "
        "The best gifts either pamper her, reference their shared history, or are things she's "
        "been wanting but won't justify buying. Thoughtless expensive gifts land worse than "
        "thoughtful inexpensive ones."
    ),
    "complicated": (
        "The relationship is on-and-off or rocky right now. The gift should feel warm and genuine "
        "without putting pressure on where things are headed. Avoid anything too romantic, too "
        "sentimental, or too expensive — light, cozy, and personal is the right register."
    ),
}

# What each vibe tag means in plain English for the LLM
VIBE_EXPLANATIONS = {
    "pampering":   "makes her feel taken care of and gives her permission to rest",
    "romantic":    "signals warmth, desire, and intentionality — this is about her as a partner",
    "sentimental": "shows he's been paying attention to their relationship and her specifically",
    "luxe":        "gives her something she'd never justify buying for herself",
    "cozy":        "makes her home or downtime feel better — warm and low-pressure",
    "fun":         "playful, surprising, and genuinely enjoyable — doesn't take itself too seriously",
    "thoughtful":  "specific to who she is — shows he actually listens",
}

# Per-occasion pitfalls to warn the LLM about
OCCASION_PITFALLS = {
    "valentines":  "Avoid framing practical or tech gifts as romantic — they read as impersonal on Valentine's Day.",
    "anniversary": "Avoid generic luxury items — a $300 gift that a stranger could have bought her will land worse than a $60 gift that references something specific to them.",
    "birthday":    "Avoid making the gift about the relationship — her birthday is about her as a person.",
    "mothers_day": "Avoid fitness gifts — they can read as a comment on her body rather than a celebration of her.",
    "apology":     "Never frame the gift as compensation. The language should be warm and humble, not impressive.",
    "just_because":"Avoid anything that feels like a grand gesture — spontaneous gifts should feel effortless.",
    "christmas":   "Avoid overly practical gifts — Christmas should feel indulgent and warm.",
}


def _build_gift_intelligence_block(
    occasion: Optional[str],
    stage: Optional[str],
    vibe: Optional[List[str]],
    confidence: Optional[str],
) -> str:
    """
    Builds the gift intelligence context block injected into the system prompt.
    This is the core of the upgrade — gives the LLM the same knowledge as the
    quiz recommendation engine so reasoning is consistent and specific.
    """
    lines = ["GIFT INTELLIGENCE — USE THIS TO WRITE SPECIFIC, SMART REASONS:"]

    if occasion and occasion in OCCASION_EMOTIONAL_REGISTER:
        lines.append(f"\nOCCASION CONTEXT:\n{OCCASION_EMOTIONAL_REGISTER[occasion]}")

    if stage and stage in STAGE_GIFT_STRATEGY:
        lines.append(f"\nRELATIONSHIP STAGE STRATEGY:\n{STAGE_GIFT_STRATEGY[stage]}")

    if vibe:
        vibe_lines = []
        for v in vibe:
            if v in VIBE_EXPLANATIONS:
                vibe_lines.append(f"  - {v.capitalize()}: a gift that {VIBE_EXPLANATIONS[v]}")
        if vibe_lines:
            lines.append(f"\nTARGET VIBE — the gift should feel like it:\n" + "\n".join(vibe_lines))

    if occasion and occasion in OCCASION_PITFALLS:
        lines.append(f"\nAVOID:\n{OCCASION_PITFALLS[occasion]}")

    if confidence == "lost":
        lines.append(
            "\nNOTE: He doesn't know her interests well. "
            "Frame reasons around the occasion and vibe rather than her specific hobbies."
        )
    elif confidence == "confident":
        lines.append(
            "\nNOTE: He knows her well. "
            "Reasons should directly connect the gift to her specific interests and personality."
        )

    return "\n".join(lines)


def _build_reason_instruction(
    target: str,
    occasion: Optional[str],
    stage: Optional[str],
) -> str:
    """
    Builds the per-gift reason instruction so the LLM knows exactly
    what angle to take for each explanation.
    """
    occasion_angles = {
        "birthday":    f"why this is the right choice for {target}'s birthday specifically — how it celebrates who she is",
        "valentines":  f"what this gift communicates to {target} on Valentine's Day — why it feels warm and intentional",
        "anniversary": f"how this gift acknowledges the depth of their relationship — why it feels meaningful not generic",
        "christmas":   f"why this is a great Christmas gift for {target} — the indulgence or warmth it delivers",
        "mothers_day": f"how this makes {target} feel appreciated and celebrated as a mother",
        "just_because":f"why this works as a surprise gift for {target} — the spontaneous, personal quality of it",
        "apology":     f"why this is the right apology gesture for {target} — the sincerity and warmth it conveys",
    }

    angle = occasion_angles.get(
        occasion or "",
        f"why this is a smart, well-matched gift for {target}"
    )

    stage_lens = {
        "new":         "Keep it light — explain why this feels right without being too intense.",
        "dating":      "Highlight how it shows he was paying attention to her specifically.",
        "serious":     "Explain how it treats her as someone he truly knows.",
        "committed":   "Connect it to pampering her, knowing her deeply, or their shared life.",
        "complicated": "Keep the framing warm and genuine — avoid anything that sounds loaded.",
    }

    lens = stage_lens.get(stage or "", "")

    return f"Explain {angle}. {lens}".strip()


# =============================================================================
# HELPERS (unchanged from original)
# =============================================================================

def generate_display_name(product_name: str, description: str = "") -> str:
    prompt = f"""You are a product naming expert. Convert this Amazon product name into a clean, retail-ready display name.

Amazon Product Name: {product_name}

Rules:
1. Maximum 6 words
2. Keep the core product type and key feature
3. Remove SEO filler and unnecessary words
4. Keep important specs if relevant
5. Natural, human-sounding title

Return ONLY the clean display name."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=20,
        )
        display_name = response.choices[0].message.content.strip().strip('"').strip("'")
        words = display_name.split()
        if len(words) > 6:
            display_name = " ".join(words[:6])
        return display_name
    except Exception as e:
        logger.error(f"Display name error: {e}")
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

    best_reason = None
    best_score = 0
    for g in llm_gifts:
        llm_tokens = set(g.get("name", "").lower().split())
        shared = len(orig_tokens & llm_tokens)
        if shared > best_score and shared >= 2:
            best_score = shared
            best_reason = g.get("reason")

    return best_reason


def _get_urgency_label(days: Optional[int]) -> str:
    if days is None:
        return "unknown timing"
    if days <= 2:
        return "last-minute"
    if days <= 7:
        return "soon"
    if days <= 21:
        return "moderate time"
    return "plenty of time"


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def generate_gift_response(
    query: str,
    gifts: List[Dict],
    preferences: Optional[Dict] = None,
    partner_context: Optional[Dict] = None,
    session_context: Optional[Dict] = None,
) -> tuple[Dict, int]:

    if not gifts:
        return {"intro": "Couldn't find good matches — try adjusting filters.", "gifts": []}, 0

    # --- CONTEXT EXTRACTION ---
    recipient_name    = partner_context.get("name") if partner_context else None
    partner_interests = partner_context.get("interests", []) if partner_context else []
    partner_vibe      = partner_context.get("vibe", []) if partner_context else []
    partner_archetypes= partner_context.get("archetypes", []) if partner_context else []

    relationship  = session_context.get("relationship_stage") or session_context.get("relationship") if session_context else None
    occasion      = session_context.get("occasion") if session_context else None
    budget        = session_context.get("budget") if session_context else None
    days          = session_context.get("days_until_needed") if session_context else None
    confidence    = session_context.get("confidence") if session_context else None
    vibe          = list(partner_vibe) if partner_vibe else []

    urgency = _get_urgency_label(days)

    # --- HUMANIZED TARGET ---
    if recipient_name:
        target = recipient_name
    elif relationship:
        relationship_labels = {
            "new":         "someone you just started seeing",
            "dating":      "your girlfriend",
            "serious":     "your girlfriend",
            "committed":   "your wife",
            "complicated": "your partner",
        }
        target = relationship_labels.get(relationship, f"your {relationship}")
    else:
        target = "her"

    # --- CONTEXT BLOCK ---
    context_text = f"""
RECIPIENT: {target}
OCCASION: {occasion or "general"}
RELATIONSHIP STAGE: {relationship or "unknown"}
BUDGET: {"$" + str(budget) if budget else "flexible"}
TIMING: {urgency}

PROFILE:
- Interests: {", ".join(partner_interests[:5]) if partner_interests else "unknown"}
- Vibe Goal: {", ".join(vibe[:2]) if vibe else "unknown"}
- Archetypes: {", ".join(partner_archetypes[:2]) if partner_archetypes else "unknown"}
"""

    # --- GIFT INTELLIGENCE BLOCK (new) ---
    gift_intelligence = _build_gift_intelligence_block(occasion, relationship, vibe, confidence)

    # --- REASON INSTRUCTION (new) ---
    reason_instruction = _build_reason_instruction(target, occasion, relationship)

    # --- GIFT LIST ---
    gift_context = ""
    for i, gift in enumerate(gifts, 1):
        name    = gift.get("name", "")
        desc    = textwrap.shorten(gift.get("description", ""), width=150, placeholder="...")
        price   = gift.get("price", 0)
        reasons = ", ".join(gift.get("ranking_reasons", []))
        g_vibe  = ", ".join(gift.get("vibe") or [])
        gift_context += f"{i}. {name} (${price:.2f})\nVibe tags: {g_vibe}\nWhy it surfaced: {reasons}\nDesc: {desc}\n---\n"

    # --- SYSTEM PROMPT ---
    system_prompt = f"""You are an elite gift advisor helping men choose the right gift for their partner.
Your job is not to describe products — it is to explain WHY a gift is the right move for this specific person, occasion, and relationship moment.

{context_text}

{gift_intelligence}

WRITING RULES:
1. Never describe product features unless they directly explain WHY the gift works.
2. Every reason must be specific to {target}, this occasion, and this relationship stage.
3. Write like you are advising a close friend — confident, warm, direct.
4. Use the gift intelligence above to ground every explanation.
5. Do not be salesy. Do not use phrases like "perfect gift" or "she'll love it."
6. Each reason should feel like: "This is the smart move here because..."

WHAT MAKES A REASON GREAT:
- It tells him what the gift COMMUNICATES to her
- It connects to her personality, interests, or their relationship stage
- It gives him confidence that this is the right call
- It is 2–3 sentences, not a list

Return valid JSON only. No markdown, no preamble."""

    # --- USER PROMPT ---
    user_prompt = f"""Search context: "{query}"

For each gift, write a reason that answers: {reason_instruction}

Return JSON:
{{
  "intro": "One natural sentence introducing these picks. Mention the occasion, the timing ({urgency}), and what makes these right for {target} right now.",
  "gifts": [
    {{
      "name": "<exact product name>",
      "reason": "2-3 sentences. {reason_instruction}"
    }}
  ]
}}

Include a reason for EVERY gift listed below.

Gifts:
{gift_context}"""

    # --- LLM CALL ---
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
            max_tokens=900,   # bumped from 700 — smarter reasons need more room
        )
        logger.info(f"LLM call {(time.time() - start) * 1000:.0f}ms")

        parsed = json.loads(response.choices[0].message.content.strip())
        tokens_used = response.usage.total_tokens if response.usage else 0

    except Exception as e:
        logger.error(f"LLM error: {e}")
        parsed = {"intro": "Here are some solid options:", "gifts": []}
        tokens_used = 0

    llm_gifts = parsed.get("gifts", [])

    # --- ENRICH RESULTS (parallelized — unchanged from original) ---
    def enrich_single_gift(original: Dict) -> Dict:
        name   = original.get("name", "")
        reason = _fuzzy_match_reason(name, llm_gifts)

        if not reason:
            # Fallback reason is now occasion-aware instead of generic
            occasion_fallbacks = {
                "valentines":  "A warm, intentional choice that fits the occasion well.",
                "anniversary": "A meaningful pick that reflects how well he knows her.",
                "birthday":    "A gift that's genuinely about her — not just the occasion.",
                "mothers_day": "A pampering choice that says he sees how much she does.",
                "apology":     "A sincere, personal gesture that doesn't try too hard.",
                "just_because":"A thoughtful surprise that shows she's on his mind.",
                "christmas":   "A warm, indulgent pick she'd love but wouldn't buy herself.",
            }
            reason = occasion_fallbacks.get(
                occasion or "",
                "A strong, well-matched choice for this moment."
            )

        display_name = original.get("display_name")
        if not display_name:
            display_name = generate_display_name(name, original.get("description", ""))

        return {
            "name":             name,
            "display_name":     display_name,
            "price":            original.get("price", 0),
            "confidence":       original.get("confidence", 0),
            "description":      original.get("description", ""),
            "image_url":        original.get("image_url", ""),
            "product_url":      original.get("product_url", "") or original.get("link", ""),
            "reason":           reason,
            "ranking_reasons":  original.get("ranking_reasons", []),
            "already_purchased":original.get("already_purchased", False),
            "shipping_min_days":original.get("shipping_min_days"),
            "shipping_max_days":original.get("shipping_max_days"),
            "is_prime_eligible":original.get("is_prime_eligible"),
        }

    start_enrich = time.time()
    with ThreadPoolExecutor(max_workers=10) as executor:
        enriched = list(executor.map(enrich_single_gift, gifts))
    logger.info(f"Enrichment & Naming took {(time.time() - start_enrich) * 1000:.0f}ms")

    return {"intro": parsed.get("intro", ""), "gifts": enriched}, tokens_used