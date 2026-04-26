"""
Gift AI — Pydantic Schemas
Updated to reflect the new quiz structure:
  - relationship_stage replaces recipient gender/relationship
  - vibe uses new 7-tag set
  - archetypes + overlap_interests added
  - confidence routing field added
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from enum import Enum


# =============================================================================
# ENUMS
# =============================================================================

class OccasionEnum(str, Enum):
    birthday    = "birthday"
    valentines  = "valentines"
    anniversary = "anniversary"
    christmas   = "christmas"
    mothers_day = "mothers_day"
    just_because= "just_because"
    apology     = "apology"


class RelationshipStageEnum(str, Enum):
    new         = "new"
    dating      = "dating"
    serious     = "serious"
    committed   = "committed"
    complicated = "complicated"


class VibeEnum(str, Enum):
    pampering   = "pampering"
    romantic    = "romantic"
    sentimental = "sentimental"
    luxe        = "luxe"
    cozy        = "cozy"
    fun         = "fun"
    thoughtful  = "thoughtful"


class ConfidenceEnum(str, Enum):
    confident = "confident"
    somewhat  = "somewhat"
    lost      = "lost"


class ArchetypeEnum(str, Enum):
    outdoorsy    = "outdoorsy"
    homebody     = "homebody"
    artsy        = "artsy"
    wellness     = "wellness"
    social       = "social"
    niche        = "niche"
    petparent    = "petparent"
    fitness_girl = "fitness_girl"


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class RecommendRequest(BaseModel):
    """
    Payload sent from the quiz to the /recommend endpoint.
    All fields except occasion are optional to support partial quiz completion
    (e.g. confidence='lost' skips archetypes and interests entirely).
    """

    # Core quiz answers
    occasion: OccasionEnum
    relationship_stage: Optional[RelationshipStageEnum] = None
    partner_name: Optional[str] = Field(None, max_length=100)
    partner_id: Optional[str] = None

    # Smart preselection outputs (user may have overridden)
    vibe: Optional[List[VibeEnum]] = Field(default_factory=list)
    max_price: Optional[float] = Field(None, ge=0, le=999999)

    # Confidence routing
    confidence: Optional[ConfidenceEnum] = None

    # Archetype + interest signals
    archetypes: Optional[List[ArchetypeEnum]] = Field(default_factory=list)
    interests: Optional[List[str]] = Field(default_factory=list)

    # Overlap interests — interests that appear in multiple selected archetypes.
    # These receive a scoring boost in the retrieval layer.
    overlap_interests: Optional[List[str]] = Field(default_factory=list)

    # Raw niche keywords extracted from freeform interest input (e.g. "Star Wars", "true crime").
    # Bypass the taxonomy and feed directly into the embedding query and LLM prompt.
    niche_keywords: Optional[List[str]] = Field(default_factory=list)

    # Date/shipping context — occasion_date must be an ISO date string (YYYY-MM-DD)
    occasion_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    days_until_needed: Optional[int] = None

    # Legacy field — kept for backward compatibility with saved partner profiles
    # Deprecated: use relationship_stage instead
    recipient: Optional[dict] = None

    # Load more — names of already-shown gifts to exclude from next batch
    exclude_names: Optional[List[str]] = Field(default_factory=list)

    # Override for k (number of results) — defaults to 5 in main.py
    k: Optional[int] = Field(None, ge=1, le=20)

    class Config:
        use_enum_values = True


class SavePartnerRequest(BaseModel):
    """Saves or updates a partner profile for returning users."""
    partner_name: str = Field(..., max_length=50)
    occasion: Optional[str] = None
    relationship_stage: Optional[str] = None
    vibe: Optional[List[str]] = Field(default_factory=list)
    interests: Optional[List[str]] = Field(default_factory=list)
    archetypes: Optional[List[str]] = Field(default_factory=list)
    max_price: Optional[float] = None


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class GiftItem(BaseModel):
    """A single recommended gift returned to the frontend."""
    id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    price: float
    currency: str = "USD"
    brand: Optional[str] = None
    link: Optional[str] = None
    image_url: Optional[str] = None
    rating: Optional[float] = None
    is_prime_eligible: Optional[bool] = None
    shipping_min_days: Optional[int] = None
    shipping_max_days: Optional[int] = None

    # Personalisation fields added by the LLM layer
    reason: Optional[str] = None           # Why this gift fits her specifically
    match_score: Optional[float] = None    # Internal ranking score (0–1)

    # New fields
    vibe: Optional[List[str]] = None
    interests: Optional[List[str]] = None
    occasions: Optional[List[str]] = None
    gift_type: Optional[List[str]] = None
    gender_skew: Optional[str] = None


class RecommendResponse(BaseModel):
    """Response envelope for the /recommend endpoint."""
    gifts: List[GiftItem]
    occasion: str
    relationship_stage: Optional[str] = None
    partner_name: Optional[str] = None
    total_found: int
    confidence: Optional[str] = None

    # Contextual messaging for the results page
    results_headline: Optional[str] = None
    results_subline: Optional[str] = None


# =============================================================================
# ADMIN SCHEMAS
# =============================================================================

class AdminAddGiftRequest(BaseModel):
    """Manual product entry via the admin dashboard."""
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    price: float
    brand: Optional[str] = None
    link: Optional[str] = None
    image_url: Optional[str] = None
    gift_type: Optional[List[str]] = Field(default_factory=list)
    interests: Optional[List[str]] = Field(default_factory=list)
    occasions: Optional[List[str]] = Field(default_factory=list)
    vibe: Optional[List[str]] = Field(default_factory=list)
    gender_skew: Optional[Literal["female", "male", "unisex"]] = "unisex"
    is_prime_eligible: Optional[bool] = False
    shipping_min_days: Optional[int] = None
    shipping_max_days: Optional[int] = None

class PreferencesRequest(BaseModel):
    user_id: str
    interests: Optional[List[str]] = []
    vibe: Optional[List[str]] = []


class GiftFeedback(BaseModel):
    user_id: str
    gift_name: str
    liked: bool
