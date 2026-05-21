#!/usr/bin/env python3
"""
Gift AI — Discovery Agent v3
=============================
Upgrades over v2:
  1. Price distribution fix — dual-tier queries per interest (standard + premium brand queries)
     targets the $50–$300 range that was previously missing
  2. Interest coverage fix — sparse interests (baking, wine, music, gaming, photography,
     art, hiking, camping, movies, makeup, running, cycling) moved to top of priority queue
  3. Vibe classification fix — overhauled prompt with explicit rules preventing "thoughtful"
     from being used as a catch-all; "luxe" and "romantic" now correctly applied
  4. Occasion sanitization — invalid tags (housewarming, wedding, etc.) stripped at insert
     time with fallback to ["birthday", "just_because"] if all tags are wiped

Usage:
    python gift_discovery_agent_v3.py [--dry-run] [--target 500] [--mode all|trends|static]

Install:
    pip install curl_cffi openai supabase python-dotenv beautifulsoup4 boto3

Environment variables (required):
    SUPABASE_URL
    SUPABASE_SERVICE_KEY
    OPENAI_API_KEY

Environment variables (optional):
    AMAZON_AFFILIATE_TAG          default: cbggiftapp637-20
    REDDIT_CLIENT_ID              Reddit API app client ID
    REDDIT_CLIENT_SECRET          Reddit API app client secret
    REDDIT_USER_AGENT             default: GiftAI/2.0
    AMAZON_PA_ACCESS_KEY          PA API (optional, falls back to scraping)
    AMAZON_PA_SECRET_KEY
    AMAZON_PA_PARTNER_TAG

Setup Reddit API (free, 60 req/min):
    1. Go to https://www.reddit.com/prefs/apps
    2. Create app → type: script
    3. Copy client_id (under app name) and secret
    4. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env
"""

import os
import re
import json
import time
import logging
import argparse
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import urllib.parse
import requests  # used for Reddit API (JSON endpoints, no bot detection needed)
from curl_cffi import requests as cffi_requests  # used for Amazon scraping — impersonates Chrome TLS fingerprint
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Global curl_cffi session — impersonates Chrome 120 TLS fingerprint.
# Amazon inspects the TLS handshake, not just User-Agent. This is the
# single biggest factor in bypassing their bot detection.
amazon_session = cffi_requests.Session(impersonate="chrome120")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── CONFIG ────────────────────────────────────────────────────────────────

AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "cbggiftapp637-20")
PRICE_MIN = 15.0
PRICE_MAX = 300.0
TARGET_TOTAL = 500
EMBED_DEDUP_THRESH = 0.93  # cosine similarity — above this = duplicate
TREND_MAX_QUERIES = 20  # cap trend-derived queries per run

INTEREST_TAGS = [
    "coffee", "cooking", "baking", "wine", "cocktails", "fitness", "running",
    "cycling", "yoga", "reading", "music", "gaming", "photography", "art",
    "travel", "hiking", "camping", "gardening", "movies", "fashion",
    "skincare", "makeup", "wellness", "home_decor", "pets",
]

GIFT_TYPE_TAGS = ["tech", "home", "outdoors", "fitness", "hobby", "beauty", "kitchen", "book", "fashion"]
VIBE_TAGS = ["cozy", "romantic", "sentimental", "luxe", "fun", "thoughtful", "pampering"]
OCCASION_TAGS = ["birthday", "valentines", "anniversary", "christmas", "mothers_day", "just_because", "apology"]
PRIORITY_INTERESTS = [
    # Completely uncovered in last run — highest priority
    "baking", "wine", "running", "cycling", "music", "gaming",
    "photography", "art", "hiking", "camping", "movies", "makeup",
    # Partially covered — still need premium price tier depth
    "fashion", "reading", "pets", "cooking", "cocktails", "travel", "gardening",
    # Already well covered — dedup will skip most, but premium queries may find gaps
    "skincare", "coffee", "fitness", "home_decor", "wellness", "yoga",
]

