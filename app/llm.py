from openai import OpenAI
import os
import time
import textwrap
import re
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from typing import List, Dict, Optional, Tuple
import json
import logging

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)


# =============================================================================
# GIFT INTELLIGENCE — OCCASION x STAGE
# =============================================================================

OCCASION_EMOTIONAL_REGISTER = {
    "birthday":    "Her birthday is about celebrating who she is as an individual — not the relationship. The gift should feel like it was chosen specifically for her.",
    "valentines":  "Valentine's Day is her holiday. The gift should feel warm and intentional — something that signals desire and care, not convenience.",
    "anniversary": "Anniversaries reward depth and personalisation above all else. The gift should reference your shared history or show you've been paying attention.",
    "christmas":   "Christmas gifts should feel warm, generous, and indulgent — things she'd love but wouldn't splurge on herself.",
    "mothers_day": "Mother's Day is about appreciation and pampering. The gift should say 'I see how much you do' and let her rest and feel celebrated.",
    "just_because":"An unexpected gift is one of the most romantic moves there is. It should feel spontaneous and personal — not like a grand gesture.",
    "apology":     "An apology gift must feel genuine, not expensive. It should say 'I was thinking about you specifically' — personal and warm without looking like a bribe.",
}

STAGE_GIFT_STRATEGY = {
    "new": (
        "This is an early relationship. The gift should feel thoughtful but low-pressure — "
        "nothing that implies too much too soon. The gesture matters more than the price tag."
    ),
    "dating": (
        "They know each other well enough to be specific. The gift should show he was paying "
        "attention to what she is into — a generic gift is a miss at this stage."
    ),
    "serious": (
        "This is a serious relationship. She expects him to know her well, so the gift should "
        "reflect that. Something she would never buy herself, tied to her interests or lifestyle."
    ),
    "committed": (
        "They are married or engaged. The best gifts either pamper her, reference their shared "
        "history, or are things she has been wanting but will not justify buying."
    ),
    "complicated": (
        "The relationship is on-and-off. The gift should feel warm and genuine without putting "
        "pressure on where things are headed. Light, cozy, and personal."
    ),
}

VIBE_EXPLANATIONS = {
    "pampering":   "makes her feel taken care of and gives her permission to rest",
    "romantic":    "signals warmth, desire, and intentionality",
    "sentimental": "shows he has been paying attention to their relationship and her specifically",
    "luxe":        "gives her something she would never justify buying for herself",
    "cozy":        "makes her home or downtime feel better — warm and low-pressure",
    "fun":         "playful, surprising, and genuinely enjoyable",
    "thoughtful":  "specific to who she is — shows he actually listens",
}

OCCASION_PITFALLS = {
    "valentines":  "Avoid framing practical or tech gifts as romantic — they read as impersonal on Valentine's Day.",
    "anniversary": "Avoid generic luxury items — a gift that a stranger could have bought her will land worse than something specific.",
    "birthday":    "Avoid making the gift about the relationship — her birthday is about her as a person.",
    "mothers_day": "Avoid fitness gifts — they can read as a comment on her body rather than a celebration of her.",
    "apology":     "Never frame the gift as compensation. The language should be warm and humble, not impressive.",
    "just_because":"Avoid anything that feels like a grand gesture — spontaneous gifts should feel effortless.",
    "christmas":   "Avoid overly practical gifts — Christmas should feel indulgent and warm.",
}


def _sanitize_for_prompt(text: str) -> str:
    """
    Strip characters that cause JSON parse errors when injected into prompts.
    Replaces smart quotes, strips non-ASCII, collapses whitespace.
    """
    if not text:
        return ""
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.encode("ascii", errors="ignore").decode("ascii")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _build_gift_intelligence_block(
    occasion: Optional[str],
    stage: Optional[str],
    vibe: Optional[List[str]],
    confidence: Optional[str],
) -> str:
    lines = ["GIFT INTELLIGENCE:"]

    if occasion and occasion in OCCASION_EMOTIONAL_REGISTER:
        lines.append(f"OCCASION: {OCCASION_EMOTIONAL_REGISTER[occasion]}")

    if stage and stage in STAGE_GIFT_STRATEGY:
        lines.append(f"STAGE: {STAGE_GIFT_STRATEGY[stage]}")

    if vibe:
        vibe_lines = [
            f"  - {v}: a gift that {VIBE_EXPLANATIONS[v]}"
            for v in vibe if v in VIBE_EXPLANATIONS
        ]
        if vibe_lines:
            lines.append("VIBE TARGET:\n" + "\n".join(vibe_lines))

    if occasion and occasion in OCCASION_PITFALLS:
        lines.append(f"AVOID: {OCCASION_PITFALLS[occasion]}")

    if confidence == "lost":
        lines.append("NOTE: He does not know her interests well. Anchor reasons in occasion and stage logic only — do not reference interests.")
    elif confidence == "confident":
        lines.append("NOTE: He knows her well. Where interests are provided, connect each reason directly to them.")

    return "\n".join(lines)


