# app/admin_products.py
# Product management service for Supabase

from typing import List, Optional
import logging
from datetime import datetime
from supabase import Client
from app.database import get_supabase
from app.admin_models import GiftProduct, ProductListResponse

logger = logging.getLogger(__name__)

TABLE_GIFTS = "gifts"


def get_next_gift_id() -> str:
    """
    Get the next gift ID (gift_XXXX).

    Returns:
        Next sequential gift ID
    """
    try:
        supabase = get_supabase()

        # Get the last gift ID
        result = supabase.table(TABLE_GIFTS)\
            .select("id")\
            .like("id", "gift_%")\
            .order("id", desc=True)\
            .limit(1)\
            .execute()

        if not result.data:
            return "gift_0001"

        last_id = result.data[0]["id"]
        # Extract number and increment
        last_num = int(last_id.split("_")[1])
        next_num = last_num + 1

        return f"gift_{next_num:04d}"

    except Exception as e:
        logger.error(f"Error getting next gift ID: {str(e)}")
        # Fallback to timestamp-based ID
        timestamp = int(datetime.utcnow().timestamp())
        return f"gift_{timestamp % 10000:04d}"


def save_product(product: GiftProduct, created_by: str = "admin") -> GiftProduct:
    """
    Save a new product to the database.

    Args:
        product: Gift product to save
        created_by: Username of creator

    Returns:
        Saved product with generated ID

    Raises:
        ValueError: If save fails
    """
    try:
        supabase = get_supabase()

        # Generate ID if not provided
        if not product.id:
            product.id = get_next_gift_id()

        # Prepare data for Supabase
        data = {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "price": product.price,
            "currency": product.currency,
            "categories": product.categories,
            "interests": product.interests,
            "occasions": product.occasions,
            "vibe": product.vibe,
            "personality_traits": product.personality_traits,
            "recipient": product.recipient.dict(),
            "experience_level": product.experience_level,
            "brand": product.brand,
            "link": product.link,
            "image_url": product.image_url,
            "source": product.source,
            "rating": product.rating,
            "review_count": product.review_count,
            "in_stock": product.in_stock,
            "created_by": created_by,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        # Insert into database
        result = supabase.table(TABLE_GIFTS).insert(data).execute()

        if not result.data:
            raise ValueError("Failed to save product - no data returned")

        logger.info(f"Product saved successfully: {product.id} - {product.name}")

        # Return the saved product
        saved_data = result.data[0]
        product.created_at = datetime.fromisoformat(saved_data["created_at"].replace("Z", "+00:00"))
        product.updated_at = datetime.fromisoformat(saved_data["updated_at"].replace("Z", "+00:00"))

        return product

    except Exception as e:
        logger.error(f"Error saving product: {str(e)}")
        raise ValueError(f"Failed to save product: {str(e)}")


def get_product(product_id: str) -> Optional[GiftProduct]:
    """
    Get a product by ID.

    Args:
        product_id: Product ID

    Returns:
        GiftProduct if found, None otherwise
    """
    try:
        supabase = get_supabase()

        result = supabase.table(TABLE_GIFTS)\
            .select("*")\
            .eq("id", product_id)\
            .execute()

        if not result.data:
            return None

        data = result.data[0]
        return GiftProduct(**data)

    except Exception as e:
        logger.error(f"Error getting product {product_id}: {str(e)}")
        return None


def list_products(
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    sort_desc: bool = True,
    search: Optional[str] = None,
    category: Optional[str] = None,
    in_stock_only: bool = False
) -> ProductListResponse:
    """
    List products with pagination and filtering.

    Args:
        page: Page number (1-indexed)
        page_size: Items per page
        sort_by: Field to sort by
        sort_desc: Sort descending if True
        search: Search query for name/description/brand
        category: Filter by category
        in_stock_only: Only show in-stock products

    Returns:
        ProductListResponse with products and pagination info
    """
    try:
        supabase = get_supabase()

        # Build query
        query = supabase.table(TABLE_GIFTS).select("*", count="exact")

        # Apply filters
        if in_stock_only:
            query = query.eq("in_stock", True)

        if category:
            query = query.contains("categories", [category])

        if search:
            # Simple text search (you can enhance this with full-text search)
            query = query.or_(
                f"name.ilike.%{search}%,"
                f"description.ilike.%{search}%,"
                f"brand.ilike.%{search}%"
            )

        # Count total
        count_result = query.execute()
        total = count_result.count if hasattr(count_result, 'count') else len(count_result.data)

        # Apply sorting
        query = query.order(sort_by, desc=sort_desc)

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.range(offset, offset + page_size - 1)

        # Execute query
        result = query.execute()

        products = [GiftProduct(**item) for item in result.data]

        logger.info(f"Listed {len(products)} products (page {page}/{(total + page_size - 1) // page_size})")

        return ProductListResponse(
            products=products,
            total=total,
            page=page,
            page_size=page_size
        )

    except Exception as e:
        logger.error(f"Error listing products: {str(e)}")
        return ProductListResponse(products=[], total=0, page=page, page_size=page_size)


def update_product(product_id: str, updates: dict) -> bool:
    """
    Update an existing product.

    Args:
        product_id: Product ID
        updates: Dictionary of fields to update

    Returns:
        True if successful, False otherwise
    """
    try:
        supabase = get_supabase()

        # Add updated_at timestamp
        updates["updated_at"] = datetime.utcnow().isoformat()

        result = supabase.table(TABLE_GIFTS)\
            .update(updates)\
            .eq("id", product_id)\
            .execute()

        if not result.data:
            logger.warning(f"Product {product_id} not found for update")
            return False

        logger.info(f"Product {product_id} updated successfully")
        return True

    except Exception as e:
        logger.error(f"Error updating product {product_id}: {str(e)}")
        return False


def delete_product(product_id: str) -> bool:
    """
    Delete a product.

    Args:
        product_id: Product ID

    Returns:
        True if successful, False otherwise
    """
    try:
        supabase = get_supabase()

        result = supabase.table(TABLE_GIFTS)\
            .delete()\
            .eq("id", product_id)\
            .execute()

        if not result.data:
            logger.warning(f"Product {product_id} not found for deletion")
            return False

        logger.info(f"Product {product_id} deleted successfully")
        return True

    except Exception as e:
        logger.error(f"Error deleting product {product_id}: {str(e)}")
        return False


def get_product_stats() -> dict:
    """
    Get statistics about products in the database.

    Returns:
        Dictionary with stats
    """
    try:
        supabase = get_supabase()

        # Total products
        result = supabase.table(TABLE_GIFTS).select("*", count="exact").execute()
        total = result.count if hasattr(result, 'count') else len(result.data)

        # In stock
        in_stock_result = supabase.table(TABLE_GIFTS)\
            .select("*", count="exact")\
            .eq("in_stock", True)\
            .execute()
        in_stock = in_stock_result.count if hasattr(in_stock_result, 'count') else len(in_stock_result.data)

        # Average rating
        all_products = result.data
        ratings = [p.get("rating") for p in all_products if p.get("rating") is not None]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        # Category distribution
        category_counts = {}
        for product in all_products:
            for category in product.get("categories", []):
                category_counts[category] = category_counts.get(category, 0) + 1

        return {
            "total_products": total,
            "in_stock": in_stock,
            "out_of_stock": total - in_stock,
            "average_rating": round(avg_rating, 2),
            "category_distribution": category_counts
        }

    except Exception as e:
        logger.error(f"Error getting product stats: {str(e)}")
        return {
            "total_products": 0,
            "in_stock": 0,
            "out_of_stock": 0,
            "average_rating": 0,
            "category_distribution": {}
        }
