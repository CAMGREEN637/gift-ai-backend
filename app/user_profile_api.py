# app/user_profile_api.py

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
import logging
import jwt
import os
import time
from app.database import get_db
from supabase import Client
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user-profile", tags=["user-profile"])


# --- Models ---
class Recipient(BaseModel):
    id: Optional[str] = None
    name: str
    relationship: Optional[str] = None
    birthday: Optional[date] = None
    anniversary: Optional[date] = None
    interests: List[str] = []
    categories: List[str] = []
    vibe: List[str] = []
    personality_traits: List[str] = []
    experience_level: Optional[str] = None
    preferred_price_range: Optional[str] = None
    notes: Optional[str] = None
    lastGiftDate: Optional[date] = None


class UserProfile(BaseModel):
    email: Optional[str] = None
    preferred_price_range: Optional[str] = None
    saved_recipients: List[dict] = []


# --- Simplified JWT Auth ---
def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """Extract user ID from Supabase JWT token - simplified decoding"""
    if not authorization or not authorization.startswith("Bearer "):
        logger.error("❌ No Authorization header provided")
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.replace("Bearer ", "")
    logger.info("🔑 Received token (first 20 chars): %s..." % token[:20])

    try:
        # Decode without verification to get the payload
        # Security Note: Verification happens at the Database layer via Supabase RLS
        unverified_payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": True}
        )

        user_id = unverified_payload.get("sub")

        if not user_id:
            logger.error("❌ No user ID (sub) found in token payload")
            raise HTTPException(status_code=401, detail="Invalid token - no user ID")

        # Manual expiration check (backup to verify_exp)
        exp = unverified_payload.get("exp")
        if exp and time.time() > exp:
            logger.error("❌ Token expired based on exp claim")
            raise HTTPException(status_code=401, detail="Token expired")

        logger.info("✅ Extracted user ID: %s" % user_id)
        return user_id

    except jwt.ExpiredSignatureError:
        logger.error("❌ Token expired signature")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.DecodeError as e:
        logger.error("❌ JWT Decode error: %s" % str(e))
        raise HTTPException(status_code=401, detail="Invalid token format")
    except Exception as e:
        logger.error("❌ Auth error: %s" % str(e))
        raise HTTPException(status_code=401, detail="Authentication failed")


