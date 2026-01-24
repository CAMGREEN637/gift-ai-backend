from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Optional


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_gift_response(
    query: str,
    gifts: List[Dict],
    preferences: Optional[Dict] = None
) -> Dict:
    """
    Generates a natural language explanation of gift recommendations.
    The LLM must only explain existing ranking signals.
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
Ranking reasons: {', '.join(gift['ranking_reasons']) if gift['ranking_reasons'] else 'General relevance'}
Description: {gift['description']}
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

Based on the gift options below, return a JSON response in this format:

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

    # ---------- Parse and return ----------

    content = response.choices[0].message.content

    try:
        return eval(content)
    except Exception:
        # Fallback if JSON parsing fails
        return {
            "intro": "Here are a few thoughtful gift ideas you might like:",
            "gifts": [
                {
                    "name": g["name"],
                    "price": g["price"],
                    "confidence": g["confidence"],
                    "reason": "This gift is relevant based on your query and preferences."
                }
                for g in gifts
            ]
        }