def _build_reason_instruction(
    target: str,
    occasion: Optional[str],
    stage: Optional[str],
) -> str:
    occasion_angles = {
        "birthday":    f"why this is the right birthday gift given what you know about {target} — not a generic birthday gift, but a specific one for her",
        "valentines":  f"why this is the right Valentine's Day move at this stage of the relationship",
        "anniversary": f"why this lands well for an anniversary given where they are in the relationship",
        "christmas":   f"why this is a strong Christmas gift for someone with her interests",
        "mothers_day": f"why this gives {target} the kind of break and appreciation Mother's Day is actually about",
        "just_because":f"why this works as an unexpected, personal gesture for {target}",
        "apology":     f"why this reads as sincere and considerate rather than expensive or generic",
    }
    angle = occasion_angles.get(occasion or "", f"why this is a well-matched gift for {target} right now")

    stage_lens = {
        "new":         "Reassure the buyer that this feels right without being too intense for an early relationship.",
        "dating":      "Validate that this shows he was paying attention to her specifically — not just buying something easy.",
        "serious":     "Confirm this is the right level — something she'd never buy herself, tied to what she's actually into.",
        "committed":   "Reassure him this hits the pampering or personal angle that works in a long relationship.",
        "complicated": "Validate that this feels warm and genuine without putting pressure on where things stand.",
    }
    lens = stage_lens.get(stage or "", "")
    return f"Explain {angle}. {lens}".strip()


# =============================================================================
# HELPERS
# =============================================================================

def generate_display_name(product_name: str, description: str = "") -> str:
    """Generate a clean 6-word display name. Only called when not already set on the gift."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "Convert this Amazon product name into a clean retail display name. "
                    "Max 6 words. No SEO filler. Return ONLY the name.\n\n"
                    f"Product: {product_name[:120]}"
                ),
            }],
            temperature=0.3,
            max_tokens=20,
        )
        name = response.choices[0].message.content.strip().strip('"').strip("'")
        return " ".join(name.split()[:6])
    except Exception as e:
        logger.warning(f"Display name generation failed: {e}")
        return " ".join(product_name.split()[:6])


def _fuzzy_match_reason(orig_name: str, llm_gifts: List[Dict]) -> Optional[str]:
    if not llm_gifts:
        return None

    orig_lower  = orig_name.lower()
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
        score  = len(orig_tokens & tokens)
        if score > best_score and score >= 2:
            best_score  = score
            best_reason = g.get("reason")

    return best_reason


def _get_urgency_label(days: Optional[int]) -> str:
    if days is None: return "unknown timing"
    if days <= 2:    return "last-minute"
    if days <= 7:    return "soon"
    if days <= 21:   return "moderate time"
    return "plenty of time"


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> Tuple[Optional[dict], int]:
    """
    Single LLM call. Returns (parsed_dict_or_None, tokens_used).
    Returns None if the response was truncated (finish_reason=length)
    or if the JSON failed to parse.
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.80,
        max_tokens=max_tokens,
    )
    raw         = response.choices[0].message.content.strip()
    tokens_used = response.usage.total_tokens if response.usage else 0
    finish      = response.choices[0].finish_reason

    if finish == "length":
        logger.warning(
            f"LLM response truncated at max_tokens={max_tokens} "
            f"(finish_reason=length, tokens={tokens_used})"
        )
        return None, tokens_used

    try:
        return json.loads(raw), tokens_used
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.debug(f"Raw output (first 600 chars): {raw[:600]}")
        return None, tokens_used


