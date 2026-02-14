# app/amazon_scraper.py
# Amazon product scraper for admin product management

import re
import logging
from typing import Optional, Dict
import httpx
from bs4 import BeautifulSoup
from app.admin_models import AmazonProductResponse

logger = logging.getLogger(__name__)

# User agent to mimic a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


def extract_asin(url: str) -> Optional[str]:
    """
    Extract ASIN from Amazon URL.

    Patterns:
    - /dp/ASIN
    - /gp/product/ASIN
    - /product/ASIN
    """
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'/product/([A-Z0-9]{10})',
        r'[?&]asin=([A-Z0-9]{10})',
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def clean_price(price_text: str) -> Optional[float]:
    """Extract numeric price from price text."""
    if not price_text:
        return None

    # Remove currency symbols and extract number
    price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
    if price_match:
        try:
            return float(price_match.group(0))
        except ValueError:
            return None
    return None


def clean_rating(rating_text: str) -> Optional[float]:
    """Extract numeric rating from rating text."""
    if not rating_text:
        return None

    # Extract number before "out of" or similar
    rating_match = re.search(r'([\d.]+)\s*out of', rating_text, re.IGNORECASE)
    if rating_match:
        try:
            return float(rating_match.group(1))
        except ValueError:
            return None

    # Try extracting any decimal number
    rating_match = re.search(r'(\d+\.?\d*)', rating_text)
    if rating_match:
        try:
            rating = float(rating_match.group(1))
            if 0 <= rating <= 5:
                return rating
        except ValueError:
            pass

    return None


def clean_review_count(review_text: str) -> Optional[int]:
    """Extract review count from review text."""
    if not review_text:
        return None

    # Remove commas and extract number
    review_text_clean = review_text.replace(',', '').replace('.', '')
    number_match = re.search(r'(\d+)', review_text_clean)
    if number_match:
        try:
            return int(number_match.group(1))
        except ValueError:
            return None

    return None


