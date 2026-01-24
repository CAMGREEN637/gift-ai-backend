#schemas.py
from pydantic import BaseModel
from typing import List, Optional

class PreferencesRequest(BaseModel):
    user_id: str
    interests: Optional[List[str]] = []
    vibe: Optional[List[str]] = []

class GiftFeedback(BaseModel):
    user_id: str
    gift_name: str
    liked: bool