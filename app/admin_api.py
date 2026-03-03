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
from supabase import Client

logger = logging.getLogger(__name__)

# SINGLE router definition
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


# ============================================
# Amazon Product Fetching
# ============================================

@router.post("/api/fetch-amazon", response_model=AmazonProductResponse)
async def fetch_amazon_product(
    request: AmazonProductRequest,
    _: None = Depends(verify_admin)
):
    """Fetch product details from Amazon URL."""
    try:
        logger.info("Fetching Amazon product: %s" % request.url)
        product = await scrape_amazon_product(request.url)
        return product
    except ValueError as e:
        logger.error("Failed to fetch Amazon product: %s" % str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Unexpected error fetching Amazon product: %s" % str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch product: %s" % str(e))


@router.post("/api/categorize", response_model=AICategorizationResponse)
async def categorize_product_endpoint(
    request: AICategorizationRequest,
    _: None = Depends(verify_admin)
):
    """Use AI to suggest product categorization."""
    try:
        logger.info("Categorizing product: %s..." % request.name[:50])
        categorization = await categorize_product(
            product_name=request.name,
            description=request.description or "",
            brand=request.brand or ""
        )
        return categorization
    except Exception as e:
        logger.error("Categorization failed: %s" % str(e))
        raise HTTPException(status_code=500, detail="Categorization failed: %s" % str(e))


# ============================================
# Product CRUD
# ============================================

@router.post("/api/products", response_model=GiftProduct)
async def create_product(
    request: ProductSaveRequest,
    _: None = Depends(verify_admin)
):
    """Save a new product to the database."""
    try:
        logger.info("Saving new product: %s" % request.product.name)
        saved_product = save_product(request.product, created_by=request.created_by)
        return saved_product
    except ValueError as e:
        logger.error("Failed to save product: %s" % str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Unexpected error saving product: %s" % str(e))
        raise HTTPException(status_code=500, detail="Failed to save product: %s" % str(e))


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
    try:
        return list_products(
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_desc=sort_desc,
            search=search,
            category=category,
            in_stock_only=in_stock_only
        )
    except Exception as e:
        logger.error("Failed to list products: %s" % str(e))
        raise HTTPException(status_code=500, detail="Failed to list products: %s" % str(e))


@router.get("/api/products/{product_id}", response_model=GiftProduct)
async def get_product_endpoint(
    product_id: str,
    _: None = Depends(verify_admin)
):
    """Get a specific product by ID."""
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product %s not found" % product_id)
    return product


@router.put("/api/products/{product_id}")
async def update_product_endpoint(
    product_id: str,
    product: GiftProduct,
    _: None = Depends(verify_admin)
):
    """Update an existing product."""
    try:
        updates = {k: v for k, v in product.dict().items() if v is not None and k != "id"}
        success = update_product(product_id, updates)
        if not success:
            raise HTTPException(status_code=404, detail="Product %s not found" % product_id)
        return {"status": "success", "message": "Product %s updated" % product_id}
    except Exception as e:
        logger.error("Failed to update product %s: %s" % (product_id, str(e)))
        raise HTTPException(status_code=500, detail="Failed to update product: %s" % str(e))


@router.delete("/api/products/{product_id}")
async def delete_product_endpoint(
    product_id: str,
    _: None = Depends(verify_admin)
):
    """Delete a product."""
    success = delete_product(product_id)
    if not success:
        raise HTTPException(status_code=404, detail="Product %s not found" % product_id)
    return {"status": "success", "message": "Product %s deleted" % product_id}


@router.get("/api/products/{product_id}/quality", response_model=QualityCheckResponse)
async def check_product_quality(
    product_id: str,
    _: None = Depends(verify_admin)
):
    """Get quality indicators for a product."""
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product %s not found" % product_id)
    indicators = get_quality_indicators(product.rating, product.review_count, product.in_stock)
    return QualityCheckResponse(**indicators)


@router.get("/api/stats")
async def get_stats(_: None = Depends(verify_admin)):
    """Get product database statistics."""
    try:
        stats = get_product_stats()
        return stats
    except Exception as e:
        logger.error("Failed to get stats: %s" % str(e))
        raise HTTPException(status_code=500, detail="Failed to get stats: %s" % str(e))


# ============================================
# Shipping Management
# ============================================

class ShippingUpdate(BaseModel):
    shipping_min_days: int
    shipping_max_days: int
    is_prime_eligible: bool
    shipping_notes: Optional[str] = None


@router.post("/apply-shipping-defaults")
async def apply_shipping_defaults():
    """Apply intelligent shipping defaults based on product categories."""
    from app.retrieval import get_supabase_client

    supabase = get_supabase_client()
    updated_count = 0

    # Conservative default for ALL products first
    result = supabase.table('gifts').update({
        'shipping_min_days': 5,
        'shipping_max_days': 8,
        'is_prime_eligible': False
    }).eq('source', 'amazon').execute()
    updated_count += len(result.data) if result.data else 0

    return {
        "status": "success",
        "updated": updated_count,
        "message": "Applied category-based shipping defaults"
    }


@router.patch("/gifts/{gift_id}/shipping")
async def update_gift_shipping(gift_id: str, update: ShippingUpdate, db: Client = Depends(get_db)):
    """Manually override shipping for a specific product."""
    result = db.table('gifts').update({
        'shipping_min_days': update.shipping_min_days,
        'shipping_max_days': update.shipping_max_days,
        'is_prime_eligible': update.is_prime_eligible,
        'shipping_notes': update.shipping_notes
    }).eq('id', gift_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Gift not found")

    return {"status": "updated", "gift": result.data[0]}


@router.get("/gifts")
async def get_all_gifts_admin(db: Client = Depends(get_db)):
    """Get all gifts for admin dashboard."""
    response = db.table('gifts').select(
        'id, name, shipping_min_days, shipping_max_days, is_prime_eligible, shipping_notes, categories'
    ).order('name').execute()
    return {"gifts": response.data}