from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List, Any, Dict, Tuple
from datetime import date
import logging
import jwt
import os
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
    relationship_stage: Optional[str] = None
    birthday: Optional[date] = None
    anniversary: Optional[date] = None
    interests: List[str] = []
    preferred_price_range: Optional[str] = None
    notes: Optional[str] = None
    lastGiftDate: Optional[date] = None


class SavedGift(BaseModel):
    """A single gift saved to a recipient's profile."""
    id: Optional[str] = None
    name: str
    display_name: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    reason: Optional[str] = None
    occasion: Optional[str] = None
    saved_at: Optional[str] = None


class SaveGiftsRequest(BaseModel):
    """Save one or more gifts to a recipient. Creates the recipient if needed."""
    recipient_name: str
    recipient_id: Optional[str] = None
    gifts: List[Dict[str, Any]]
    occasion: Optional[str] = None


class UserProfile(BaseModel):
    email: Optional[str] = None
    preferred_price_range: Optional[str] = None
    saved_recipients: List[dict] = []


# --- Simplified JWT Auth ---
def get_current_user(authorization: Optional[str] = Header(None)) -> Tuple[str, str]:
    """Returns a tuple of (user_id, email) from the JWT.

    Requires SUPABASE_JWT_SECRET to be set as an environment variable in Railway
    (Settings → Variables). Without it the server will reject all authenticated
    requests rather than silently accept forged tokens.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    # SUPABASE_JWT_SECRET must be set in Railway environment variables.
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    if not jwt_secret:
        logger.error("SUPABASE_JWT_SECRET is not set — cannot verify JWT signatures")
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: JWT secret not set"
        )

    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated"
        )
        user_id = payload.get("sub")
        email = payload.get("email", "")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token - no user ID")

        return user_id, email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="Invalid token format")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed")


# --- Helpers ---
def _serialize_recipient(recipient_dict: dict) -> dict:
    for date_field in ("birthday", "anniversary", "lastGiftDate"):
        if recipient_dict.get(date_field):
            recipient_dict[date_field] = str(recipient_dict[date_field])
    return recipient_dict


def _get_or_create_profile(user_id: str, email: str, db: Client) -> dict:
    """Fetch the user profile, creating it if it doesn't exist, storing email."""
    response = db.table("user_profiles") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    if not response.data or len(response.data) == 0:
        new_profile = {
            "user_id": user_id,
            "email": email,  # Added email here
            "saved_recipients": []
        }
        result = db.table("user_profiles").insert(new_profile).execute()
        return result.data[0]

    return response.data[0]


# --- Endpoints ---

