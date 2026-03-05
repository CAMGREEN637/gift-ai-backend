import httpx
import re
from bs4 import BeautifulSoup
from typing import Optional, Dict
import logging
import random
import time

logger = logging.getLogger(__name__)

# Realistic browser user agents that rotate
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


def extract_asin_from_url(url: str) -> Optional[str]:
    """Extract ASIN from Amazon URL."""
    # Pattern: /dp/{ASIN} or /gp/product/{ASIN}
    match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})', url)
    if match:
        return match.group(1)
    return None


def get_random_headers():
    """Get realistic browser headers"""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


async def scrape_amazon_product(url: str) -> Dict:
    """
    Scrape product details from Amazon URL with improved anti-blocking.
    """

    # Validate URL
    if not url or "amazon.com" not in url.lower():
        raise ValueError("Invalid Amazon URL")

    # Add small random delay to appear more human
    time.sleep(random.uniform(0.5, 1.5))

    try:
        async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                http2=True
        ) as client:

            logger.info("Fetching URL: %s" % url)
            response = await client.get(url, headers=get_random_headers())

            if response.status_code == 503:
                raise ValueError("Amazon is temporarily blocking requests. Try again in a few minutes.")

            if response.status_code != 200:
                raise ValueError("Failed to fetch page (HTTP %d)" % response.status_code)

            html = response.text

            if "api-services-support@amazon.com" in html or "Enter the characters you see below" in html:
                raise ValueError(
                    "Amazon CAPTCHA detected. Please try again in a few minutes or use a different network.")

            soup = BeautifulSoup(html, "html.parser")
            product_data = {}

            # --- Product Name ---
            name = None
            name_selectors = [
                {"id": "productTitle"},
                {"id": "title"},
                {"class": "product-title-word-break"},
            ]

            for selector in name_selectors:
                element = soup.find(**selector)
                if element:
                    name = element.get_text().strip()
                    if name: break

            if not name:
                raise ValueError("Could not extract product name.")

            product_data["name"] = name

            # --- Price ---
            price = 0.0
            price_patterns = [{"class": "a-price-whole"}, {"class": "a-offscreen"}]

            for pattern in price_patterns:
                element = soup.find(**pattern)
                if element:
                    price_text = element.get_text().strip()
                    match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
                    if match:
                        price = float(match.group())
                        break
            product_data["price"] = price

            # --- Description ---
            description = None
            desc_selectors = [{"id": "feature-bullets"}, {"id": "productDescription"}]

            for selector in desc_selectors:
                element = soup.find(**selector)
                if element:
                    description = re.sub(r'\s+', ' ', element.get_text().strip())[:500]
                    break
            product_data["description"] = description or "No description available"

            # --- Image URL ---
            img_element = soup.find("img", {"id": "landingImage"}) or soup.find("img", {"class": "a-dynamic-image"})
            product_data["image_url"] = img_element.get("src") if img_element else None

            # --- Brand ---
            brand = None
            brand_element = soup.find("a", {"id": "bylineInfo"})
            if brand_element:
                brand_text = brand_element.get_text().strip()
                brand = re.sub(r'^(Visit the |Brand: )', '', brand_text).replace(' Store', '').strip()
            product_data["brand"] = brand

            # --- NEW: ASIN Extraction ---
            asin = extract_asin_from_url(url)
            product_data["asin"] = asin
            if asin:
                logger.info("✓ Found ASIN: %s" % asin)

            # --- Rating & Reviews ---
            rating = None
            rating_element = soup.find("span", {"class": "a-icon-alt"})
            if rating_element:
                match = re.search(r'([\d.]+)\s*out of\s*5', rating_element.get_text())
                if match: rating = float(match.group(1))
            product_data["rating"] = rating

            review_count = None
            review_element = soup.find("span", {"id": "acrCustomerReviewText"})
            if review_element:
                match = re.search(r'([\d,]+)\s*ratings?', review_element.get_text())
                if match: review_count = int(match.group(1).replace(',', ''))
            product_data["review_count"] = review_count

            # Metadata and Defaults
            product_data.update({
                "link": url,
                "source": "amazon",
                "currency": "USD",
                "in_stock": True,
                "categories": [],
                "interests": [],
                "occasions": [],
                "vibe": [],
                "personality_traits": [],
                "recipient": {}
            })

            return product_data

    except Exception as e:
        logger.error("Scraping error: %s" % str(e))
        raise ValueError("Failed to scrape product: %s" % str(e))


def get_quality_indicators(rating: Optional[float], review_count: Optional[int], in_stock: bool) -> Dict:
    """Analyze product quality based on rating and reviews."""
    indicators = {
        "overall_quality": "unknown",
        "rating_score": "N/A",
        "review_score": "N/A",
        "stock_status": "in_stock" if in_stock else "out_of_stock",
        "recommended": False
    }

    if rating is not None:
        indicators["rating_score"] = "excellent" if rating >= 4.5 else "good" if rating >= 4.0 else "average"

    if review_count is not None:
        indicators["review_score"] = "highly_reviewed" if review_count >= 1000 else "well_reviewed"

    if rating and review_count:
        if rating >= 4.0 and review_count >= 100:
            indicators["overall_quality"] = "excellent"
            indicators["recommended"] = True

    return indicators