# =============================================================================
# MAIN
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

    # --- Context extraction ---
    recipient_name     = partner_context.get("name")          if partner_context else None
    partner_interests  = partner_context.get("interests", []) if partner_context else []
    partner_vibe       = partner_context.get("vibe", [])      if partner_context else []
    partner_archetypes = partner_context.get("archetypes", [])if partner_context else []

    relationship = (
        session_context.get("relationship_stage")
        or session_context.get("relationship")
        if session_context else None
    )
    occasion   = session_context.get("occasion")          if session_context else None
    budget     = session_context.get("budget")            if session_context else None
    days       = session_context.get("days_until_needed") if session_context else None
    confidence = session_context.get("confidence")        if session_context else None
    vibe       = list(partner_vibe) if partner_vibe else []

    urgency = _get_urgency_label(days)

    # --- Humanized target ---
    if recipient_name:
        target = recipient_name
    elif relationship:
        labels = {
            "new":         "someone you just started seeing",
            "dating":      "your girlfriend",
            "serious":     "your girlfriend",
            "committed":   "your wife",
            "complicated": "your partner",
        }
        target = labels.get(relationship, f"your {relationship}")
    else:
        target = "her"

    # --- Intelligence blocks ---
    gift_intelligence  = _build_gift_intelligence_block(occasion, relationship, vibe, confidence)
    reason_instruction = _build_reason_instruction(target, occasion, relationship)

    # --- Build sanitized gift context lines ---
    gift_lines = []
    for i, g in enumerate(gifts, 1):
        name      = _sanitize_for_prompt(g.get("name", ""))
        desc      = _sanitize_for_prompt(
                        textwrap.shorten(g.get("description", ""), width=100, placeholder="...")
                    )
        price     = g.get("price", 0)
        vibe_tags = ", ".join(g.get("vibe") or [])
        gift_lines.append(
            f"{i}. {name} (${price}) | vibe: {vibe_tags} | {desc}"
        )

    # --- System prompt ---
    # Safe interests preview for inline use in the GOOD example
    interests_preview = partner_interests[0] if partner_interests else "her known interests"

    system_prompt = (
        f"You are an elite gift advisor helping men feel confident about the gift they're about to buy.\n"
        f"Your job is NOT to describe the product or invent things about the recipient. "
        f"Your job is to REASSURE the buyer — explain why this is the right call given "
        f"the occasion, the stage of the relationship, and what he actually knows about her.\n\n"
        f"TARGET: {target} | OCCASION: {occasion or 'general'} | "
        f"STAGE: {relationship or 'unknown'} | TIMING: {urgency} | "
        f"BUDGET: {'$' + str(budget) if budget else 'flexible'}\n"
        f"KNOWN INTERESTS: {', '.join(partner_interests[:5]) if partner_interests else 'not specified'}\n\n"
        f"{gift_intelligence}\n\n"
        f"RULES:\n"
        f"- You are writing for the BUYER, not about the recipient. Reassure him his choice is right.\n"
        f"- ONLY reference interests explicitly listed in KNOWN INTERESTS. Never invent traits, values, or preferences.\n"
        f"- Anchor every reason in one or more of: (1) occasion logic, (2) relationship stage logic, (3) her known interests. Use only what you actually have.\n"
        f"- If no interests are known, rely on occasion + stage alone. Do not fabricate specificity.\n"
        f"- 2 sentences max per reason. Confident, warm, direct.\n"
        f"- No phrases like 'perfect gift', 'she will love it', 'timeless', 'cherished', 'lasting elegance'.\n"
        f"- Use '{target}' naturally where it fits. Do not force it into every sentence.\n\n"
        f"GOOD: Valentine's Day at this stage calls for something warm and intentional — not practical. "
        f"Her interest in {interests_preview} gives this a real hook, so it reads as specific rather than a default gesture.\n"
        f"BAD: This speaks to {target}'s deep appreciation for timeless elegance and lasting beauty — "
        f"it honors who she is at her core.\n\n"
        f"Return valid JSON only. No markdown."
    )

    def _make_user_prompt(lines: List[str]) -> str:
        gift_ctx = "\n".join(lines)
        return (
            f"Reason for each gift — answer: {reason_instruction}\n\n"
            f"Gifts:\n{gift_ctx}\n\n"
            f"JSON format:\n"
            f'{{"intro":"one sentence for {target}","gifts":[{{"name":"<exact>","reason":"2 sentences"}}]}}'
        )

    # --- LLM call strategy ---
    parsed      = None
    tokens_used = 0
    start       = time.time()

    try:
        # Attempt 1: all gifts
        parsed, t1 = _call_llm(system_prompt, _make_user_prompt(gift_lines), max_tokens=1400)
        tokens_used += t1

        # Attempt 2: if still failing, retry with top 5 gifts only
        if parsed is None:
            logger.warning("Retrying with top 5 gifts to reduce output size")
            parsed, t2 = _call_llm(system_prompt, _make_user_prompt(gift_lines[:5]), max_tokens=700)
            tokens_used += t2

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        parsed = None

    logger.info(f"LLM total {(time.time() - start)*1000:.0f}ms | tokens: {tokens_used}")

    llm_gifts = parsed.get("gifts", []) if parsed else []

    if not llm_gifts:
        logger.warning("LLM returned no gift reasons — using occasion fallbacks")

    # --- Occasion-aware fallback reasons ---
    occasion_fallbacks = {
        "valentines":  "Valentine's Day calls for something warm and intentional — this fits that register without feeling like a default.",
        "anniversary": "Anniversaries reward thoughtfulness over price. This is a considered pick that reflects where they are.",
        "birthday":    "Her birthday is about her as a person, not the relationship. This is tied to her interests, not just the occasion.",
        "mothers_day": "Mother's Day is about making her feel seen and rested. This delivers that without overcomplicating it.",
        "apology":     "The best apology gifts feel personal, not expensive. This reads as sincere rather than compensatory.",
        "just_because":"Spontaneous gifts land best when they feel warm and specific rather than planned. This does both.",
        "christmas":   "Christmas is about indulgence — something she'd love but wouldn't buy herself. This fits that brief.",
    }
    fallback = occasion_fallbacks.get(occasion or "", "A well-matched choice given the occasion and where they are.")

    # --- Enrich results ---
    def enrich_single_gift(original: Dict) -> Dict:
        name         = original.get("name", "")
        reason       = _fuzzy_match_reason(name, llm_gifts) or fallback
        display_name = original.get("display_name") or generate_display_name(name, original.get("description", ""))

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
    with ThreadPoolExecutor(max_workers=5) as executor:
        enriched = list(executor.map(enrich_single_gift, gifts))
    logger.info(f"Enrichment {(time.time() - start_enrich)*1000:.0f}ms")

    return {"intro": parsed.get("intro", "") if parsed else "", "gifts": enriched}, tokens_used