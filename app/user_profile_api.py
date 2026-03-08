# app/user_profile_api.py

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from app.database import get_db
from supabase import Client
import logging
import jwt
import os
import json
import requests  # Added for JWKS fetching

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


# --- JWT Auth (Updated for ES256 & JWKS) ---
def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """Extract user ID from Supabase JWT token (supports ES256)"""
    if not authorization or not authorization.startswith("Bearer "):
        logger.error("❌ No Authorization header provided")
        raise HTTPException(status_code=401, detail="Not authenticated - No auth header")

    token = authorization.replace("Bearer ", "")
    logger.info("🔑 Received token (first 20 chars): %s..." % token[:20])

    try:
        # Get Supabase project ref from URL
        supabase_url = os.getenv("SUPABASE_URL")
        if not supabase_url:
            raise HTTPException(status_code=500, detail="SUPABASE_URL not configured")

        # Extract project reference (e.g., "eimtwdqiwhkgbfmtonkt")
        project_ref = supabase_url.replace("https://", "").split(".")[0]

        # Fetch JWKS (JSON Web Key Set) from Supabase
        jwks_url = f"https://{project_ref}.supabase.co/auth/v1/jwks"
        jwks_response = requests.get(jwks_url)
        jwks = jwks_response.json()

        # Decode header to get key ID
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        if not kid:
            raise HTTPException(status_code=401, detail="Invalid token - no key ID")

        # Find the matching key
        key = None
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid:
                key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)
                break

        if not key:
            raise HTTPException(status_code=401, detail="Invalid token - key not found")

        # Decode and verify token
        payload = jwt.decode(
            token,
            key=key,
            algorithms=["ES256"],  # New algorithm
            audience="authenticated",
            options={"verify_aud": True}
        )

        user_id = payload.get("sub")

        if not user_id:
            logger.error("❌ Token valid but no user ID in payload")
            raise HTTPException(status_code=401, detail="Invalid token - no user ID")

        logger.info("✅ Authenticated user: %s" % user_id)
        return user_id

    except jwt.ExpiredSignatureError:
        logger.error("❌ Token expired")
        raise HTTPException(status_code=401, detail="Token expired - please sign in again")
    except jwt.InvalidTokenError as e:
        logger.error("❌ Invalid token: %s" % str(e))
        raise HTTPException(status_code=401, detail="Invalid token")
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
            .single() \
            .execute()

        if not response.data:
            # Create profile if doesn't exist
            new_profile = {
                "user_id": user_id,
                "saved_recipients": []
            }
            response = db.table("user_profiles").insert(new_profile).execute()
            return response.data[0]

        return response.data

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
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if not response.data:
            return []

        recipients = response.data.get("saved_recipients", [])
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
        # Get current profile
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        recipients = response.data.get("saved_recipients", []) if response.data else []

        # Generate ID if not provided
        if not recipient.id:
            import uuid
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
        from datetime import datetime
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
            .single() \
            .execute()

        recipients = response.data.get("saved_recipients", []) if response.data else []

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
            .single() \
            .execute()

        recipients = response.data.get("saved_recipients", []) if response.data else []

        # Find and update
        index = next((i for i, r in enumerate(recipients) if r.get("id") == recipient_id), None)

        if index is None:
            raise HTTPException(status_code=404, detail="Recipient not found")

        # Update recipient
        recipient_dict = recipient.dict(exclude_none=True)
        recipient_dict["id"] = recipient_id

        # Convert dates to strings
        if recipient_dict.get("birthday"):
            recipient_dict["birthday"] = str(recipient_dict["birthday"])
        if recipient_dict.get("anniversary"):
            recipient_dict["anniversary"] = str(recipient_dict["anniversary"])

        recipients[index] = {**recipients[index], **recipient_dict}

        # Save
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
            .single() \
            .execute()

        recipients = response.data.get("saved_recipients", []) if response.data else []

        # Filter out the recipient
        new_recipients = [r for r in recipients if r.get("id") != recipient_id]

        if len(new_recipients) == len(recipients):
            raise HTTPException(status_code=404, detail="Recipient not found")

        # Save
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
        "message": "Auth is working!"
    }