# Static queries — each interest has:
#   - Standard queries (broad, tend to surface $15–$50 products)
#   - Premium queries (brand-specific or price-signalled, surface $50–$300 products)
# This dual-tier approach fixes the price skew: 69% of gifts were under $30.
STATIC_QUERIES_BY_INTEREST: dict[str, list[str]] = {
    "skincare": [
        # Standard
        "skincare gift set for women", "face serum gift set women",
        "vitamin C skincare routine gift", "gua sha facial tool set gift",
        # Premium ($50–$300 targets)
        "Tatcha skincare gift set luxury", "La Mer moisturizer gift women",
        "Drunk Elephant skincare gift set", "luxury anti-aging skincare gift $100",
        "Sulwhasoo skincare gift set premium",
    ],
    "coffee": [
        # Standard
        "coffee lover gift for women", "pour over coffee set gift",
        "coffee subscription gift box", "travel coffee mug insulated gift",
        # Premium
        "Fellow Ode grinder gift coffee", "Ember smart mug gift",
        "luxury espresso machine gift $150", "Nespresso machine gift set",
        "premium coffee subscription gift $75",
    ],
    "fitness": [
        # Standard
        "fitness gift for her", "resistance bands gift set",
        "foam roller recovery kit gift", "athletic wear gift women",
        # Premium
        "Lululemon gift set women fitness", "Garmin fitness watch gift women",
        "Theragun massage gun gift", "luxury gym bag gift women $80",
        "Apple Watch gift women fitness",
    ],
    "home_decor": [
        # Standard
        "home decor gift for women", "luxury candle gift set",
        "throw blanket gift soft", "ceramic vase gift minimalist",
        # Premium
        "Diptyque candle gift set luxury", "Matouk linen gift women",
        "Anthropologie home gift set $75", "luxury diffuser gift set $100",
        "Jonathan Adler gift women home decor",
    ],
    "wellness": [
        # Standard
        "wellness gift basket for women", "meditation kit gift set",
        "aromatherapy diffuser gift", "crystal healing set gift",
        # Premium
        "Theragun wellness gift $150", "Hyperice recovery gift women",
        "luxury sauna blanket gift", "weighted blanket premium gift $80",
        "NuFace facial device gift women",
    ],
    "yoga": [
        # Standard
        "yoga gift set for women", "yoga block cork set gift",
        "yoga bag gift women", "meditation cushion gift set",
        # Premium
        "Manduka yoga mat gift premium", "Lululemon yoga gift set",
        "luxury meditation gift set $100", "Gaiam premium yoga kit gift",
        "yoga wheel gift set premium",
    ],
    "reading": [
        # Standard
        "book lover gift for women", "reading nook gift set cozy",
        "book subscription box gift", "literary themed candle gift",
        # Premium
        "Kindle Paperwhite gift set", "leather journal gift set premium",
        "BookTok book club gift set $60", "first edition book gift women",
        "luxury reading accessories gift set",
    ],
    "fashion": [
        # Standard
        "fashion gift for women", "silk scarf gift women",
        "sunglasses gift women", "leather wallet gift women",
        # Premium
        "designer silk scarf gift $100", "luxury handbag gift women $150",
        "Quay sunglasses gift set women", "Mejuri jewelry gift set",
        "cashmere scarf gift women luxury",
    ],
    "cooking": [
        # Standard
        "cooking gift for women", "gourmet spice set gift",
        "cookbook gift women", "artisan salt gift set",
        # Premium
        "Le Creuset gift women cooking", "Staub cocotte gift set",
        "luxury knife set gift women $100", "truffle oil gift set gourmet",
        "chef cooking class gift experience",
    ],
    "baking": [
        # Standard
        "baking gift set for women", "cookie decorating gift set",
        "baking cookbook gift women", "artisan bread baking kit gift",
        # Premium
        "KitchenAid attachment gift set baking", "Nordic Ware baking gift set",
        "luxury baking gift set $75", "sourdough starter kit gift premium",
        "Valrhona chocolate baking gift set",
    ],
    "wine": [
        # Standard
        "wine lover gift for her", "wine tasting kit gift",
        "wine glass set gift women", "wine subscription gift",
        # Premium
        "Riedel wine glass set gift", "wine aerator decanter gift $60",
        "luxury wine tasting gift set $100", "Coravin wine gift system",
        "premium wine subscription gift $80",
    ],
    "cocktails": [
        # Standard
        "cocktail making gift set women", "bartender kit gift",
        "mocktail gift set women", "cocktail recipe book gift",
        # Premium
        "Cocktail Kingdom bar tools gift", "luxury cocktail kit gift $75",
        "Japanese whisky gift set women", "premium bitters cocktail gift set",
        "crystal cocktail glasses gift set",
    ],
    "makeup": [
        # Standard
        "makeup gift set for women", "lipstick gift set women",
        "makeup brush set gift", "tinted moisturizer gift",
        # Premium
        "Charlotte Tilbury gift set makeup", "NARS makeup gift set luxury",
        "Natasha Denona eyeshadow gift", "luxury makeup gift set $80",
        "Pat McGrath makeup gift women",
    ],
    "travel": [
        # Standard
        "travel gift for women", "travel toiletry bag gift",
        "passport holder gift women", "packing cubes gift set women",
        # Premium
        "Away luggage gift women $275", "Beis weekender bag gift",
        "luxury travel set gift $100", "Paravel travel bag gift women",
        "cashmere travel blanket gift women",
    ],
    "running": [
        # Standard
        "running gift for women", "running belt waist pack gift",
        "compression socks gift runner", "hydration vest gift women",
        # Premium
        "Garmin GPS watch gift women running", "On Running shoes gift women",
        "Aftershokz headphones gift runner", "running jacket gift women $80",
        "Polar heart rate monitor gift women",
    ],
    "hiking": [
        # Standard
        "hiking gift for women", "hiking daypack gift women",
        "headlamp gift hiking women", "trail snack gift set",
        # Premium
        "Osprey hiking pack gift women", "Patagonia jacket gift women hiking",
        "Yeti tumbler gift hikers", "trekking poles gift premium women",
        "Arc'teryx gift women outdoor $150",
    ],
    "camping": [
        # Standard
        "camping gift for women", "hammock gift women outdoor",
        "camping lantern gift women", "outdoor blanket gift women",
        # Premium
        "REI camping gift set women", "Yeti cooler gift women camping",
        "luxury glamping gift set $100", "camp chair gift premium women",
        "Big Agnes sleeping bag gift women",
    ],
    "cycling": [
        # Standard
        "cycling gift for women", "bike accessories gift women",
        "water bottle cycling gift", "cycling jersey gift women",
        # Premium
        "Garmin cycling computer gift", "Rapha cycling gift women",
        "cycling helmet gift premium women", "bike light gift set premium",
        "Maap cycling kit gift women",
    ],
    "photography": [
        # Standard
        "photography gift for women", "camera strap gift women",
        "photo album gift personalized", "instant camera gift women",
        # Premium
        "Fujifilm Instax gift set premium", "camera bag gift women $80",
        "Polaroid Now camera gift set", "photo printing gift subscription",
        "leather camera strap gift premium",
    ],
    "art": [
        # Standard
        "art supply gift for women", "watercolor set gift women",
        "sketchbook gift premium", "pottery kit gift at home",
        # Premium
        "Winsor Newton watercolor gift set", "Procreate Apple Pencil gift",
        "pottery wheel gift women $100", "luxury art supply gift set $75",
        "painting class gift experience women",
    ],
    "music": [
        # Standard
        "music lover gift for women", "vinyl record gift women",
        "ukulele gift women beginner", "music subscription gift card",
        # Premium
        "Sony WH1000XM5 headphones gift", "Bose QuietComfort gift women",
        "turntable record player gift $150", "AirPods Pro gift women",
        "premium wireless earbuds gift women $100",
    ],
    "gaming": [
        # Standard
        "gaming gift for women", "cozy gaming gift set women",
        "Nintendo Switch gift accessories", "board game gift couples",
        # Premium
        "Nintendo Switch OLED gift women", "gaming chair gift women $150",
        "Steam gift card premium gaming", "gaming headset gift women $80",
        "Meta Quest VR headset gift",
    ],
    "gardening": [
        # Standard
        "gardening gift for women", "herb garden kit indoor gift",
        "succulent kit gift women", "garden apron gift women",
        # Premium
        "Terrain garden gift set premium", "Bonsai starter kit gift $60",
        "luxury seed collection gift women", "garden tool set premium gift $75",
        "aeroponics garden kit gift $100",
    ],
    "movies": [
        # Standard
        "movie lover gift for women", "movie night gift basket",
        "film photography gift women", "streaming subscription gift card",
        # Premium
        "Criterion Collection gift set films", "projector gift women home $150",
        "luxury home theater gift set", "4K projector gift women $200",
        "cinema light box gift premium",
    ],
    "pets": [
        # Standard
        "pet lover gift for women", "cat lover gift set women",
        "dog lover gift set women", "animal lover candle gift",
        # Premium
        "Furbo dog camera gift $150", "luxury pet portrait gift custom",
        "Whistle GPS tracker pet gift", "BarkBox premium gift subscription",
        "personalized pet jewelry gift women $75",
    ],
}

