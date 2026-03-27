# app/admin_api.py
# Admin API endpoints for product management

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List
import logging
import os

from app.admin_models import (
    AmazonProductRequest,
    AmazonProductResponse,
    AICategorizationRequest,
    AICategorizationResponse,
    GiftProduct,
    ProductSaveRequest,
    ProductListResponse,
    QualityCheckResponse
)
from app.amazon_scraper import scrape_amazon_product, get_quality_indicators
from app.ai_categorization import categorize_product
from app.admin_products import (
    save_product,
    get_product,
    list_products,
    update_product,
    delete_product,
    get_product_stats
)
from app.database import get_db
from app.llm import generate_display_name
from app.embeddings import generate_embedding, create_gift_text_for_embedding
from supabase import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Admin authentication
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", os.getenv("BACKEND_API_KEY"))


def verify_admin(x_api_key: Optional[str] = Header(None)):
    """Verify admin API key."""
    if not ADMIN_API_KEY:
        logger.warning("No ADMIN_API_KEY set - admin endpoints are unprotected!")
        return

    if not x_api_key or x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized - Invalid API key")


# --- Helper Models ---

class DisplayNameUpdate(BaseModel):
    display_name: str


class ShippingUpdate(BaseModel):
    shipping_min_days: int
    shipping_max_days: int
    is_prime_eligible: bool
    shipping_notes: Optional[str] = None


class ManualProductRequest(BaseModel):
    """Request body for manually entered products (no Amazon scrape needed)."""
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    price: float
    currency: str = "USD"
    link: Optional[str] = None          # JS sends 'link'; stored as product_url in DB
    image_url: Optional[str] = None
    source: str = "other"
    categories: List[str] = []
    interests: List[str] = []
    occasions: List[str] = []
    vibe: List[str] = []
    personality_traits: List[str] = []
    recipient: Optional[dict] = None
    experience_level: str = "beginner"
    rating: Optional[float] = None
    review_count: int = 0
    in_stock: bool = True


# ============================================
# Amazon Product Fetching & Automation
# ============================================

