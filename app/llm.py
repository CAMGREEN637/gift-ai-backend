# app/llm.py
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

    IMPORTANT:
    - Retrieval owns product data (image_url, product_url, description, etc.)
    - LLM ONLY provides explanations
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

    # ---------- Build gift context (LLM sees only explainable fields) ----------

    gift_context = ""
    for gift in gifts:
        gift_context += f"""
Name: {gift.get('name')}
Price: ${gift.get('price')}
Confidence: {gift.get('confidence')}
Ranking reasons: {', '.join(gift.get('ranking_reasons', [])) or 'Relevant to the search'}
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
- Use ranking reasons verbatim
- Do NOT invent product details
- Do NOT invent preferences
- Keep explanations concise and warm
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

    # ---------- Parse response safely ----------

    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {
            "intro": "Here are a few thoughtful gift ideas you might like:",
            "gifts": []
        }

    # ---------- MERGE explanations INTO original gifts ----------

    explanations_by_name = {
        g["name"]: g.get("reason")
        for g in parsed.get("gifts", [])
        if isinstance(g, dict) and "name" in g
    }

    enriched_gifts = []

    for gift in gifts:
        enriched = {
            **gift,  # ← THIS PRESERVES image_url, product_url, description
            "reason": explanations_by_name.get(
                gift.get("name"),
                "This gift is a strong match based on your search and preferences."
            )
        }
        enriched_gifts.append(enriched)

    return {
        "intro": parsed.get(
            "intro",
            "Here are some thoughtful gift ideas based on your request."
        ),
        "gifts": enriched_gifts,
    }