# --- Endpoints ---
@router.get("/")
async def get_profile(
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Get user's profile"""
    try:
        response = db.table("user_profiles") \
            .select("*") \
            .eq("user_id", user_id) \
            .execute()

        # If no profile, create one
        if not response.data or len(response.data) == 0:
            new_profile = {
                "user_id": user_id,
                "saved_recipients": []
            }
            response = db.table("user_profiles").insert(new_profile).execute()
            return response.data[0]

        return response.data[0]

    except Exception as e:
        logger.error("Error getting profile: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recipients")
async def get_recipients(
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Get all saved recipients"""
    try:
        # Don't use .single() - it throws error if no rows
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        # Check if profile exists
        if not response.data or len(response.data) == 0:
            logger.info("No profile found for user %s, returning empty list" % user_id)
            return []

        recipients = response.data[0].get("saved_recipients", [])
        logger.info("Loaded %d recipients for user %s" % (len(recipients), user_id))
        return recipients

    except Exception as e:
        logger.error("Error getting recipients: %s" % str(e))
        return []


@router.post("/recipients")
async def add_recipient(
        recipient: Recipient,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Add a new gift recipient"""
    try:
        # Get current profile (don't use .single())
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        # If no profile exists, create one
        if not response.data or len(response.data) == 0:
            logger.info("Creating new profile for user %s" % user_id)

            # Generate recipient ID
            recipient_id = str(uuid.uuid4())

            # Build recipient dict
            recipient_dict = recipient.dict(exclude_none=True)
            recipient_dict["id"] = recipient_id

            # Convert dates
            if recipient_dict.get("birthday"):
                recipient_dict["birthday"] = str(recipient_dict["birthday"])
            if recipient_dict.get("anniversary"):
                recipient_dict["anniversary"] = str(recipient_dict["anniversary"])
            if recipient_dict.get("lastGiftDate"):
                recipient_dict["lastGiftDate"] = str(recipient_dict["lastGiftDate"])

            # Add timestamp
            recipient_dict["createdAt"] = datetime.now().isoformat()

            # Create new profile with this recipient
            new_profile = {
                "user_id": user_id,
                "saved_recipients": [recipient_dict]
            }

            db.table("user_profiles").insert(new_profile).execute()
            logger.info("Created new profile and added recipient: %s" % recipient.name)
            return recipient_dict

        # Profile exists, add to it
        recipients = response.data[0].get("saved_recipients", [])

        # Generate ID if not provided
        if not recipient.id:
            recipient.id = str(uuid.uuid4())

        # Convert to dict
        recipient_dict = recipient.dict(exclude_none=True)

        # Convert dates to strings
        if recipient_dict.get("birthday"):
            recipient_dict["birthday"] = str(recipient_dict["birthday"])
        if recipient_dict.get("anniversary"):
            recipient_dict["anniversary"] = str(recipient_dict["anniversary"])
        if recipient_dict.get("lastGiftDate"):
            recipient_dict["lastGiftDate"] = str(recipient_dict["lastGiftDate"])

        # Add timestamp
        recipient_dict["createdAt"] = datetime.now().isoformat()

        # Check if recipient with same name exists
        existing_index = next(
            (i for i, r in enumerate(recipients) if r.get("name", "").lower() == recipient.name.lower()),
            None
        )

        if existing_index is not None:
            # Update existing
            recipients[existing_index] = {**recipients[existing_index], **recipient_dict}
            logger.info("Updated recipient: %s" % recipient.name)
        else:
            # Add new
            recipients.append(recipient_dict)
            logger.info("Added new recipient: %s" % recipient.name)

        # Save back to database
        db.table("user_profiles").update({
            "saved_recipients": recipients
        }).eq("user_id", user_id).execute()

        return recipient_dict

    except Exception as e:
        logger.error("Error adding recipient: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recipients/{recipient_id}")
async def get_recipient(
        recipient_id: str,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Get a specific recipient by ID"""
    try:
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        if not response.data or len(response.data) == 0:
             raise HTTPException(status_code=404, detail="Recipient not found")

        recipients = response.data[0].get("saved_recipients", [])

        recipient = next((r for r in recipients if r.get("id") == recipient_id), None)

        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")

        return recipient

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting recipient: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/recipients/{recipient_id}")
async def update_recipient(
        recipient_id: str,
        recipient: Recipient,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Update a recipient"""
    try:
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        if not response.data or len(response.data) == 0:
             raise HTTPException(status_code=404, detail="Recipient not found")

        recipients = response.data[0].get("saved_recipients", [])

        index = next((i for i, r in enumerate(recipients) if r.get("id") == recipient_id), None)

        if index is None:
            raise HTTPException(status_code=404, detail="Recipient not found")

        recipient_dict = recipient.dict(exclude_none=True)
        recipient_dict["id"] = recipient_id

        if recipient_dict.get("birthday"):
            recipient_dict["birthday"] = str(recipient_dict["birthday"])
        if recipient_dict.get("anniversary"):
            recipient_dict["anniversary"] = str(recipient_dict["anniversary"])

        recipients[index] = {**recipients[index], **recipient_dict}

        db.table("user_profiles").update({
            "saved_recipients": recipients
        }).eq("user_id", user_id).execute()

        logger.info("Updated recipient %s for user %s" % (recipient_id, user_id))
        return recipients[index]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating recipient: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/recipients/{recipient_id}")
async def delete_recipient(
        recipient_id: str,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Delete a recipient"""
    try:
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        if not response.data or len(response.data) == 0:
             raise HTTPException(status_code=404, detail="Recipient not found")

        recipients = response.data[0].get("saved_recipients", [])

        new_recipients = [r for r in recipients if r.get("id") != recipient_id]

        if len(new_recipients) == len(recipients):
            raise HTTPException(status_code=404, detail="Recipient not found")

        db.table("user_profiles").update({
            "saved_recipients": new_recipients
        }).eq("user_id", user_id).execute()

        logger.info("Deleted recipient %s for user %s" % (recipient_id, user_id))
        return {"status": "deleted", "recipient_id": recipient_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting recipient: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test-auth")
async def test_auth(user_id: str = Depends(get_current_user_id)):
    """Test endpoint to verify authentication"""
    return {
        "status": "authenticated",
        "user_id": user_id,
        "message": "Simplified auth is working!"
    }