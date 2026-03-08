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
import requests
from jwt.algorithms import ECAlgorithm  # Specific import for ES256 support

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

# --- JWT Auth (Hybrid ES256 & HS256 Support) ---
def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    """Extract user ID from Supabase JWT token (supports ES256 and HS256)"""
    if not authorization or not authorization.startswith("Bearer "):
        logger.error("❌ No Authorization header provided")
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.replace("Bearer ", "")
    logger.info("🔑 Received token (first 20 chars): %s..." % token[:20])

    try:
        # Decode header to check algorithm
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        kid = header.get("kid")
        logger.info("🔑 Token algorithm: %s, Key ID: %s" % (alg, kid))

        # 1. Handle ES256 (New Supabase Signing Keys)
        if alg == "ES256":
            supabase_url = os.getenv("SUPABASE_URL")
            if not supabase_url:
                raise HTTPException(status_code=500, detail="SUPABASE_URL not configured")

            project_ref = supabase_url.replace("https://", "").replace("http://", "").split(".")[0]
            jwks_url = f"https://{project_ref}.supabase.co/auth/v1/jwks"
            logger.info("🔑 Fetching JWKS from: %s" % jwks_url)

            try:
                jwks_response = requests.get(jwks_url, timeout=5)
                jwks_response.raise_for_status()
                jwks = jwks_response.json()

                # Find matching key
                matching_key = None
                for jwk_data in jwks.get("keys", []):
                    if jwk_data.get("kid") == kid:
                        matching_key = jwk_data
                        break

                if not matching_key:
                    logger.warning("❌ Key ID %s not found in JWKS. Falling back to HS256." % kid)
                    raise ValueError("Key not found")

                # Convert JWK to public key and decode
                public_key = ECAlgorithm.from_jwk(json.dumps(matching_key))
                payload = jwt.decode(
                    token,
                    key=public_key,
                    algorithms=["ES256"],
                    audience="authenticated",
                    options={"verify_aud": True}
                )
            except Exception as e:
                logger.warning("ES256 decode failed: %s, trying HS256 fallback" % str(e))
                raise ValueError("ES256 failed")

        # 2. Handle HS256 (Legacy Secret)
        elif alg == "HS256" or alg is None:
            jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
            if not jwt_secret:
                logger.error("❌ SUPABASE_JWT_SECRET not set!")
                raise HTTPException(status_code=500, detail="Server configuration error")

            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"verify_aud": True}
            )
        else:
            raise HTTPException(status_code=401, detail=f"Unsupported algorithm: {alg}")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token - no user ID")

        logger.info("✅ Authenticated user: %s" % user_id)
        return user_id

    except ValueError:
        # Fallback to HS256 if ES256 logic failed but didn't throw a specific JWT error
        try:
            jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
            payload = jwt.decode(token, jwt_secret, algorithms=["HS256"], audience="authenticated")
            return payload.get("sub")
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error("❌ Auth error: %s" % str(e))
        raise HTTPException(status_code=401, detail="Authentication failed")

# --- Rest of the endpoints (get_profile, recipients, etc.) ---
# ... [Keeping your existing endpoint logic here] ...

@router.get("/test-auth")
async def test_auth(user_id: str = Depends(get_current_user_id)):
    """Test endpoint to verify authentication"""
    return {
        "status": "authenticated",
        "user_id": user_id,
        "message": "Auth is working!"
    }