async def scrape_amazon_product(url: str) -> AmazonProductResponse:
    """
    Scrape Amazon product details from URL.

    Args:
        url: Amazon product URL

    Returns:
        AmazonProductResponse with extracted details

    Raises:
        ValueError: If ASIN cannot be extracted or product not found
        httpx.HTTPError: If request fails
    """
    # Extract ASIN
    asin = extract_asin(url)
    if not asin:
        raise ValueError("Could not extract ASIN from URL. Please provide a valid Amazon product URL.")

    logger.info(f"Scraping Amazon product: ASIN={asin}")

    # Construct clean Amazon URL
    product_url = f"https://www.amazon.com/dp/{asin}"

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            response = await client.get(product_url)
            response.raise_for_status()

            if response.status_code != 200:
                raise ValueError(f"Failed to fetch product page: HTTP {response.status_code}")

            html = response.text

        # Parse HTML
        soup = BeautifulSoup(html, 'html.parser')

        # Extract product name
        name = None
        name_selectors = [
            {'id': 'productTitle'},
            {'class': 'product-title'},
            {'id': 'title'},
        ]
        for selector in name_selectors:
            element = soup.find(**selector)
            if element:
                name = element.get_text(strip=True)
                break

        if not name:
            raise ValueError("Could not extract product name. The page might be blocked or product unavailable.")

        # Extract price
        price = None
        price_selectors = [
            {'class': 'a-price-whole'},
            {'class': 'a-offscreen'},
            {'id': 'priceblock_ourprice'},
            {'id': 'priceblock_dealprice'},
            {'class': 'a-price'},
        ]
        for selector in price_selectors:
            element = soup.find(**selector)
            if element:
                price_text = element.get_text(strip=True)
                price = clean_price(price_text)
                if price:
                    break

        # Extract image URL
        image_url = None
        image_selectors = [
            {'id': 'landingImage'},
            {'id': 'imgBlkFront'},
            {'class': 'a-dynamic-image'},
        ]
        for selector in image_selectors:
            element = soup.find('img', **selector)
            if element:
                image_url = element.get('src') or element.get('data-old-hires') or element.get('data-a-dynamic-image')
                if image_url:
                    # Extract first URL if it's a JSON string
                    if image_url.startswith('{'):
                        import json
                        try:
                            image_data = json.loads(image_url)
                            image_url = list(image_data.keys())[0]
                        except:
                            pass
                    break

        # Extract brand
        brand = None
        brand_selectors = [
            {'id': 'bylineInfo'},
            {'class': 'po-brand'},
            {'id': 'brand'},
        ]
        for selector in brand_selectors:
            element = soup.find(**selector)
            if element:
                brand_text = element.get_text(strip=True)
                # Clean up "Visit the X Store" or "Brand: X"
                brand_text = re.sub(r'Visit the (.+?) Store', r'\1', brand_text, flags=re.IGNORECASE)
                brand_text = re.sub(r'Brand:\s*', '', brand_text, flags=re.IGNORECASE)
                brand = brand_text
                break

        # Extract description
        description = None
        desc_selectors = [
            {'id': 'feature-bullets'},
            {'id': 'productDescription'},
            {'class': 'a-section a-spacing-medium a-spacing-top-small'},
        ]
        for selector in desc_selectors:
            element = soup.find(**selector)
            if element:
                # Get text from list items if available
                items = element.find_all('li')
                if items:
                    description = ' '.join([item.get_text(strip=True) for item in items[:5]])  # First 5 bullet points
                else:
                    description = element.get_text(strip=True)[:500]  # Limit to 500 chars
                break

        # Extract rating
        rating = None
        rating_selectors = [
            {'class': 'a-icon-alt'},
            {'id': 'acrPopover'},
            {'class': 'a-star'},
        ]
        for selector in rating_selectors:
            element = soup.find(**selector)
            if element:
                rating_text = element.get_text(strip=True)
                rating = clean_rating(rating_text)
                if rating:
                    break

        # Extract review count
        review_count = None
        review_selectors = [
            {'id': 'acrCustomerReviewText'},
            {'class': 'a-size-base'},
        ]
        for selector in review_selectors:
            element = soup.find(**selector)
            if element:
                review_text = element.get_text(strip=True)
                if 'rating' in review_text.lower():
                    review_count = clean_review_count(review_text)
                    if review_count:
                        break

        # Check stock status
        in_stock = True
        stock_selectors = [
            {'id': 'availability'},
            {'class': 'a-size-medium a-color-price'},
        ]
        for selector in stock_selectors:
            element = soup.find(**selector)
            if element:
                stock_text = element.get_text(strip=True).lower()
                if any(word in stock_text for word in ['unavailable', 'out of stock', 'currently unavailable']):
                    in_stock = False
                    break

        logger.info(f"Successfully scraped product: {name[:50]}...")

        return AmazonProductResponse(
            name=name,
            description=description,
            price=price,
            currency="USD",  # Amazon.com defaults to USD
            image_url=image_url,
            brand=brand,
            rating=rating,
            review_count=review_count or 0,
            in_stock=in_stock,
            asin=asin,
            link=product_url
        )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error scraping Amazon: {str(e)}")
        raise ValueError(f"Failed to fetch Amazon page: {str(e)}")
    except Exception as e:
        logger.error(f"Error scraping Amazon: {str(e)}")
        raise ValueError(f"Failed to scrape product details: {str(e)}")


def get_quality_indicators(rating: Optional[float], review_count: Optional[int], in_stock: bool) -> Dict[str, str]:
    """
    Get quality indicators for a product.

    Returns:
        Dict with rating_status, reviews_status, stock_status, overall_quality
    """
    # Rating status
    if rating is None:
        rating_status = "warning"
    elif rating >= 4.0:
        rating_status = "excellent"
    elif rating >= 3.0:
        rating_status = "warning"
    else:
        rating_status = "poor"

    # Review count status
    review_count = review_count or 0
    if review_count >= 50:
        reviews_status = "excellent"
    elif review_count >= 10:
        reviews_status = "warning"
    else:
        reviews_status = "poor"

    # Stock status
    stock_status = "in_stock" if in_stock else "out_of_stock"

    # Overall quality (worst of rating and reviews)
    if not in_stock:
        overall_quality = "poor"
    elif rating_status == "poor" or reviews_status == "poor":
        overall_quality = "poor"
    elif rating_status == "warning" or reviews_status == "warning":
        overall_quality = "warning"
    elif rating_status == "excellent" and reviews_status == "excellent":
        overall_quality = "excellent"
    else:
        overall_quality = "good"

    return {
        "rating_status": rating_status,
        "reviews_status": reviews_status,
        "stock_status": stock_status,
        "overall_quality": overall_quality
    }
