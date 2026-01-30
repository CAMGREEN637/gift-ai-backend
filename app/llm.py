from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Optional
import json

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_gift_response(
    query: str,
    gifts: List[Dict],
    preferences: Optional[Dict] = None
) -> Dict:
    """
    Generates a natural language explanation of gift recommendations.
    Preserves ranking detail while ensuring frontend-safe output.
    """

    # ---------- Build preference context ----------

    if preferences:
        pref_text = f"""
User preferences (IMPORTANT):
- Interests: {preferences.get("interests", [])}
- Vibe: {preferences.get("vibe", [])}

You must prioritize gifts that match these preferences and
explicitly explain how each gift aligns with them.
"""
    else:
        pref_text = "User did not provide explicit preferences."

    # ---------- Build gift context ----------

    gift_context = ""
    for gift in gifts:
        gift_context += f"""
Name: {gift['name']}
Price: ${gift['price']}
Confidence: {gift['confidence']}
Ranking reasons: {', '.join(gift.get('ranking_reasons', [])) or 'General relevance'}
Description: {gift.get('description', 'No description provided')}
---
"""

    # ---------- System prompt ----------

    system_prompt = f"""
You are a thoughtful gift recommendation assistant.

Your job is to explain gift recommendations clearly, honestly,
and persuasively — without inventing facts.

{pref_text}

Rules:
- Treat higher confidence gifts as stronger recommendations
- Use ranking reasons verbatim when explaining why a gift was chosen
- Do NOT invent new reasons or preferences
- If a gift has lower confidence, frame it as an alternative
- Keep explanations concise but warm
"""

    # ---------- User prompt ----------

    user_prompt = f"""
User query: "{query}"

Return STRICT JSON in this format:

{{
  "intro": "one short sentence setting context",
  "gifts": [
    {{
      "name": "gift name",
      "price": number,
      "confidence": number,
      "reason": "1–2 sentence explanation referencing ranking reasons"
    }}
  ]
}}

Gift options:
{gift_context}
"""

    # ---------- LLM call ----------

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.4
    )

    content = response.choices[0].message.content

    # ---------- Parse + normalize output ----------

    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {
            "intro": "Here are a few thoughtful gift ideas you might like:",
            "gifts": []
        }

    # ---------- HARD NORMALIZATION (CRITICAL FIX) ----------

    normalized_gifts = []

    for gift in parsed.get("gifts", []):
        # Find original gift to recover ranking reasons
        source = next(
            (g for g in gifts if g["name"] == gift["name"]),
            None
        )

        ranking_reasons = (
            source.get("ranking_reasons")
            if source and isinstance(source.get("ranking_reasons"), list)
            else ["Good overall match for your request"]
        )

        normalized_gifts.append({
            "name": gift["name"],
            "price": gift.get("price"),
            "confidence": gift.get("confidence", 0.5),
            "reason": gift.get("reason"),
            "ranking_reasons": ranking_reasons,
        })

    return {
        "intro": parsed.get(
            "intro",
            "Here are some thoughtful gift ideas based on your request."
        ),
        "gifts": normalized_gifts,
    }

