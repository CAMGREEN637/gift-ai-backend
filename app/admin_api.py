# app/admin_api.py
# Admin API endpoints for product management

from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
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

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/admin/api", tags=["admin"])

# Admin authentication
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", os.getenv("BACKEND_API_KEY"))


def verify_admin(x_api_key: Optional[str] = Header(None)):
    """
    Verify admin API key.

    Raises:
        HTTPException: If unauthorized
    """
    if not ADMIN_API_KEY:
        # If no key is set, allow access (development mode)
        logger.warning("No ADMIN_API_KEY set - admin endpoints are unprotected!")
        return

    if not x_api_key or x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized - Invalid API key")


# ============================================
# Product Endpoints
# ============================================

@router.post("/fetch-amazon", response_model=AmazonProductResponse)
async def fetch_amazon_product(
    request: AmazonProductRequest,
    _: None = Depends(verify_admin)
):
    """
    Fetch product details from Amazon URL.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Scraped product details
    """
    try:
        logger.info(f"Fetching Amazon product: {request.url}")
        product = await scrape_amazon_product(request.url)
        return product
    except ValueError as e:
        logger.error(f"Failed to fetch Amazon product: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching Amazon product: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch product: {str(e)}")


@router.post("/categorize", response_model=AICategorizationResponse)
async def categorize_product_endpoint(
    request: AICategorizationRequest,
    _: None = Depends(verify_admin)
):
    """
    Use AI to suggest product categorization.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Suggested categories and attributes
    """
    try:
        logger.info(f"Categorizing product: {request.name[:50]}...")
        categorization = await categorize_product(
            product_name=request.name,
            description=request.description or "",
            brand=request.brand or ""
        )
        return categorization
    except Exception as e:
        logger.error(f"Categorization failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Categorization failed: {str(e)}")


@router.post("/products", response_model=GiftProduct)
async def create_product(
    request: ProductSaveRequest,
    _: None = Depends(verify_admin)
):
    """
    Save a new product to the database.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Saved product with generated ID
    """
    try:
        logger.info(f"Saving new product: {request.product.name}")
        saved_product = save_product(request.product, created_by=request.created_by)
        return saved_product
    except ValueError as e:
        logger.error(f"Failed to save product: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error saving product: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save product: {str(e)}")


@router.get("/products", response_model=ProductListResponse)
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
    """
    List products with pagination and filtering.

    Requires:
    - X-API-Key header with admin key

    Query parameters:
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20)
    - sort_by: Field to sort by (default: created_at)
    - sort_desc: Sort descending (default: true)
    - search: Search query
    - category: Filter by category
    - in_stock_only: Show only in-stock products

    Returns:
    - Paginated list of products
    """
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
        logger.error(f"Failed to list products: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list products: {str(e)}")


@router.get("/products/{product_id}", response_model=GiftProduct)
async def get_product_endpoint(
    product_id: str,
    _: None = Depends(verify_admin)
):
    """
    Get a specific product by ID.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Product details
    """
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return product


@router.put("/products/{product_id}")
async def update_product_endpoint(
    product_id: str,
    product: GiftProduct,
    _: None = Depends(verify_admin)
):
    """
    Update an existing product.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Success message
    """
    try:
        # Convert to dict and remove None values
        updates = {k: v for k, v in product.dict().items() if v is not None and k != "id"}

        success = update_product(product_id, updates)
        if not success:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

        return {"status": "success", "message": f"Product {product_id} updated"}
    except Exception as e:
        logger.error(f"Failed to update product {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update product: {str(e)}")


@router.delete("/products/{product_id}")
async def delete_product_endpoint(
    product_id: str,
    _: None = Depends(verify_admin)
):
    """
    Delete a product.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Success message
    """
    success = delete_product(product_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    return {"status": "success", "message": f"Product {product_id} deleted"}


@router.get("/products/{product_id}/quality", response_model=QualityCheckResponse)
async def check_product_quality(
    product_id: str,
    _: None = Depends(verify_admin)
):
    """
    Get quality indicators for a product.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Quality status indicators
    """
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    indicators = get_quality_indicators(product.rating, product.review_count, product.in_stock)

    return QualityCheckResponse(**indicators)


@router.get("/stats")
async def get_stats(
    _: None = Depends(verify_admin)
):
    """
    Get product database statistics.

    Requires:
    - X-API-Key header with admin key

    Returns:
    - Statistics dictionary
    """
    try:
        stats = get_product_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
