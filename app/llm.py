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
) -> tuple[Dict, int]:
   """
   Generates a natural language explanation of gift recommendations.
   Preserves ranking detail AND all gift fields for frontend rendering.

   Returns:
       Tuple of (response_data, tokens_used)
   """


   # ---------- Preference context ----------


   if preferences:
       pref_text = f"""
User preferences (IMPORTANT):
- Interests: {preferences.get("interests", [])}
- Vibe: {preferences.get("vibe", [])}
"""
   else:
       pref_text = "User did not provide explicit preferences."


   # ---------- Gift context for LLM ----------


   gift_context = ""
   for gift in gifts:
       gift_context += f"""
Name: {gift['name']}
Price: ${gift['price']}
Confidence: {gift['confidence']}
Ranking reasons: {', '.join(gift.get('ranking_reasons', [])) or 'General relevance'}
Description: {gift.get('description', '')}
---
"""


   system_prompt = f"""
You are a thoughtful gift recommendation assistant.


{pref_text}


Rules:
- Do NOT invent facts
- Do NOT invent preferences
- Use ranking reasons verbatim
- Treat higher confidence gifts as stronger recommendations
"""


   user_prompt = f"""
User query: "{query}"


Return STRICT JSON:


{{
 "intro": "one short sentence",
 "gifts": [
   {{
     "name": "gift name",
     "reason": "1–2 sentence explanation"
   }}
 ]
}}


Gift options:
{gift_context}
"""


   response = client.chat.completions.create(
       model="gpt-4o-mini",
       messages=[
           {"role": "system", "content": system_prompt},
           {"role": "user", "content": user_prompt}
       ],
       temperature=0.4
   )

   # Extract token usage from response
   tokens_used = response.usage.total_tokens if response.usage else 0

   content = response.choices[0].message.content


   try:
       parsed = json.loads(content)
   except Exception:
       parsed = {"intro": "", "gifts": []}


   # ---------- CRITICAL FIX ----------
   # Explicitly map all necessary fields, converting 'link' to 'product_url'


   enriched = []


   for original in gifts:
       llm_match = next(
           (g for g in parsed.get("gifts", []) if g["name"] == original["name"]),
           None
       )

       # Explicitly create the enriched gift with all necessary fields
       enriched.append({
           "name": original["name"],
           "price": original["price"],
           "confidence": original.get("confidence", 0),
           "description": original.get("description", ""),
           "image_url": original.get("image_url", ""),
           "product_url": original.get("link", ""),  # Map 'link' to 'product_url'
           "ranking_reasons": original.get("ranking_reasons", []),
           "reason": llm_match.get("reason") if llm_match else
                     "This gift matches your request based on relevance.",
       })


   response_data = {
       "intro": parsed.get(
           "intro",
           "Here are some thoughtful gift ideas for you:"
       ),
       "gifts": enriched
   }

   return response_data, tokens_used