# ─── REDDIT SUBREDDITS FOR GIFT TREND SIGNALS ──────────────────────────────

REDDIT_GIFT_SUBREDDITS = [
    "r/gifts",
    "r/giftideas",
    "r/TheGirlSurvivalGuide",  # women's lifestyle — strong gift signal
    "r/AskWomen",
    "r/BuyItForLife",  # quality product discussions
    "r/femalefashionadvice",
    "r/SkincareAddiction",
    "r/MakeupAddiction",
    "r/weddingplanning",  # anniversary/occasion signals
    "r/dataisbeautiful",
]

REDDIT_GIFT_KEYWORDS = [
    "best gift", "gift idea", "gift for her", "she loved it", "bought her",
    "perfect gift", "recommend gift", "gift under", "gift around", "obsessed with",
    "trending", "everyone wants", "sold out", "viral", "must have",
]


# ─── TREND SIGNAL ──────────────────────────────────────────────────────────

@dataclass
class TrendSignal:
    term: str
    source: str  # "reddit" | "amazon_movers"
    score: float  # relative weight (upvotes, rank-based, etc.)
    raw_context: str  # original post title or product name
    subreddit: str = ""
    amazon_category: str = ""

    def __repr__(self):
        return f"TrendSignal({self.term!r} from {self.source}, score={self.score:.1f})"


