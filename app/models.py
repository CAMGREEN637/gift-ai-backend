#models.py
from pydantic import BaseModel
from typing import List

class PartnerInfo(BaseModel):
    name: str
    age: int
    interest: List[str]
    budget: int
    occasion: str