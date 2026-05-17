#!/usr/bin/env python3
"""
Gift AI — Discovery Agent v2
=============================
Upgrades over v1:
  1. Trend intelligence — Reddit API + Amazon Movers & Shakers
  2. Embedding-based deduplication (pgvector similarity > 0.93)
  3. Trend-to-query expansion via GPT-4o-mini

Usage:
    python gift_discovery_agent_v2.py [--dry-run] [--target 500] [--mode all|trends|static]

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

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

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
PRIORITY_INTERESTS = ["skincare", "coffee", "fitness", "home_decor", "wellness", "yoga", "reading", "fashion"]

# Static fallback queries (same as v1) — used when trend layer yields nothing
STATIC_QUERIES_BY_INTEREST: dict[str, list[str]] = {
    "skincare": ["luxury skincare gift set for women", "face serum gift set women", "vitamin C skincare routine gift",
                 "gua sha facial tool set gift", "retinol cream gift women"],
    "coffee": ["coffee lover gift for women", "pour over coffee set gift", "coffee subscription gift box",
               "espresso gift set women", "travel coffee mug insulated gift"],
    "fitness": ["fitness gift for her", "yoga mat gift set women", "resistance bands gift set",
                "foam roller recovery kit gift", "athletic wear gift women"],
    "home_decor": ["home decor gift for women", "luxury candle gift set", "aesthetic desk organizer gift",
                   "throw blanket gift soft", "ceramic vase gift minimalist"],
    "wellness": ["wellness gift basket for women", "meditation kit gift set", "aromatherapy diffuser gift",
                 "bath and body gift set luxury", "crystal healing set gift"],
    "yoga": ["yoga gift set for women", "yoga block cork set gift", "yoga bag gift women",
             "aromatherapy yoga mat spray gift", "meditation cushion gift set"],
    "reading": ["book lover gift for women", "reading nook gift set cozy", "book subscription box gift",
                "kindle accessories gift set", "literary themed candle gift"],
    "fashion": ["fashion gift for women", "silk scarf gift women luxury", "jewelry gift set for her",
                "sunglasses gift women", "leather wallet gift women"],
    "cooking": ["cooking gift for women", "gourmet spice set gift", "cookbook gift women", "chef knife set gift",
                "artisan salt gift set"],
    "baking": ["baking gift set for women", "stand mixer attachment gift", "artisan bread baking kit gift",
               "cookie decorating gift set", "baking cookbook gift women"],
    "wine": ["wine lover gift for her", "wine tasting kit gift", "wine aerator decanter gift set",
             "wine subscription gift", "wine glass set gift women"],
    "cocktails": ["cocktail making gift set women", "bartender kit gift", "mocktail gift set women",
                  "cocktail recipe book gift", "whiskey stone set gift women"],
    "makeup": ["makeup gift set for women", "luxury eyeshadow palette gift", "lipstick gift set women",
               "makeup brush set gift", "tinted moisturizer gift"],
    "travel": ["travel gift for women", "travel toiletry bag gift", "passport holder gift women",
               "travel pillow luxury gift", "packing cubes gift set women"],
    "running": ["running gift for women", "running belt waist pack gift", "GPS watch gift women running",
                "compression socks gift runner", "hydration vest gift women"],
    "hiking": ["hiking gift for women", "trekking poles gift women", "hiking daypack gift women",
               "headlamp gift hiking women", "trail snack gift set"],
    "camping": ["camping gift for women", "hammock gift women outdoor", "camping lantern gift women",
                "camp mug insulated gift", "outdoor blanket gift women"],
    "cycling": ["cycling gift for women", "bike accessories gift women", "cycling jersey gift women",
                "water bottle cycling gift", "bike lock gift women"],
    "photography": ["photography gift for women", "camera strap gift women", "photo album gift personalized",
                    "instant camera gift women", "camera bag gift women"],
    "art": ["art supply gift for women", "watercolor set gift women", "sketchbook gift premium",
            "pottery kit gift at home", "painting class gift set"],
    "music": ["music lover gift for women", "wireless earbuds gift women", "vinyl record gift women",
              "ukulele gift women beginner", "music subscription gift card"],
    "gaming": ["gaming gift for women", "cozy gaming gift set women", "gaming headset gift women",
               "Nintendo Switch gift accessories", "board game gift couples"],
    "gardening": ["gardening gift for women", "herb garden kit indoor gift", "garden tool set women gift",
                  "succulent kit gift women", "garden apron gift women"],
    "movies": ["movie lover gift for women", "home theater gift set", "film photography gift women",
               "movie night gift basket", "streaming subscription gift card"],
    "pets": ["pet lover gift for women", "cat lover gift set women", "dog lover gift set women",
             "pet photo gift personalized", "animal lover candle gift"],
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
    Scrapes Amazon Movers & Shakers — publicly available, no auth needed.
    Best-seller momentum = strong gift potential signal.
    """

    MOVERS_URLS = [
        ("https://www.amazon.com/gp/movers-and-shakers/beauty", "beauty"),
        ("https://www.amazon.com/gp/movers-and-shakers/home-garden", "home"),
        ("https://www.amazon.com/gp/movers-and-shakers/fashion", "fashion"),
        ("https://www.amazon.com/gp/movers-and-shakers/sports", "fitness"),
        ("https://www.amazon.com/gp/movers-and-shakers/kitchen", "kitchen"),
        ("https://www.amazon.com/gp/movers-and-shakers/handmade", "hobby"),
    ]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def fetch_signals(self, top_n: int = 15) -> list[TrendSignal]:
        """
        Scrape top N movers per category.
        Rank 1 gets highest score, rank N gets lowest (linear decay).
        """
        signals: list[TrendSignal] = []

        for url, category in self.MOVERS_URLS:
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                # Amazon Movers & Shakers product names sit in zg-bdg-img-nn or similar
                # Multiple selector attempts for resilience against layout changes
                items = (
                        soup.select(".zg-item-immersion")
                        or soup.select('[data-p13n-asin-metadata]')
                        or soup.select(".a-link-normal.a-text-normal")
                )

                found = 0
                for rank, item in enumerate(items[:top_n], start=1):
                    name_el = (
                            item.select_one(".p13n-sc-truncate")
                            or item.select_one(".zg-item a span")
                            or item.select_one("span.a-text-normal")
                            or item.select_one("div._cDEzb_p13n-sc-css-line-clamp-1_1Fn1y")
                    )
                    if not name_el:
                        continue

                    name = name_el.get_text(strip=True)
                    if len(name) < 5:
                        continue

                    # Score inversely proportional to rank (rank 1 = top_n pts)
                    rank_score = float(top_n - rank + 1)

                    signals.append(TrendSignal(
                        term=name,
                        source="amazon_movers",
                        score=rank_score * 10,  # scale up vs reddit scores
                        raw_context=f"Amazon Movers & Shakers #{rank} in {category}",
                        amazon_category=category,
                    ))
                    found += 1

                logger.info(f"Amazon Movers ({category}): found {found} products")
                time.sleep(random.uniform(2.0, 3.5))  # polite rate limit

            except Exception as e:
                logger.warning(f"Amazon Movers scrape failed for {category}: {e}")

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


