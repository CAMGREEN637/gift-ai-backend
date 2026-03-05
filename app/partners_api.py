# app/partners_api.py

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from app.database import get_db
from supabase import Client
import logging
import jwt
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/partners", tags=["partners"])


# Pydantic Models
class PartnerBase(BaseModel):
    name: str
    relationship: Optional[str] = None
    gender: Optional[str] = None
    interests: Optional[List[str]] = []
    categories: Optional[List[str]] = []
    vibe: Optional[List[str]] = []
    personality_traits: Optional[List[str]] = []
    experience_level: Optional[str] = None
    birthday: Optional[date] = None
    anniversary: Optional[date] = None
    preferred_price_range: Optional[str] = None
    notes: Optional[str] = None


class PartnerCreate(PartnerBase):
    pass


class PartnerUpdate(PartnerBase):
    pass


# JWT-based authentication
def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """
    Extract user ID from Supabase JWT token.

    Raises:
        HTTPException: If token is invalid or missing
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.replace("Bearer ", "")

    try:
        # Get Supabase JWT secret from environment
        jwt_secret = os.getenv("SUPABASE_JWT_SECRET")

        if not jwt_secret:
            logger.error("SUPABASE_JWT_SECRET not set!")
            raise HTTPException(status_code=500, detail="Server configuration error")

        # Decode JWT token
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated"
        )

        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing user ID")

        logger.info("Authenticated user: %s" % user_id)
        return user_id

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error("Invalid token: %s" % str(e))
        raise HTTPException(status_code=401, detail="Invalid token")


# Endpoints with real auth
@router.post("/")
async def create_partner(
        partner: PartnerCreate,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Create a new partner profile"""
    try:
        data = partner.dict()
        data["user_id"] = user_id

        response = db.table("partners").insert(data).execute()

        if not response.data:
            raise HTTPException(status_code=400, detail="Failed to create partner")

        logger.info("Created partner for user %s: %s" % (user_id, partner.name))
        return response.data[0]
    except Exception as e:
        logger.error("Error creating partner: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def list_partners(
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Get all partners for the current user"""
    try:
        response = db.table("partners") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("name") \
            .execute()

        logger.info("Loaded %d partners for user %s" % (len(response.data), user_id))
        return response.data
    except Exception as e:
        logger.error("Error listing partners: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{partner_id}")
async def get_partner(
        partner_id: str,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Get a specific partner by ID"""
    try:
        response = db.table("partners") \
            .select("*") \
            .eq("id", partner_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Partner not found")

        return response.data
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Partner not found")
        logger.error("Error getting partner: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{partner_id}")
async def update_partner(
        partner_id: str,
        partner: PartnerUpdate,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Update a partner profile"""
    try:
        data = partner.dict(exclude_unset=True)

        response = db.table("partners") \
            .update(data) \
            .eq("id", partner_id) \
            .eq("user_id", user_id) \
            .execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Partner not found")

        logger.info("Updated partner %s for user %s" % (partner_id, user_id))
        return response.data[0]
    except Exception as e:
        logger.error("Error updating partner: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{partner_id}")
async def delete_partner(
        partner_id: str,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Delete a partner profile"""
    try:
        response = db.table("partners") \
            .delete() \
            .eq("id", partner_id) \
            .eq("user_id", user_id) \
            .execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Partner not found")

        logger.info("Deleted partner %s for user %s" % (partner_id, user_id))
        return {"status": "deleted", "partner_id": partner_id}
    except Exception as e:
        logger.error("Error deleting partner: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


# Gift history endpoints
@router.post("/{partner_id}/gifts")
async def add_gift_to_history(
        partner_id: str,
        gift: dict,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Record a gift recommendation or purchase"""
    try:
        partner_response = db.table("partners") \
            .select("id") \
            .eq("id", partner_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if not partner_response.data:
            raise HTTPException(status_code=404, detail="Partner not found")

        gift["partner_id"] = partner_id
        gift["user_id"] = user_id

        response = db.table("partner_gift_history").insert(gift).execute()
        return response.data[0]
    except Exception as e:
        logger.error("Error adding gift to history: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{partner_id}/gifts")
async def get_partner_gift_history(
        partner_id: str,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Get all gifts for this partner"""
    try:
        response = db.table("partner_gift_history") \
            .select("*") \
            .eq("partner_id", partner_id) \
            .eq("user_id", user_id) \
            .order("recommended_at", desc=True) \
            .execute()

        return response.data
    except Exception as e:
        logger.error("Error getting gift history: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))