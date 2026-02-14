# app/admin_models.py
# Pydantic models for admin product management

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal
from datetime import datetime
from decimal import Decimal


class RecipientInfo(BaseModel):
    gender: List[Literal["male", "female", "unisex"]] = []
    relationship: List[Literal["partner", "spouse", "boyfriend", "girlfriend", "friend", "family"]] = []


class GiftProduct(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    price: float
    currency: str = "USD"

    # Categorical arrays with max limits
    categories: List[Literal["tech", "home", "kitchen", "fashion", "beauty", "fitness", "outdoors", "hobby", "book", "experiences"]] = Field(default_factory=list, max_items=2)
    interests: List[Literal["coffee", "cooking", "baking", "fitness", "running", "yoga", "gaming", "photography", "music", "travel", "reading", "art", "gardening", "cycling", "hiking", "camping", "movies", "wine", "cocktails", "tea", "fashion", "skincare", "makeup"]] = Field(default_factory=list, max_items=5)
    occasions: List[Literal["birthday", "anniversary", "valentines", "holiday", "christmas", "wedding", "engagement", "graduation", "just_because"]] = Field(default_factory=list, max_items=4)
    vibe: List[Literal["romantic", "practical", "luxury", "fun", "sentimental", "creative", "cozy", "adventurous", "minimalist"]] = Field(default_factory=list, max_items=3)
    personality_traits: List[Literal["introverted", "extroverted", "analytical", "creative", "sentimental", "adventurous", "organized", "relaxed", "curious"]] = Field(default_factory=list, max_items=3)

    recipient: RecipientInfo = Field(default_factory=RecipientInfo)
    experience_level: Optional[Literal["beginner", "enthusiast", "expert"]] = None

    brand: Optional[str] = None
    link: Optional[str] = None
    image_url: Optional[str] = None
    source: str = "amazon"

    # Quality metrics
    rating: Optional[float] = None
    review_count: Optional[int] = 0
    in_stock: bool = True

    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @validator('categories')
    def validate_categories_limit(cls, v):
        if len(v) > 2:
            raise ValueError('categories cannot have more than 2 items')
        return v

    @validator('interests')
    def validate_interests_limit(cls, v):
        if len(v) > 5:
            raise ValueError('interests cannot have more than 5 items')
        return v

    @validator('occasions')
    def validate_occasions_limit(cls, v):
        if len(v) > 4:
            raise ValueError('occasions cannot have more than 4 items')
        return v

    @validator('vibe')
    def validate_vibe_limit(cls, v):
        if len(v) > 3:
            raise ValueError('vibe cannot have more than 3 items')
        return v

    @validator('personality_traits')
    def validate_personality_traits_limit(cls, v):
        if len(v) > 3:
            raise ValueError('personality_traits cannot have more than 3 items')
        return v

    @validator('rating')
    def validate_rating(cls, v):
        if v is not None and (v < 0 or v > 5):
            raise ValueError('rating must be between 0 and 5')
        return v

    @validator('price')
    def validate_price(cls, v):
        if v < 0:
            raise ValueError('price must be non-negative')
        return v


class AmazonProductRequest(BaseModel):
    url: str


class AmazonProductResponse(BaseModel):
    name: str
    description: Optional[str]
    price: Optional[float]
    currency: str = "USD"
    image_url: Optional[str]
    brand: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    in_stock: bool
    asin: str
    link: str


class AICategorizationRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    brand: Optional[str] = ""


class AICategorizationResponse(BaseModel):
    categories: List[str]
    interests: List[str]
    occasions: List[str]
    recipient: RecipientInfo
    vibe: List[str]
    personality_traits: List[str]
    experience_level: str


class ProductSaveRequest(BaseModel):
    product: GiftProduct
    created_by: Optional[str] = "admin"


class ProductListResponse(BaseModel):
    products: List[GiftProduct]
    total: int
    page: int
    page_size: int


class QualityCheckResponse(BaseModel):
    rating_status: Literal["excellent", "good", "warning", "poor"]
    reviews_status: Literal["excellent", "good", "warning", "poor"]
    stock_status: Literal["in_stock", "out_of_stock"]
    overall_quality: Literal["excellent", "good", "warning", "poor"]