@dataclass
class AgentStats:
    discovered: int = 0
    trend_signals: int = 0
    trend_queries_generated: int = 0
    classified: int = 0
    embedded: int = 0
    inserted: int = 0
    skipped_price: int = 0
    skipped_embed_dupe: int = 0
    skipped_name_dupe: int = 0
    skipped_not_gift: int = 0
    skipped_classification_fail: int = 0
    errors: int = 0
    start_time: datetime = field(default_factory=datetime.now)

    def report(self) -> str:
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return (
            f"\n{'─' * 55}\n"
            f"Agent v2 Run Summary ({elapsed:.0f}s elapsed)\n"
            f"{'─' * 55}\n"
            f"Trend signals collected:      {self.trend_signals}\n"
            f"Trend queries generated:      {self.trend_queries_generated}\n"
            f"Products discovered:          {self.discovered}\n"
            f"Classified:                   {self.classified}\n"
            f"Embedded:                     {self.embedded}\n"
            f"Inserted:                     {self.inserted}\n"
            f"Skipped (price):              {self.skipped_price}\n"
            f"Skipped (embed duplicate):    {self.skipped_embed_dupe}\n"
            f"Skipped (name duplicate):     {self.skipped_name_dupe}\n"
            f"Skipped (not gift-apt):       {self.skipped_not_gift}\n"
            f"Skipped (classify failed):    {self.skipped_classification_fail}\n"
            f"Errors:                       {self.errors}\n"
            f"{'─' * 55}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: TREND INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════

class RedditTrendScraper:
    """
    Pulls trending gift signals from Reddit using the official API.
    Free tier: 60 requests/minute, no approval needed for read-only.
    """

    BASE = "https://oauth.reddit.com"
    AUTH_URL = "https://www.reddit.com/api/v1/access_token"

    def __init__(self):
        self.client_id = os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        self.user_agent = os.getenv("REDDIT_USER_AGENT", "GiftAI/2.0 (gift recommendation bot)")
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_token(self) -> Optional[str]:
        if self._token and time.time() < self._token_expiry:
            return self._token
        if not self.configured:
            return None
        try:
            resp = requests.post(
                self.AUTH_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.user_agent},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
            logger.info("Reddit token acquired")
            return self._token
        except Exception as e:
            logger.warning(f"Reddit auth failed: {e}")
            return None

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        token = self._get_token()
        if not token:
            return None
        try:
            resp = requests.get(
                f"{self.BASE}{path}",
                headers={"Authorization": f"bearer {token}", "User-Agent": self.user_agent},
                params=params or {},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Reddit GET {path} failed: {e}")
            return None

    def fetch_signals(self, limit_per_sub: int = 25) -> list[TrendSignal]:
        """
        Fetch hot/top posts from gift subreddits and extract product mentions.
        Returns ranked TrendSignal list.
        """
        if not self.configured:
            logger.warning("Reddit not configured (REDDIT_CLIENT_ID/SECRET missing) — skipping")
            return []

        signals: list[TrendSignal] = []

        for sub in REDDIT_GIFT_SUBREDDITS:
            sub_name = sub.lstrip("r/")
            data = self._get(f"/r/{sub_name}/hot", params={"limit": limit_per_sub})
            if not data:
                continue

            posts = data.get("data", {}).get("children", [])
            for post in posts:
                p = post.get("data", {})
                title = p.get("title", "")
                selftext = p.get("selftext", "")
                score = p.get("score", 0)
                num_comments = p.get("num_comments", 0)

                # Only posts with meaningful engagement
                if score < 50 and num_comments < 5:
                    continue

                # Check if post is gift-relevant
                combined = (title + " " + selftext).lower()
                if not any(kw in combined for kw in REDDIT_GIFT_KEYWORDS):
                    continue

                # Extract product-like mentions (capitalized phrases, quoted strings)
                terms = self._extract_product_terms(title, selftext)
                for term in terms:
                    # Relevance weight: upvotes + comment engagement
                    weight = score + (num_comments * 3)
                    signals.append(TrendSignal(
                        term=term,
                        source="reddit",
                        score=float(weight),
                        raw_context=title[:120],
                        subreddit=sub_name,
                    ))

            time.sleep(0.5)  # polite: 2 req/s well within 60/min limit
            logger.info(f"Reddit r/{sub_name}: fetched {len(posts)} posts")

        # Also check r/gifts top of the week for weekly trend pulse
        week_data = self._get("/r/gifts/top", params={"t": "week", "limit": 25})
        if week_data:
            for post in week_data.get("data", {}).get("children", []):
                p = post.get("data", {})
                title = p.get("title", "")
                score = p.get("score", 0)
                terms = self._extract_product_terms(title, "")
                for term in terms:
                    signals.append(TrendSignal(
                        term=term,
                        source="reddit_weekly",
                        score=float(score * 1.5),  # weekly top = stronger signal
                        raw_context=title[:120],
                        subreddit="gifts",
                    ))

        logger.info(f"Reddit: collected {len(signals)} raw trend signals")
        return signals

    def _extract_product_terms(self, title: str, body: str) -> list[str]:
        """
        Extract product-like terms from post text.
        Looks for: brand+product combos, quoted strings, capitalized product names.
        """
        combined = title + " " + body[:300]
        terms = []

        # Quoted product names: "Ember Mug", 'silk pillowcase', etc.
        quoted = re.findall(r'["\']([A-Za-z][^"\']{3,40})["\']', combined)
        terms.extend(quoted)

        # Brand + product patterns: "Tatcha Water Cream", "Dyson Airwrap"
        # Heuristic: 2-4 consecutive capitalized words not at sentence start
        cap_phrases = re.findall(r'\b([A-Z][a-z]{1,15}(?:\s+[A-Z][a-z]{1,15}){1,3})\b', combined)
        terms.extend(cap_phrases)

        # Lowercase product mentions after "bought", "got", "love", "recommend"
        trigger_phrases = re.findall(
            r'(?:bought|got her|love|recommend|obsessed with|picked up)\s+(?:a\s+|the\s+)?([a-z][a-z\s]{4,40}?)(?:\.|,|!|\?|$)',
            combined.lower(),
        )
        terms.extend([t.strip() for t in trigger_phrases if len(t.strip()) > 4])

        # Deduplicate and filter noise
        seen = set()
        clean = []
        for t in terms:
            t = t.strip()
            t_lower = t.lower()
            if (
                    len(t) > 3
                    and t_lower not in seen
                    and not any(skip in t_lower for skip in ["http", "www", "edit", "update", "thanks"])
            ):
                seen.add(t_lower)
                clean.append(t)

        return clean[:5]  # cap per post


class AmazonMoversScraper:
    """
    Scrapes Amazon Movers & Shakers.
    Updated with session warming, retry logic, and resilient grid selectors.
    """

    MOVERS_URLS = [
        ("https://www.amazon.com/gp/movers-and-shakers/beauty", "beauty"),
        ("https://www.amazon.com/gp/movers-and-shakers/home-garden", "home"),
        ("https://www.amazon.com/gp/movers-and-shakers/fashion", "fashion"),
        ("https://www.amazon.com/gp/movers-and-shakers/sports", "fitness"),
        ("https://www.amazon.com/gp/movers-and-shakers/kitchen", "kitchen"),
        ("https://www.amazon.com/gp/movers-and-shakers/handmade", "hobby"),
    ]

    def __init__(self):
        self._session_warmed = False

    def _warm_session(self):
        """Hit the homepage first to establish standard routing cookies."""
        if self._session_warmed:
            return
        try:
            logger.info("Warming Amazon session cookies...")
            amazon_session.get("https://www.amazon.com/", headers=AMAZON_SCRAPE_HEADERS, timeout=10)
            time.sleep(random.uniform(2.0, 4.0))
            self._session_warmed = True
        except Exception as e:
            logger.warning(f"Session warming failed: {e}")

    def fetch_signals(self, top_n: int = 15) -> list[TrendSignal]:
        self._warm_session()
        signals: list[TrendSignal] = []

        for url, category in self.MOVERS_URLS:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Update Referer to look like natural navigation
                    headers = AMAZON_SCRAPE_HEADERS.copy()
                    headers["Referer"] = "https://www.amazon.com/"

                    resp = amazon_session.get(url, headers=headers, timeout=15)

                    if resp.status_code == 503:
                        backoff = random.uniform(15.0, 25.0) * (attempt + 1)
                        logger.warning(
                            f"503 on Movers ({category}) [Attempt {attempt + 1}/{max_retries}]. Backing off {backoff:.0f}s.")
                        time.sleep(backoff)
                        continue  # Goes to the next iteration of the retry loop

                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, "html.parser")

                    # Use structural targeting rather than ephemeral CSS classes
                    items = soup.select('div[id^="gridItemRoot"]')

                    # Fallback if gridItemRoot isn't present
                    if not items:
                        items = soup.select(".zg-item-immersion, [data-p13n-asin-metadata]")

                    found = 0
                    for rank, item in enumerate(items[:top_n], start=1):
                        # Extract name: Grid items usually have the title in an image alt tag or an explicit a-link-normal text span
                        name = ""

                        # Strategy A: Check image alt text (very stable)
                        img_el = item.select_one('img')
                        if img_el and img_el.get('alt'):
                            name = img_el.get('alt').strip()

                        # Strategy B: Check text content
                        if not name or len(name) < 5:
                            name_el = (
                                    item.select_one("a.a-link-normal div:not(:has(img))")
                                    or item.select_one("span.a-text-normal")
                                    or item.select_one(".p13n-sc-truncate")
                            )
                            if name_el:
                                name = name_el.get_text(strip=True)

                        if len(name) < 5:
                            continue

                        rank_score = float(top_n - rank + 1)

                        signals.append(TrendSignal(
                            term=name,
                            source="amazon_movers",
                            score=rank_score * 10,
                            raw_context=f"Amazon Movers & Shakers #{rank} in {category}",
                            amazon_category=category,
                        ))
                        found += 1

                    logger.info(f"Amazon Movers ({category}): found {found} products")
                    time.sleep(random.uniform(3.0, 6.0))
                    break  # Success, break out of the retry loop

                except Exception as e:
                    logger.warning(f"Amazon Movers scrape failed for {category} on attempt {attempt + 1}: {e}")
                    time.sleep(random.uniform(5.0, 10.0))

        logger.info(f"Amazon Movers: collected {len(signals)} raw trend signals")
        return signals


def merge_and_rank_signals(signals: list[TrendSignal]) -> list[TrendSignal]:
    """
    Merge signals by term similarity, sum scores across sources.
    A term appearing in both Reddit AND Amazon Movers gets a cross-source boost.
    Returns ranked list (highest score first).
    """
    # Group by normalized term
    grouped: dict[str, list[TrendSignal]] = {}
    for sig in signals:
        key = re.sub(r'\s+', ' ', sig.term.lower().strip())
        # Simple fuzzy grouping: strip possessives, trailing s
        key = re.sub(r"'s|'s", "", key).rstrip("s").strip()
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(sig)

    merged: list[TrendSignal] = []
    for key, group in grouped.items():
        total_score = sum(s.score for s in group)
        sources = {s.source for s in group}
        # Cross-source bonus: seen on both Reddit AND Amazon = 2x multiplier
        if len(sources) > 1:
            total_score *= 2.0
            logger.info(f"Cross-source signal: '{key}' (sources: {sources})")
        best = max(group, key=lambda s: s.score)
        merged.append(TrendSignal(
            term=best.term,
            source="+".join(sorted(sources)),
            score=total_score,
            raw_context=best.raw_context,
            subreddit=best.subreddit,
            amazon_category=best.amazon_category,
        ))

    merged.sort(key=lambda s: s.score, reverse=True)
    return merged


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: TREND → AMAZON SEARCH QUERY EXPANSION
# ═══════════════════════════════════════════════════════════════════════════

TREND_EXPANSION_SYSTEM = """You are a gift search query generator for an Amazon product discovery agent.

Given a list of trending product terms or gift signals, generate focused Amazon search queries
that will surface GIFT-APPROPRIATE products for women (from their boyfriend/husband/partner).

Rules:
- Each query should be 4-8 words
- Frame as gift searches: "X gift for women", "X gift set her", etc.
- Keep brand names when present (Dyson, Tatcha, Ember, etc.)
- Skip anything clearly male-targeted, kitchen appliance, or outside $15-$300
- Generate 1-2 queries per trend term
- Return ONLY a JSON array of strings, no explanation

Example input: ["sunset projector", "silk pillowcase", "Dyson Airwrap"]
Example output: ["sunset projector gift women", "aesthetic light projector gift her", "silk pillowcase gift set women luxury", "Dyson Airwrap gift for girlfriend"]"""


def expand_trends_to_queries(openai_client, signals: list[TrendSignal], max_signals: int = 15) -> list[dict]:
    """
    Uses GPT-4o-mini to turn trend signals into Amazon search queries.
    Returns list of {"query": str, "interest_hint": str, "source": str, "trend_term": str}
    """
    top_signals = signals[:max_signals]
    terms = [s.term for s in top_signals]

    if not terms:
        return []

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=400,
            temperature=0.3,
            messages=[
                {"role": "system", "content": TREND_EXPANSION_SYSTEM},
                {"role": "user", "content": json.dumps(terms)},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        queries = json.loads(raw)

        result = []
        for i, q in enumerate(queries):
            if isinstance(q, str) and len(q) > 5:
                # Map back to originating signal for logging
                source_signal = top_signals[i // 2] if i // 2 < len(top_signals) else top_signals[-1]
                result.append({
                    "query": q,
                    "interest_hint": "trend",
                    "source": source_signal.source,
                    "trend_term": source_signal.term,
                })

        logger.info(f"Trend expansion: {len(terms)} signals → {len(result)} search queries")
        return result

    except Exception as e:
        logger.warning(f"Trend expansion failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: EMBEDDING-BASED DEDUPLICATION
# ═══════════════════════════════════════════════════════════════════════════

class EmbedDeduplicator:
    """
    Uses pgvector similarity search to detect near-duplicate products before insert.

    Why this beats name-matching:
      "Ember Mug 2"
      "Ember Temperature Control Smart Mug"
      "Heated Smart Coffee Mug by Ember"
    All three share embedding similarity > 0.93 — correctly flagged as duplicates.

    Strategy:
      1. Generate embedding for candidate product
      2. Query Supabase match_gifts with threshold 0.93, limit 3
      3. If any result returns: candidate is a duplicate → skip
      4. If no results: unique → proceed to insert
    """

    def __init__(self, supabase, openai_client):
        self.supabase = supabase
        self.openai_client = openai_client
        self._cache_hits = 0
        self._cache_misses = 0

    def is_duplicate(self, embed_text: str, embedding: list[float]) -> tuple[bool, Optional[str]]:
        """
        Check if a product with this embedding already exists in the DB.
        Returns (is_duplicate, matched_name_if_dupe).

        Uses the existing match_gifts RPC — same function retrieval.py uses —
        so no extra Supabase function needed.
        """
        try:
            response = self.supabase.rpc(
                "match_gifts",
                {
                    "query_embedding": embedding,
                    "match_threshold": EMBED_DEDUP_THRESH,
                    "match_count": 3,
                },
            ).execute()

            matches = response.data or []
            if matches:
                best = matches[0]
                matched_name = best.get("name", "unknown")
                similarity = best.get("similarity", 0)
                logger.debug(
                    f"Embed dupe detected: sim={similarity:.3f} → '{matched_name}'"
                )
                self._cache_hits += 1
                return True, matched_name

            self._cache_misses += 1
            return False, None

        except Exception as e:
            logger.warning(f"Dedup query failed: {e} — allowing insert")
            return False, None

    def stats(self) -> str:
        total = self._cache_hits + self._cache_misses
        rate = self._cache_hits / total * 100 if total else 0
        return f"Dedup: {self._cache_hits} dupes caught / {total} checked ({rate:.1f}% dupe rate)"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: AMAZON PRODUCT DISCOVERY (unchanged from v1)
# ═══════════════════════════════════════════════════════════════════════════

def build_affiliate_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}?tag={AFFILIATE_TAG}"


# Fortified headers matching a real Chrome 120 browser navigation request.
# curl_cffi handles the User-Agent automatically to match the impersonate flag,
# so we omit it here — adding a mismatched UA would break the fingerprint.
AMAZON_SCRAPE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def _extract_name(item) -> str:
    """
    Multi-selector name extraction — resilient to Amazon A/B layout tests.
    Amazon frequently rotates HTML structure; trying multiple selectors in
    priority order means a layout change breaks one path, not all of them.
    """
    selectors = [
        "h2 a span",
        "h2 span.a-text-normal",
        "[data-cy='title-recipe'] span",
        "a.a-link-normal span.a-text-normal",
        "div.s-title-instructions-style span",
        "span.a-size-medium.a-color-base.a-text-normal",
    ]
    for sel in selectors:
        el = item.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text:
                return text
    return ""


def _extract_price(item) -> Optional[float]:
    """
    Multi-selector price extraction — handles split whole/fraction format
    and the hidden .a-offscreen span Amazon uses for accessibility
    (more stable across layout variants than the visible price elements).
    """
    # Try the hidden accessibility span first — most layout-stable
    offscreen = item.select_one(".a-price .a-offscreen")
    if offscreen:
        try:
            raw = offscreen.get_text(strip=True).replace("$", "").replace(",", "")
            price = float(raw)
            if PRICE_MIN <= price <= PRICE_MAX:
                return price
        except ValueError:
            pass

    # Fall back to split whole + fraction
    whole_el = item.select_one(".a-price-whole")
    frac_el = item.select_one(".a-price-fraction")
    if whole_el:
        try:
            whole_text = whole_el.get_text(strip=True).replace(",", "").replace(".", "")
            price = float(whole_text)
            if frac_el:
                price += float(frac_el.get_text(strip=True)) / 100
            # Sanity check: if price looks like cents (e.g. 4999), convert
            if price > PRICE_MAX * 10:
                price /= 100
            if PRICE_MIN <= price <= PRICE_MAX:
                return price
        except ValueError:
            pass

    # Last resort: any data-a-color="price" span
    price_el = item.select_one("[data-a-color='price'] span")
    if price_el:
        try:
            raw = price_el.get_text(strip=True).replace("$", "").replace(",", "")
            price = float(raw)
            if PRICE_MIN <= price <= PRICE_MAX:
                return price
        except ValueError:
            pass

    return None


def search_amazon_scraping(query: str) -> list[dict]:
    """
    Amazon product search using curl_cffi (Chrome TLS impersonation).

    Improvements over v1:
    - curl_cffi replaces requests → bypasses TLS fingerprint detection
    - Fortified headers match a real Chrome navigation request
    - 503 triggers graceful backoff instead of crash/silent fail
    - Jitter includes occasional human-style reading pauses
    - Multi-selector extraction handles A/B layout variants
    """
    search_url = (
        f"https://www.amazon.com/s"
        f"?k={urllib.parse.quote(query)}"
        f"&rh=p_36%3A1500-30000"  # $15–$300 price filter in cents
    )

    try:
        resp = amazon_session.get(search_url, headers=AMAZON_SCRAPE_HEADERS, timeout=15)

        # 503 = bot wall / CAPTCHA. Back off gracefully — don't retry immediately.
        if resp.status_code == 503:
            backoff = random.uniform(12.0, 18.0)
            logger.warning(f"503 bot protection hit for '{query}'. Backing off {backoff:.0f}s.")
            time.sleep(backoff)
            return []

        resp.raise_for_status()

    except Exception as e:
        logger.warning(f"Amazon search failed for '{query}': {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []

    for item in soup.select('[data-component-type="s-search-result"]')[:8]:
        try:
            asin = item.get("data-asin", "")
            if not asin:
                continue

            name = _extract_name(item)
            if not name:
                continue

            price = _extract_price(item)
            if price is None:
                continue

            img_el = item.select_one("img.s-image")
            image_url = img_el.get("src", "") if img_el else ""

            products.append({
                "asin": asin,
                "name": name,
                "price": price,
                "image_url": image_url,
                "link": build_affiliate_url(asin),
                "description": name,
            })
        except Exception:
            continue

    logger.info(f"Scraped {len(products)} products for '{query}'")

    # Randomised jitter with occasional human-style reading pause (Gemini suggestion #4)
    base_sleep = random.uniform(2.0, 5.0)
    if random.random() < 0.1:  # 10% chance of a longer "reading" pause
        base_sleep += random.uniform(5.0, 10.0)
    time.sleep(base_sleep)

    return products


def search_amazon_pa_api(query: str) -> list[dict]:
    """PA API v5 — only runs if credentials are set."""
    access_key = os.getenv("AMAZON_PA_ACCESS_KEY")
    secret_key = os.getenv("AMAZON_PA_SECRET_KEY")
    partner_tag = os.getenv("AMAZON_PA_PARTNER_TAG", AFFILIATE_TAG)

    if not access_key or not secret_key:
        return []

    try:
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        payload = {
            "Keywords": query,
            "Resources": ["ItemInfo.Title", "Offers.Listings.Price", "Images.Primary.Large"],
            "SearchIndex": "All",
            "PartnerTag": partner_tag,
            "PartnerType": "Associates",
            "Marketplace": "www.amazon.com",
            "ItemCount": 10,
            "MinPrice": int(PRICE_MIN * 100),
            "MaxPrice": int(PRICE_MAX * 100),
        }

        host = "webservices.amazon.com"
        endpoint = f"https://{host}/paapi5/searchitems"
        creds = Credentials(access_key, secret_key)
        req = AWSRequest(
            method="POST", url=endpoint,
            data=json.dumps(payload),
            headers={
                "content-type": "application/json; charset=UTF-8",
                "host": host,
                "x-amz-target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
            },
        )
        SigV4Auth(creds, "ProductAdvertisingAPI", "us-east-1").add_auth(req)

        resp = requests.post(endpoint, data=req.body, headers=dict(req.headers), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"PA API failed for '{query}': {e}")
        return []

    products = []
    for item in data.get("SearchResult", {}).get("Items", []):
        try:
            asin = item.get("ASIN", "")
            name = item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "")
            price = float(item.get("Offers", {}).get("Listings", [{}])[0].get("Price", {}).get("Amount", 0))
            if not (PRICE_MIN <= price <= PRICE_MAX):
                continue
            image_url = item.get("Images", {}).get("Primary", {}).get("Large", {}).get("URL", "")
            products.append({"asin": asin, "name": name, "price": price, "image_url": image_url,
                             "link": build_affiliate_url(asin), "description": name})
        except Exception:
            continue

    logger.info(f"PA API: {len(products)} products for '{query}'")
    return products


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: CLASSIFICATION + EMBEDDING
# ═══════════════════════════════════════════════════════════════════════════

CLASSIFY_SYSTEM = """You are a product taxonomy classifier for a gift recommendation app (men buying gifts for girlfriends/wives).

Return ONLY valid JSON — no markdown, no preamble, no explanation.

--- TAXONOMY ---

interests (pick 1-4, ONLY from this exact list):
coffee, cooking, baking, wine, cocktails, fitness, running, cycling, yoga, reading, music, gaming, photography, art, travel, hiking, camping, gardening, movies, fashion, skincare, makeup, wellness, home_decor, pets

gift_type (pick 1-3, ONLY from this exact list):
tech, home, outdoors, fitness, hobby, beauty, kitchen, book, fashion

vibe (pick 1-3, ONLY from this exact list):
cozy, romantic, sentimental, luxe, fun, thoughtful, pampering

VIBE ASSIGNMENT RULES — read carefully, do not default to "thoughtful":
- "luxe": price over $60 OR brand is known luxury (Tatcha, La Mer, Diptyque, Lululemon, Riedel, Le Creuset, Sony, Bose, Away, Patagonia, Arc'teryx). This is the most under-used tag — lean into it for premium items.
- "romantic": jewelry, lingerie, perfume, candles for two, couples experiences, roses, heart motifs, date-night items. Use for valentines/anniversary gifts.
- "sentimental": personalized items, photo gifts, custom engravings, keepsakes, "first" items (first home, first anniversary), memory books.
- "pampering": spa, bath, skincare, massage, self-care rituals, face masks, body scrubs, anything indulgent.
- "cozy": blankets, slippers, warm drinks, lounge wear, candles, reading nooks, anything soft/warm/stay-at-home.
- "fun": games, novelty items, experiences, humorous gifts, activities.
- "thoughtful": ONLY use when none of the above fit. Do NOT use as a catch-all. If unsure between thoughtful and another vibe, pick the other vibe.

occasions (pick 2-5, ONLY from this exact list — do NOT invent others):
birthday, valentines, anniversary, christmas, mothers_day, just_because, apology

OCCASION RULES:
- ONLY use occasions from the list above. Never use: housewarming, wedding, bridal_shower, thanksgiving, get_well, graduation, back_to_school, or any other occasion.
- "valentines" and "anniversary": use for romantic, luxe, or sentimental items
- "apology": use sparingly — only for truly versatile, peace-offering items
- "just_because": default fallback for any gift that works any time
- Every gift must have at least 2 occasions

gender_skew: "female" | "male" | "unisex"
- Default to "female" for beauty, skincare, yoga, wellness, home decor
- "unisex" for tech, books, food/drink items
- "male" only if clearly male-targeted

is_gift_appropriate: true | false
- false = digital download only, perishable food, strictly utilitarian (toilet paper, cleaning supplies), or price outside $15-$300

description_for_embedding: 2-3 sentences.
- What it IS and what experience/feeling it creates
- Who it's for ("the woman who loves her morning ritual", "for the partner who has everything")
- Include relevant vibes and interest signals naturally
- Warm editorial tone. No invented specs or features.

--- JSON SHAPE (return exactly this, nothing else) ---
{"interests":[],"gift_type":[],"vibe":[],"occasions":[],"gender_skew":"female","is_gift_appropriate":true,"description_for_embedding":""}"""


def classify_product(openai_client, name: str, description: str, price: float) -> Optional[dict]:
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=500,
            temperature=0.1,
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user", "content": f"Name: {name}\nPrice: ${price:.2f}\nDescription: {description}"},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Classify failed for '{name}': {e}")
        return None


def generate_embedding(openai_client, text: str) -> Optional[list[float]]:
    try:
        resp = openai_client.embeddings.create(model="text-embedding-3-small", input=text[:8000])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return None


def build_embed_text(name: str, description: str, interests: list, gift_type: list) -> str:
    parts = [name, description]
    if interests:
        parts.append("Interests: " + ", ".join(interests))
    if gift_type:
        parts.append("Gift type: " + ", ".join(gift_type))
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: SUPABASE
# ═══════════════════════════════════════════════════════════════════════════

def get_supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


def get_db_count(supabase) -> int:
    resp = supabase.table("gifts").select("id", count="exact").execute()
    return resp.count or 0


def get_existing_names(supabase) -> set[str]:
    resp = supabase.table("gifts").select("name").execute()
    return {r["name"].lower().strip() for r in (resp.data or [])}


def insert_gift(supabase, row: dict, dry_run: bool = False) -> bool:
    if dry_run:
        logger.info(f"[DRY RUN] Would insert: {row['name']} (${row['price']})")
        return True
    try:
        # Final ASIN-level dedup
        if "/dp/" in (row.get("link") or ""):
            asin = row["link"].split("/dp/")[1].split("?")[0]
            existing = supabase.table("gifts").select("id").ilike("link", f"%/dp/{asin}%").execute()
            if existing.data:
                logger.info(f"ASIN dupe on insert, skipping: {row['name']}")
                return False
        supabase.table("gifts").insert(row).execute()
        logger.info(f"✓ Inserted: {row['name']} (${row['price']})")
        return True
    except Exception as e:
        logger.warning(f"Insert failed for '{row.get('name')}': {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: MAIN AGENT LOOP
# ═══════════════════════════════════════════════════════════════════════════

def get_static_queries() -> list[dict]:
    queries = []
    for interest in PRIORITY_INTERESTS:
        for q in STATIC_QUERIES_BY_INTEREST.get(interest, []):
            queries.append({"query": q, "interest_hint": interest, "source": "static", "trend_term": None})
    for interest in INTEREST_TAGS:
        if interest in PRIORITY_INTERESTS:
            continue
        for q in STATIC_QUERIES_BY_INTEREST.get(interest, []):
            queries.append({"query": q, "interest_hint": interest, "source": "static", "trend_term": None})
    return queries


def process_product(
        product: dict,
        openai_client,
        supabase,
        deduplicator: EmbedDeduplicator,
        existing_names: set[str],
        stats: AgentStats,
        dry_run: bool,
) -> bool:
    """
    Full pipeline for a single candidate product.
    Returns True if successfully inserted.
    """
    name = product.get("name", "").strip()
    price = product.get("price", 0.0)

    # 1. Price gate
    if not (PRICE_MIN <= price <= PRICE_MAX):
        stats.skipped_price += 1
        return False

    # 2. Fast name dedup (cheap — avoids unnecessary API calls)
    name_lower = name.lower().strip()
    if name_lower in existing_names:
        stats.skipped_name_dupe += 1
        return False

    # 3. Classify
    classification = classify_product(
        openai_client,
        name=name,
        description=product.get("description", name),
        price=price,
    )
    if not classification:
        stats.skipped_classification_fail += 1
        return False
    stats.classified += 1

    if not classification.get("is_gift_appropriate", True):
        stats.skipped_not_gift += 1
        return False

    # 4. Generate embedding
    embed_text = build_embed_text(
        name=name,
        description=classification.get("description_for_embedding", name),
        interests=classification.get("interests", []),
        gift_type=classification.get("gift_type", []),
    )
    embedding = generate_embedding(openai_client, embed_text)
    if not embedding:
        stats.errors += 1
        return False
    stats.embedded += 1

    # 5. Embedding-based dedup (the real dedup layer)
    is_dupe, matched_name = deduplicator.is_duplicate(embed_text, embedding)
    if is_dupe:
        logger.info(f"  ⊘ Embed dupe: '{name}' ≈ '{matched_name}'")
        stats.skipped_embed_dupe += 1
        existing_names.add(name_lower)  # add to fast cache too
        return False

    # 6. Sanitize taxonomy fields — strip any values outside the known tag sets.
    # The LLM occasionally invents tags (e.g. "housewarming", "beauty" as an interest).
    # We strip them here rather than relying solely on the prompt.
    VALID_INTERESTS  = set(INTEREST_TAGS)
    VALID_GIFT_TYPES = set(GIFT_TYPE_TAGS)
    VALID_VIBES      = set(VIBE_TAGS)
    VALID_OCCASIONS  = set(OCCASION_TAGS)
    VALID_GENDERS    = {"female", "male", "unisex"}

    raw_occasions = classification.get("occasions", [])
    clean_occasions = [o for o in raw_occasions if o in VALID_OCCASIONS]
    # If sanitization wiped all occasions, fall back to sensible defaults
    if not clean_occasions:
        clean_occasions = ["birthday", "just_because"]
        logger.debug(f"Occasion fallback applied for: {name[:60]}")

    clean_interests = [i for i in classification.get("interests", []) if i in VALID_INTERESTS]
    clean_gift_type = [t for t in classification.get("gift_type", []) if t in VALID_GIFT_TYPES]
    clean_vibe      = [v for v in classification.get("vibe", []) if v in VALID_VIBES]
    clean_gender    = classification.get("gender_skew", "unisex")
    if clean_gender not in VALID_GENDERS:
        clean_gender = "unisex"

    # 7. Build row and insert
    gift_row = {
        "name": name,
        "display_name": name,
        "description": classification.get("description_for_embedding", name),
        "price": price,
        "currency": "USD",
        "link": product.get("link", ""),
        "image_url": product.get("image_url", ""),
        "brand": product.get("brand"),
        "interests": clean_interests,
        "gift_type": clean_gift_type,
        "vibe": clean_vibe,
        "occasions": clean_occasions,
        "gender_skew": clean_gender,
        "is_prime_eligible": False,
        "shipping_min_days": 2,
        "shipping_max_days": 5,
        "embedding": embedding,
        "rating": None,
    }

    success = insert_gift(supabase, gift_row, dry_run=dry_run)
    if success:
        stats.inserted += 1
        existing_names.add(name_lower)
    return success


def run_agent(dry_run: bool = False, target: int = TARGET_TOTAL, mode: str = "all"):
    logger.info("=" * 60)
    logger.info(f"Gift AI Discovery Agent v2 | mode={mode} | dry_run={dry_run}")
    logger.info("=" * 60)

    # Init
    supabase = get_supabase()
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    deduplicator = EmbedDeduplicator(supabase, openai_client)
    stats = AgentStats()
    existing_names = get_existing_names(supabase)
    current_count = get_db_count(supabase)
    needed = target - current_count

    logger.info(f"DB: {current_count} gifts | Target: {target} | Need: {needed}")
    if needed <= 0:
        logger.info("Target already met.")
        return

    use_pa_api = bool(os.getenv("AMAZON_PA_ACCESS_KEY"))

    # ── PHASE 1: TREND INTELLIGENCE ──────────────────────────────────────
    trend_queries: list[dict] = []

    if mode in ("all", "trends"):
        logger.info("\n── Phase 1: Collecting trend signals ──")

        # Reddit
        reddit = RedditTrendScraper()
        reddit_signals = reddit.fetch_signals(limit_per_sub=25)

        # Amazon Movers & Shakers
        movers = AmazonMoversScraper()
        mover_signals = movers.fetch_signals(top_n=15)

        # Merge + rank
        all_signals = merge_and_rank_signals(reddit_signals + mover_signals)
        stats.trend_signals = len(all_signals)

        if all_signals:
            logger.info(f"\nTop 10 trend signals:")
            for sig in all_signals[:10]:
                logger.info(f"  [{sig.score:6.0f}] {sig.term!r:40s} ({sig.source})")

            # Expand trends to Amazon search queries
            trend_queries = expand_trends_to_queries(
                openai_client, all_signals, max_signals=TREND_MAX_QUERIES
            )
            stats.trend_queries_generated = len(trend_queries)
            logger.info(f"\nTrend-derived queries: {len(trend_queries)}")
            for tq in trend_queries[:5]:
                logger.info(f"  → '{tq['query']}' (from: {tq['trend_term']})")

    # ── PHASE 2: BUILD FULL QUERY LIST ───────────────────────────────────
    # Trend queries first (higher signal), then static fallbacks
    all_queries: list[dict] = []

    if mode in ("all", "trends"):
        all_queries.extend(trend_queries)

    if mode in ("all", "static"):
        all_queries.extend(get_static_queries())

    logger.info(
        f"\n── Phase 2: {len(all_queries)} total queries ({len(trend_queries)} trend, {len(all_queries) - len(trend_queries)} static)")

    # ── PHASE 3: DISCOVER + PROCESS ──────────────────────────────────────
    logger.info("\n── Phase 3: Product discovery ──")
    inserted_this_run = 0

    for i, query_obj in enumerate(all_queries):
        if inserted_this_run >= needed:
            logger.info(f"Target reached ({target} gifts). Stopping.")
            break

        query = query_obj["query"]
        source = query_obj.get("source", "static")
        trend_term = query_obj.get("trend_term")

        prefix = "🔥 TREND" if source != "static" else "   static"
        suffix = f" (trend: {trend_term})" if trend_term else ""
        logger.info(f"\n[{i + 1}/{len(all_queries)}] {prefix} '{query}'{suffix}")

        # Discover products
        products = search_amazon_pa_api(query) if use_pa_api else search_amazon_scraping(query)
        stats.discovered += len(products)

        for product in products:
            if inserted_this_run >= needed:
                break

            ok = process_product(
                product=product,
                openai_client=openai_client,
                supabase=supabase,
                deduplicator=deduplicator,
                existing_names=existing_names,
                stats=stats,
                dry_run=dry_run,
            )
            if ok:
                inserted_this_run += 1
                if inserted_this_run % 10 == 0:
                    logger.info(f"Progress: {current_count + inserted_this_run}/{target}")

            time.sleep(random.uniform(0.3, 0.7))

    # ── DONE ─────────────────────────────────────────────────────────────
    logger.info(deduplicator.stats())
    logger.info(stats.report())
    logger.info(f"Estimated final count: {current_count + inserted_this_run}")


# ─── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gift AI Discovery Agent v2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target", type=int, default=TARGET_TOTAL)
    parser.add_argument(
        "--mode", choices=["all", "trends", "static"], default="all",
        help="all=trends+static | trends=trend queries only | static=predefined only"
    )
    args = parser.parse_args()
    run_agent(dry_run=args.dry_run, target=args.target, mode=args.mode)

def insert_gift(supabase, row: dict, dry_run: bool = False) -> bool:
    if dry_run:
        logger.info(f"[DRY RUN] Would insert: {row['name']} (${row['price']})")
        return True
    try:
        if "/dp/" in (row.get("link") or ""):
            asin = row["link"].split("/dp/")[1].split("?")[0]
            existing = supabase.table("gifts").select("id").ilike("link", f"%/dp/{asin}%").execute()
            if existing.data:
                logger.info(f"ASIN dupe: {row['name']} | ASIN: {asin} | matched: {existing.data[0]}")
                return False
        supabase.table("gifts").insert(row).execute()
        logger.info(f"✓ Inserted: {row['name']} (${row['price']})")
        return True
    except Exception as e:
        logger.warning(f"Insert failed for '{row.get('name')}': {e}")
        return False