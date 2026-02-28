# app/partners_api.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from app.database import get_db
from supabase import Client
import logging

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


class Partner(PartnerBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    last_gift_search_at: Optional[datetime] = None


class GiftHistoryCreate(BaseModel):
    gift_id: Optional[str] = None
    gift_name: str
    gift_url: Optional[str] = None
    price: Optional[float] = None
    occasion: Optional[str] = None
    occasion_date: Optional[date] = None
    budget_max: Optional[int] = None
    delivery_deadline: Optional[date] = None
    purchased: bool = False
    notes: Optional[str] = None
    rating: Optional[int] = None


# Helper to get user_id (temporary - integrate with your auth)
def get_current_user_id(db: Client = Depends(get_db)) -> str:
    # TODO: Get from JWT/session token
    # For now, return test user
    return "test_user_123"


# Endpoints
@router.post("/", response_model=dict)
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

        return response.data[0]
    except Exception as e:
        logger.error("Error creating partner: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[dict])
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

        return response.data
    except Exception as e:
        logger.error("Error listing partners: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{partner_id}", response_model=dict)
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


@router.put("/{partner_id}", response_model=dict)
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

        return {"status": "deleted", "partner_id": partner_id}
    except Exception as e:
        logger.error("Error deleting partner: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{partner_id}/gifts")
async def add_gift_to_history(
        partner_id: str,
        gift: GiftHistoryCreate,
        user_id: str = Depends(get_current_user_id),
        db: Client = Depends(get_db)
):
    """Record a gift recommendation or purchase"""
    try:
        # Verify partner exists
        partner_response = db.table("partners") \
            .select("id") \
            .eq("id", partner_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if not partner_response.data:
            raise HTTPException(status_code=404, detail="Partner not found")

        # Add gift to history
        data = gift.dict()
        data["partner_id"] = partner_id
        data["user_id"] = user_id

        response = db.table("partner_gift_history").insert(data).execute()

        # Update partner's last_gift_date if purchased
        if gift.purchased:
            db.table("partners") \
                .update({"last_gift_date": datetime.now().isoformat()}) \
                .eq("id", partner_id) \
                .execute()

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