def search_amazon_scraping(query: str) -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    search_url = f"https://www.amazon.com/s?k={requests.utils.quote(query)}&rh=p_36%3A1500-30000"

    try:
        resp = requests.get(search_url, headers=headers, timeout=15)
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
            name_el = item.select_one("h2 a span")
            name = name_el.get_text(strip=True) if name_el else ""
            if not name:
                continue
            price_whole = item.select_one(".a-price-whole")
            price_frac = item.select_one(".a-price-fraction")
            if not price_whole:
                continue
            try:
                price = float(price_whole.get_text(strip=True).replace(",", "").replace(".", ""))
                if price_frac:
                    price += float(price_frac.get_text(strip=True)) / 100
            except ValueError:
                continue
            if not (PRICE_MIN <= price <= PRICE_MAX):
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
    time.sleep(random.uniform(2.0, 4.0))
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

Classify into:
  interests (1-4): coffee, cooking, baking, wine, cocktails, fitness, running, cycling, yoga, reading, music, gaming, photography, art, travel, hiking, camping, gardening, movies, fashion, skincare, makeup, wellness, home_decor, pets
  gift_type (1-3): tech, home, outdoors, fitness, hobby, beauty, kitchen, book, fashion
  vibe (1-3): cozy, romantic, sentimental, luxe, fun, thoughtful, pampering
  occasions (2-5): birthday, valentines, anniversary, christmas, mothers_day, just_because, apology
  gender_skew: "female" | "male" | "unisex"
  is_gift_appropriate: true | false  (false = consumable that ships poorly, strictly utilitarian, outside $15-$300)
  description_for_embedding: 2-3 sentences. What it IS + the experience it creates + who it's for. Warm editorial tone. No invented specs.

JSON shape:
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

    # 6. Build row and insert
    gift_row = {
        "name": name,
        "display_name": name,
        "description": classification.get("description_for_embedding", name),
        "price": price,
        "currency": "USD",
        "link": product.get("link", ""),
        "image_url": product.get("image_url", ""),
        "brand": product.get("brand"),
        "interests": classification.get("interests", []),
        "gift_type": classification.get("gift_type", []),
        "vibe": classification.get("vibe", []),
        "occasions": classification.get("occasions", []),
        "gender_skew": classification.get("gender_skew", "unisex"),
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