@router.post("/api/fetch-amazon")
async def fetch_amazon_product_endpoint(
        request: AmazonProductRequest,
        db: Client = Depends(get_db),
        _: None = Depends(verify_admin)
):
    """
    Fetch from Amazon, generate a clean display name,
    create embeddings, and save to database.
    """
    try:
        logger.info("Fetching Amazon product: %s" % request.url)
        product_data = await scrape_amazon_product(request.url)

        if not product_data:
            raise HTTPException(status_code=404, detail="Product details could not be scraped")

        # Generate clean display name via LLM
        display_name = generate_display_name(
            product_name=product_data.get('name', ''),
            description=product_data.get('description', '')
        )

        logger.info("✨ Display Name Generated: %s" % display_name)

        # Prepare for search: Generate Embeddings
        gift_temp = {
            "name": product_data.get('name'),
            "description": product_data.get('description', ''),
            "categories": []
        }
        embedding_text = create_gift_text_for_embedding(gift_temp)
        embedding = generate_embedding(embedding_text)

        # Generate a sequential gift ID (table has no auto-increment default)
        from app.admin_products import get_next_gift_id
        gift_id = get_next_gift_id()
        logger.info("Generated gift ID: %s" % gift_id)

        # Save to Supabase
        result = db.table('gifts').insert({
            'id': gift_id,
            'name': product_data.get('name'),
            'display_name': display_name,
            'price': product_data.get('price', 0.0),
            'description': product_data.get('description', ''),
            'image_url': product_data.get('image_url'),
            'link': product_data.get('product_url') or product_data.get('link'),
            'source': 'amazon',
            'shipping_min_days': 5,
            'shipping_max_days': 8,
            'is_prime_eligible': product_data.get('is_prime_eligible', False),
            'embedding': embedding
        }).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to insert product into database")

        return {
            "success": True,
            "product": result.data[0],
            "display_name": display_name,
            "original_name": product_data.get('name')
        }

    except Exception as e:
        logger.error("Error in fetch-amazon: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Manual Product Creation (NEW)
# ============================================

@router.post("/api/products/manual")
async def create_manual_product_endpoint(
        request: ManualProductRequest,
        db: Client = Depends(get_db),
        _: None = Depends(verify_admin)
):
    """
    Create a product manually without Amazon scraping.
    Generates a display name (if not provided) and embeddings,
    then saves to the database with the full tag schema.
    """
    try:
        logger.info("Creating manual product: %s" % request.name)

        # Generate display name if not manually provided
        display_name = request.display_name
        if not display_name:
            display_name = generate_display_name(
                product_name=request.name,
                description=request.description or ''
            )
            logger.info("✨ Auto-generated display name: %s" % display_name)

        # Generate embedding for search
        gift_temp = {
            "name": request.name,
            "description": request.description or '',
            "categories": request.categories
        }
        embedding_text = create_gift_text_for_embedding(gift_temp)
        embedding = generate_embedding(embedding_text)

        # Generate a sequential gift ID (table has no auto-increment default)
        from app.admin_products import get_next_gift_id
        gift_id = get_next_gift_id()
        logger.info("Generated gift ID: %s" % gift_id)

        # Build the full record — matching the existing gifts table schema
        record = {
            'id': gift_id,
            'name': request.name,
            'display_name': display_name,
            'description': request.description,
            'brand': request.brand,
            'price': request.price,
            'currency': request.currency,
            'link': request.link,
            'image_url': request.image_url,
            'source': request.source,
            'categories': request.categories,
            'interests': request.interests,
            'occasions': request.occasions,
            'vibe': request.vibe,
            'personality_traits': request.personality_traits,
            'recipient': request.recipient or {},
            'experience_level': request.experience_level,
            'rating': request.rating,
            'review_count': request.review_count,
            'in_stock': request.in_stock,
            'embedding': embedding,
            'shipping_min_days': 5,
            'shipping_max_days': 8,
            'is_prime_eligible': False,
        }

        result = db.table('gifts').insert(record).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to insert manual product into database")

        saved = result.data[0]
        logger.info("Manual product saved: %s (%s)" % (saved.get('id'), request.name))

        return {
            "success": True,
            "id": saved.get('id'),
            "product": saved,
            "display_name": display_name
        }

    except Exception as e:
        logger.error("Error creating manual product: %s" % str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/categorize", response_model=AICategorizationResponse)
async def categorize_product_endpoint(
        request: AICategorizationRequest,
        _: None = Depends(verify_admin)
):
    """Use AI to suggest product categorization."""
    try:
        categorization = await categorize_product(
            product_name=request.name,
            description=request.description or "",
            brand=request.brand or ""
        )
        return categorization
    except Exception as e:
        raise HTTPException(status_code=500, detail="Categorization failed: %s" % str(e))


# ============================================
# Product CRUD & Management
# ============================================

@router.get("/api/products", response_model=ProductListResponse)
async def list_products_endpoint(
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_desc: bool = True,
        search: Optional[str] = None,
        category: Optional[str] = None,
        in_stock_only: bool = False,
        _: None = Depends(verify_admin)
):
    """List products with pagination and filtering."""
    return list_products(page, page_size, sort_by, sort_desc, search, category, in_stock_only)


@router.post("/api/products")
async def create_product_endpoint(request: ProductSaveRequest, _: None = Depends(verify_admin)):
    """
    Save a product built from the admin form (post-scrape or post-manual).
    Routes to the manual creation path which handles embeddings + display name.
    """
    try:
        product = request.product
        manual_req = ManualProductRequest(
            name=product.name,
            display_name=getattr(product, 'display_name', None),
            description=product.description,
            brand=product.brand,
            price=product.price,
            currency=product.currency or "USD",
            link=product.link,
            image_url=product.image_url,
            source=product.source or "other",
            categories=product.categories or [],
            interests=product.interests or [],
            occasions=product.occasions or [],
            vibe=product.vibe or [],
            personality_traits=product.personality_traits or [],
            recipient=product.recipient.dict() if product.recipient else {},
            experience_level=product.experience_level or "beginner",
            rating=product.rating,
            review_count=product.review_count or 0,
            in_stock=product.in_stock if product.in_stock is not None else True,
        )
        saved = save_product(product, request.created_by or "admin")
        return {"id": saved.id, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/products/{product_id}", response_model=GiftProduct)
async def get_product_endpoint(product_id: str, _: None = Depends(verify_admin)):
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put("/api/products/{product_id}")
async def update_product_endpoint(product_id: str, product: GiftProduct, _: None = Depends(verify_admin)):
    updates = {k: v for k, v in product.dict().items() if v is not None and k != "id"}
    if not update_product(product_id, updates):
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "success"}


@router.delete("/api/products/{product_id}")
async def delete_product_endpoint(product_id: str, _: None = Depends(verify_admin)):
    if not delete_product(product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "success"}


# ============================================
# Display Name Overrides
# ============================================

@router.put("/api/products/{product_id}/display-name")
async def update_display_name_endpoint(
        product_id: str,
        request: DisplayNameUpdate,
        db: Client = Depends(get_db),
        _: None = Depends(verify_admin)
):
    """Manually update the display name for a product."""
    result = db.table('gifts').update({
        'display_name': request.display_name.strip()
    }).eq('id', product_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True, "display_name": request.display_name}


@router.post("/api/products/{product_id}/regenerate-display-name")
async def regenerate_display_name_endpoint(
        product_id: str,
        db: Client = Depends(get_db),
        _: None = Depends(verify_admin)
):
    """Regenerate display name using the AI LLM."""
    res = db.table('gifts').select('name, description').eq('id', product_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")

    product = res.data[0]
    new_name = generate_display_name(product['name'], product.get('description', ''))

    db.table('gifts').update({'display_name': new_name}).eq('id', product_id).execute()
    return {"success": True, "display_name": new_name}


# ============================================
# Shipping & Stats
# ============================================

@router.patch("/gifts/{gift_id}/shipping")
async def update_gift_shipping(gift_id: str, update: ShippingUpdate, db: Client = Depends(get_db),
                               _: None = Depends(verify_admin)):
    result = db.table('gifts').update({
        'shipping_min_days': update.shipping_min_days,
        'shipping_max_days': update.shipping_max_days,
        'is_prime_eligible': update.is_prime_eligible,
        'shipping_notes': update.shipping_notes
    }).eq('id', gift_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Gift not found")
    return {"status": "updated"}


@router.get("/api/stats")
async def get_stats(_: None = Depends(verify_admin)):
    return get_product_stats()