@router.get("/")
async def get_profile(
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, email = auth
    try:
        return _get_or_create_profile(user_id, email, db)
    except Exception as e:
        logger.error("Error getting profile: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recipients")
async def get_recipients(
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, _ = auth
    try:
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        if not response.data or len(response.data) == 0:
            return []

        recipients = response.data[0].get("saved_recipients", [])
        return recipients
    except Exception as e:
        logger.error("Error getting recipients: %s" % str(e))
        return []


@router.post("/recipients")
async def add_recipient(
        recipient: Recipient,
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, email = auth
    try:
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        recipient_id = recipient.id or str(uuid.uuid4())
        recipient_dict = recipient.dict(exclude_none=True)
        recipient_dict["id"] = recipient_id
        recipient_dict["createdAt"] = datetime.now().isoformat()
        recipient_dict.setdefault("saved_gifts", [])
        recipient_dict = _serialize_recipient(recipient_dict)

        if not response.data or len(response.data) == 0:
            # When creating a new profile, also capture email from the JWT
            new_profile = {
                "user_id": user_id,
                "email": email,  # Added email here
                "saved_recipients": [recipient_dict]
            }
            db.table("user_profiles").insert(new_profile).execute()
            return recipient_dict

        recipients = response.data[0].get("saved_recipients", [])
        existing_index = next(
            (i for i, r in enumerate(recipients)
             if r.get("name", "").lower() == recipient.name.lower()),
            None
        )

        if existing_index is not None:
            # Preserve saved_gifts when updating
            existing_gifts = recipients[existing_index].get("saved_gifts", [])
            recipients[existing_index] = {**recipients[existing_index], **recipient_dict}
            recipients[existing_index]["saved_gifts"] = existing_gifts
        else:
            recipients.append(recipient_dict)

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
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, _ = auth
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
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, _ = auth
    try:
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Recipient not found")

        recipients = response.data[0].get("saved_recipients", [])
        index = next(
            (i for i, r in enumerate(recipients) if r.get("id") == recipient_id), None
        )

        if index is None:
            raise HTTPException(status_code=404, detail="Recipient not found")

        recipient_dict = recipient.dict(exclude_none=True)
        recipient_dict["id"] = recipient_id
        recipient_dict = _serialize_recipient(recipient_dict)

        # Always preserve saved_gifts on PUT
        existing_gifts = recipients[index].get("saved_gifts", [])
        recipients[index] = {**recipients[index], **recipient_dict}
        recipients[index]["saved_gifts"] = existing_gifts

        db.table("user_profiles").update({
            "saved_recipients": recipients
        }).eq("user_id", user_id).execute()

        return recipients[index]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating recipient: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/recipients/{recipient_id}")
async def delete_recipient(
        recipient_id: str,
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, _ = auth
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

        return {"status": "deleted", "recipient_id": recipient_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting recipient: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/saved-gifts")
async def save_gifts(
        body: SaveGiftsRequest,
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, email = auth
    try:
        profile = _get_or_create_profile(user_id, email, db)
        recipients = profile.get("saved_recipients", [])

        # Find the recipient
        recipient_index = None
        if body.recipient_id:
            recipient_index = next(
                (i for i, r in enumerate(recipients) if r.get("id") == body.recipient_id),
                None
            )
        if recipient_index is None:
            recipient_index = next(
                (i for i, r in enumerate(recipients)
                 if r.get("name", "").lower() == body.recipient_name.lower()),
                None
            )

        # Create recipient entry if not found
        if recipient_index is None:
            new_recipient = {
                "id": body.recipient_id or str(uuid.uuid4()),
                "name": body.recipient_name,
                "createdAt": datetime.now().isoformat(),
                "saved_gifts": [],
            }
            recipients.append(new_recipient)
            recipient_index = len(recipients) - 1

        recipient = recipients[recipient_index]
        existing_gifts: list = recipient.get("saved_gifts", [])

        # Deduplicate by product_url, fall back to name
        def is_duplicate(new_gift: dict) -> bool:
            new_url = new_gift.get("product_url") or new_gift.get("link")
            for eg in existing_gifts:
                if new_url and eg.get("product_url") == new_url:
                    return True
                if eg.get("name", "").lower() == new_gift.get("name", "").lower():
                    return True
            return False

        added = []
        for gift in body.gifts:
            if is_duplicate(gift):
                continue
            entry = {
                "id": str(uuid.uuid4()),
                "name": gift.get("name", ""),
                "display_name": gift.get("display_name"),
                "price": gift.get("price"),
                "image_url": gift.get("image_url"),
                "product_url": gift.get("product_url") or gift.get("link"),
                "reason": gift.get("reason"),
                "occasion": body.occasion,
                "saved_at": datetime.now().isoformat(),
            }
            existing_gifts.append(entry)
            added.append(entry)

        recipients[recipient_index]["saved_gifts"] = existing_gifts

        db.table("user_profiles").update({
            "saved_recipients": recipients
        }).eq("user_id", user_id).execute()

        logger.info(
            "Saved %d gift(s) for recipient '%s' (user %s)"
            % (len(added), body.recipient_name, user_id)
        )
        return {
            "saved": len(added),
            "skipped_duplicates": len(body.gifts) - len(added),
            "gifts": added,
            "recipient_id": recipients[recipient_index]["id"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error saving gifts: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/saved-gifts/{recipient_id}/{gift_id}")
async def unsave_gift(
        recipient_id: str,
        gift_id: str,
        auth: Tuple[str, str] = Depends(get_current_user),
        db: Client = Depends(get_db)
):
    user_id, _ = auth
    try:
        response = db.table("user_profiles") \
            .select("saved_recipients") \
            .eq("user_id", user_id) \
            .execute()

        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Profile not found")

        recipients = response.data[0].get("saved_recipients", [])
        r_index = next(
            (i for i, r in enumerate(recipients) if r.get("id") == recipient_id), None
        )
        if r_index is None:
            raise HTTPException(status_code=404, detail="Recipient not found")

        saved_gifts = recipients[r_index].get("saved_gifts", [])
        new_gifts = [g for g in saved_gifts if g.get("id") != gift_id]

        if len(new_gifts) == len(saved_gifts):
            raise HTTPException(status_code=404, detail="Gift not found")

        recipients[r_index]["saved_gifts"] = new_gifts
        db.table("user_profiles").update({
            "saved_recipients": recipients
        }).eq("user_id", user_id).execute()

        return {"status": "removed", "gift_id": gift_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error unsaving gift: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test-auth")
async def test_auth(auth: Tuple[str, str] = Depends(get_current_user)):
    user_id, email = auth
    return {"status": "authenticated", "user_id": user_id, "email": email}