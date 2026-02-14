# app/ai_categorization.py
# AI-powered product categorization using OpenAI

import json
import logging
from openai import OpenAI
import os
from dotenv import load_dotenv
from app.admin_models import AICategorizationResponse, RecipientInfo

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CATEGORIZATION_PROMPT_TEMPLATE = """Based on this product:
Title: {product_name}
Description: {description}
Brand: {brand}

Suggest appropriate values for a gift recommendation database.

Return ONLY valid JSON (no markdown, no explanation, no code blocks):
{{
  "categories": [],
  "interests": [],
  "occasions": [],
  "recipient": {{
    "gender": [],
    "relationship": []
  }},
  "vibe": [],
  "personality_traits": [],
  "experience_level": ""
}}

STRICT Guidelines (follow these limits exactly):
- categories: Pick MAXIMUM 2 from [tech, home, kitchen, fashion, beauty, fitness, outdoors, hobby, book, experiences]
- interests: Pick MAXIMUM 5 from [coffee, cooking, baking, fitness, running, yoga, gaming, photography, music, travel, reading, art, gardening, cycling, hiking, camping, movies, wine, cocktails, tea, fashion, skincare, makeup]
- occasions: Pick MAXIMUM 4 from [birthday, anniversary, valentines, holiday, christmas, wedding, engagement, graduation, just_because]
- recipient.gender: Pick 1-3 from [male, female, unisex]
- recipient.relationship: Pick 1-6 from [partner, spouse, boyfriend, girlfriend, friend, family]
- vibe: Pick MAXIMUM 3 from [romantic, practical, luxury, fun, sentimental, creative, cozy, adventurous, minimalist]
- personality_traits: Pick MAXIMUM 3 from [introverted, extroverted, analytical, creative, sentimental, adventurous, organized, relaxed, curious]
- experience_level: Pick EXACTLY 1 from [beginner, enthusiast, expert]

Rules:
1. Be selective - choose only the MOST relevant categories
2. Consider who would actually use/appreciate this product
3. Think about typical gift-giving scenarios
4. Match experience_level to product complexity
5. Return ONLY the JSON, nothing else"""


async def categorize_product(
    product_name: str,
    description: str = "",
    brand: str = ""
) -> AICategorizationResponse:
    """
    Use OpenAI to suggest product categories and attributes.

    Args:
        product_name: Product name/title
        description: Product description
        brand: Brand name

    Returns:
        AICategorizationResponse with suggested categories

    Raises:
        ValueError: If OpenAI API fails or returns invalid JSON
    """
    logger.info(f"Categorizing product: {product_name[:50]}...")

    # Build prompt
    prompt = CATEGORIZATION_PROMPT_TEMPLATE.format(
        product_name=product_name,
        description=description[:500],  # Limit description length
        brand=brand or "Unknown"
    )

    try:
        # Call OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a gift categorization expert. Return only valid JSON with no markdown formatting or explanations."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,  # Lower temperature for more consistent results
            max_tokens=500
        )

        # Extract content
        content = response.choices[0].message.content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        logger.debug(f"OpenAI response: {content}")

        # Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {content}")
            raise ValueError(f"OpenAI returned invalid JSON: {str(e)}")

        # Validate and construct response
        categorization = AICategorizationResponse(
            categories=data.get("categories", [])[:2],  # Enforce max 2
            interests=data.get("interests", [])[:5],  # Enforce max 5
            occasions=data.get("occasions", [])[:4],  # Enforce max 4
            recipient=RecipientInfo(
                gender=data.get("recipient", {}).get("gender", [])[:3],
                relationship=data.get("recipient", {}).get("relationship", [])[:6]
            ),
            vibe=data.get("vibe", [])[:3],  # Enforce max 3
            personality_traits=data.get("personality_traits", [])[:3],  # Enforce max 3
            experience_level=data.get("experience_level", "beginner")
        )

        logger.info(f"Categorization successful: {len(categorization.categories)} categories, {len(categorization.interests)} interests")

        return categorization

    except Exception as e:
        logger.error(f"AI categorization failed: {str(e)}")
        # Return safe defaults if AI fails
        return AICategorizationResponse(
            categories=[],
            interests=[],
            occasions=["just_because"],
            recipient=RecipientInfo(gender=["unisex"], relationship=["friend"]),
            vibe=["practical"],
            personality_traits=[],
            experience_level="beginner"
        )


def validate_categorization(categorization: dict) -> dict:
    """
    Validate and clean categorization data.

    Ensures:
    - Arrays don't exceed max limits
    - Values are from allowed lists
    - Required fields are present
    """
    # Valid values for each field
    VALID_CATEGORIES = ["tech", "home", "kitchen", "fashion", "beauty", "fitness", "outdoors", "hobby", "book", "experiences"]
    VALID_INTERESTS = ["coffee", "cooking", "baking", "fitness", "running", "yoga", "gaming", "photography", "music", "travel", "reading", "art", "gardening", "cycling", "hiking", "camping", "movies", "wine", "cocktails", "tea", "fashion", "skincare", "makeup"]
    VALID_OCCASIONS = ["birthday", "anniversary", "valentines", "holiday", "christmas", "wedding", "engagement", "graduation", "just_because"]
    VALID_GENDERS = ["male", "female", "unisex"]
    VALID_RELATIONSHIPS = ["partner", "spouse", "boyfriend", "girlfriend", "friend", "family"]
    VALID_VIBES = ["romantic", "practical", "luxury", "fun", "sentimental", "creative", "cozy", "adventurous", "minimalist"]
    VALID_TRAITS = ["introverted", "extroverted", "analytical", "creative", "sentimental", "adventurous", "organized", "relaxed", "curious"]
    VALID_EXPERIENCE = ["beginner", "enthusiast", "expert"]

    def filter_valid(values: list, valid_list: list, max_count: int) -> list:
        """Filter to only valid values and enforce max count."""
        filtered = [v for v in values if v in valid_list]
        return filtered[:max_count]

    # Clean and validate
    cleaned = {
        "categories": filter_valid(categorization.get("categories", []), VALID_CATEGORIES, 2),
        "interests": filter_valid(categorization.get("interests", []), VALID_INTERESTS, 5),
        "occasions": filter_valid(categorization.get("occasions", []), VALID_OCCASIONS, 4),
        "recipient": {
            "gender": filter_valid(categorization.get("recipient", {}).get("gender", []), VALID_GENDERS, 3),
            "relationship": filter_valid(categorization.get("recipient", {}).get("relationship", []), VALID_RELATIONSHIPS, 6)
        },
        "vibe": filter_valid(categorization.get("vibe", []), VALID_VIBES, 3),
        "personality_traits": filter_valid(categorization.get("personality_traits", []), VALID_TRAITS, 3),
        "experience_level": categorization.get("experience_level", "beginner") if categorization.get("experience_level") in VALID_EXPERIENCE else "beginner"
    }

    return cleaned
