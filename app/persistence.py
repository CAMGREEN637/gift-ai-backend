# app/persistence.py
# Database operations using Supabase

from app.database import get_supabase, TABLE_USER_PREFERENCES, TABLE_FEEDBACK, TABLE_INFERRED_PREFERENCES
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)

# ============================================
# User Preferences
# ============================================

def save_preferences(user_id: str, interests: List[str], vibe: List[str]) -> bool:
    """
    Save or update user preferences.

    Args:
        user_id: Unique user identifier
        interests: List of user interests
        vibe: List of user vibe preferences

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        supabase = get_supabase()

        # Check if user preferences already exist
        existing = supabase.table(TABLE_USER_PREFERENCES)\
            .select("user_id")\
            .eq("user_id", user_id)\
            .execute()

        data = {
            "user_id": user_id,
            "interests": interests,
            "vibe": vibe
        }

        if existing.data:
            # Update existing preferences
            result = supabase.table(TABLE_USER_PREFERENCES)\
                .update({"interests": interests, "vibe": vibe})\
                .eq("user_id", user_id)\
                .execute()
            logger.info(f"Updated preferences for user: {user_id}")
        else:
            # Insert new preferences
            result = supabase.table(TABLE_USER_PREFERENCES)\
                .insert(data)\
                .execute()
            logger.info(f"Created preferences for user: {user_id}")

        return True

    except Exception as e:
        logger.error(f"Error saving preferences for user {user_id}: {str(e)}")
        return False


def get_preferences(user_id: str) -> Optional[Dict]:
    """
    Get user preferences.

    Args:
        user_id: Unique user identifier

    Returns:
        Dict with 'interests' and 'vibe' keys, or None if not found
    """
    try:
        supabase = get_supabase()

        result = supabase.table(TABLE_USER_PREFERENCES)\
            .select("interests, vibe")\
            .eq("user_id", user_id)\
            .execute()

        if not result.data:
            return None

        pref = result.data[0]
        return {
            "interests": pref.get("interests", []),
            "vibe": pref.get("vibe", [])
        }

    except Exception as e:
        logger.error(f"Error getting preferences for user {user_id}: {str(e)}")
        return None


# ============================================
# Feedback
# ============================================

def save_feedback(user_id: str, gift_name: str, liked: bool) -> bool:
    """
    Save user feedback on a gift recommendation.

    Args:
        user_id: Unique user identifier
        gift_name: Name of the gift
        liked: Whether user liked the gift

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        supabase = get_supabase()

        data = {
            "user_id": user_id,
            "gift_name": gift_name,
            "liked": liked
        }

        result = supabase.table(TABLE_FEEDBACK)\
            .insert(data)\
            .execute()

        logger.info(f"Saved feedback for user {user_id}: {gift_name} - {'liked' if liked else 'disliked'}")
        return True

    except Exception as e:
        logger.error(f"Error saving feedback for user {user_id}: {str(e)}")
        return False


def get_feedback(user_id: str) -> List[Dict]:
    """
    Get all feedback for a user.

    Args:
        user_id: Unique user identifier

    Returns:
        List of dicts with 'gift_name' and 'liked' keys
    """
    try:
        supabase = get_supabase()

        result = supabase.table(TABLE_FEEDBACK)\
            .select("gift_name, liked")\
            .eq("user_id", user_id)\
            .execute()

        if not result.data:
            return []

        return [
            {
                "gift_name": row["gift_name"],
                "liked": row["liked"]
            }
            for row in result.data
        ]

    except Exception as e:
        logger.error(f"Error getting feedback for user {user_id}: {str(e)}")
        return []


# ============================================
# Inferred Preferences
# ============================================

def update_inferred(user_id: str, category: str, value: str) -> bool:
    """
    Update inferred preferences by incrementing weight or creating new entry.

    Args:
        user_id: Unique user identifier
        category: Category type ('interest' or 'vibe')
        value: The preference value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        supabase = get_supabase()

        # Check if preference already exists
        existing = supabase.table(TABLE_INFERRED_PREFERENCES)\
            .select("id, weight")\
            .eq("user_id", user_id)\
            .eq("category", category)\
            .eq("value", value)\
            .execute()

        if existing.data:
            # Increment weight
            row = existing.data[0]
            new_weight = row["weight"] + 1

            result = supabase.table(TABLE_INFERRED_PREFERENCES)\
                .update({"weight": new_weight})\
                .eq("id", row["id"])\
                .execute()

            logger.info(f"Incremented inferred preference for user {user_id}: {category}/{value} -> weight {new_weight}")
        else:
            # Create new preference
            data = {
                "user_id": user_id,
                "category": category,
                "value": value,
                "weight": 1
            }

            result = supabase.table(TABLE_INFERRED_PREFERENCES)\
                .insert(data)\
                .execute()

            logger.info(f"Created inferred preference for user {user_id}: {category}/{value}")

        return True

    except Exception as e:
        logger.error(f"Error updating inferred preference for user {user_id}: {str(e)}")
        return False


def get_inferred(user_id: str) -> Dict:
    """
    Get all inferred preferences for a user.

    Args:
        user_id: Unique user identifier

    Returns:
        Dict with 'interests' and 'vibe' keys, each containing weighted preferences
    """
    try:
        supabase = get_supabase()

        result = supabase.table(TABLE_INFERRED_PREFERENCES)\
            .select("category, value, weight")\
            .eq("user_id", user_id)\
            .execute()

        interests = {}
        vibe = {}

        for row in result.data:
            if row["category"] == "interest":
                interests[row["value"]] = row["weight"]
            else:  # vibe
                vibe[row["value"]] = row["weight"]

        return {
            "interests": interests,
            "vibe": vibe
        }

    except Exception as e:
        logger.error(f"Error getting inferred preferences for user {user_id}: {str(e)}")
        return {"interests": {}, "vibe": {}}


# ============================================
# Utility Functions
# ============================================

def delete_user_data(user_id: str) -> bool:
    """
    Delete all data for a user (GDPR compliance).

    Args:
        user_id: Unique user identifier

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        supabase = get_supabase()

        # Delete from all tables
        supabase.table(TABLE_USER_PREFERENCES).delete().eq("user_id", user_id).execute()
        supabase.table(TABLE_FEEDBACK).delete().eq("user_id", user_id).execute()
        supabase.table(TABLE_INFERRED_PREFERENCES).delete().eq("user_id", user_id).execute()

        logger.info(f"Deleted all data for user: {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error deleting data for user {user_id}: {str(e)}")
        return False
