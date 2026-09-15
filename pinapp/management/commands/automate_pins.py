import random
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from google import genai
from google.genai import types

from .create_pin import Command as CreatePinCommand


# ---------------------------------------------------------------------------
# Seasonal / evergreen fallback niches (used when trend fetching fails)
# ---------------------------------------------------------------------------
SEASONAL_NICHES = {
    1: ["home organization ideas", "new year fitness gadgets", "winter skincare essentials"],
    2: ["valentines day gifts", "cozy home decor", "self care products"],
    3: ["spring cleaning gadgets", "garden tools", "minimalist home decor"],
    4: ["outdoor entertaining", "Easter decor ideas", "spring fashion accessories"],
    5: ["summer essentials", "travel accessories", "home workout equipment"],
    6: ["beach essentials", "outdoor gadgets", "aesthetic water bottles"],
    7: ["back to school supplies", "dorm room decor", "portable tech gadgets"],
    8: ["back to school organization", "fall fashion accessories", "desk setup ideas"],
    9: ["fall home decor", "cozy blankets and throws", "aesthetic desk accessories"],
    10: ["halloween decor", "autumn kitchen gadgets", "cozy reading nook ideas"],
    11: ["christmas gift ideas", "holiday home decor", "black friday deals gadgets"],
    12: ["christmas gifts for her", "holiday kitchen essentials", "winter home must haves"],
}

EVERGREEN_NICHES = [
    "aesthetic room decor",
    "kitchen gadgets must have",
    "home office setup",
    "bathroom organization ideas",
    "minimalist lifestyle products",
    "self care gift set",
    "smart home devices",
    "portable travel essentials",
    "desk accessories aesthetic",
    "closet organization ideas",
]

# ---------------------------------------------------------------------------
# User-Agent rotation pool
# ---------------------------------------------------------------------------
USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) "
        "Gecko/20100101 Firefox/132.0"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
]

# Amazon domains per region
AMAZON_DOMAINS = {
    "US": "www.amazon.com",
    "IN": "www.amazon.in",
    "UK": "www.amazon.co.uk",
    "DE": "www.amazon.de",
    "CA": "www.amazon.ca",
}


class Command(BaseCommand):
    help = "Discover trending topics, find Amazon products, and create Pinterest pins."

    # Terms to exclude (non-physical / media products)
    MEDIA_TERMS = {
        "audiobook", "blu-ray", "book", "cd", "dvd", "ebook",
        "kindle", "mp3", "music", "paperback", "soundtrack", "vinyl",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--region",
            default=None,
            help="Amazon region: US, IN, UK, DE, CA (default: from .env AMAZON_REGION or US).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Number of products to process (default: 1, max: 10).",
        )
        parser.add_argument(
            "--topic",
            help="Use this topic directly instead of fetching trends.",
        )
        parser.add_argument(
            "--amazon-url",
            help="Use a specific Amazon search or product page URL directly.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print extracted product data without calling Gemini or Telegram.",
        )

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["limit"] > 10:
            raise CommandError("--limit must be between 1 and 10.")

        region = (options["region"] or getattr(settings, "AMAZON_REGION", "US")).upper()
        if region not in AMAZON_DOMAINS:
            raise CommandError(f"Unknown region '{region}'. Use one of: {', '.join(AMAZON_DOMAINS)}.")

        domain = AMAZON_DOMAINS[region]

        # --- Determine topic(s) ---
        if options["topic"]:
            topics = [options["topic"]]
        else:
            topics = self.get_trending_topics()

        # --- Find products ---
        products = []
        topic = ""

        if options["amazon_url"]:
            # Direct Amazon URL mode
            self.stdout.write(f"Using direct Amazon URL: {options['amazon_url']}")
            try:
                products = self.scrape_amazon_page(options["amazon_url"], options["limit"], domain)
                topic = options.get("topic", "Direct URL")
            except CommandError as exc:
                raise CommandError(f"Failed to scrape the provided Amazon URL: {exc}") from exc
        else:
            for candidate in topics:
                self.stdout.write(f"Trying topic: {candidate}")
                try:
                    products = self.search_amazon(candidate, options["limit"], domain)
                except CommandError as exc:
                    self.stdout.write(self.style.WARNING(f"  Skipping: {exc}"))
                    continue
                topic = candidate
                break

        if not products:
            raise CommandError(
                "No topics produced Amazon products. Try --topic with a specific query, "
                "or --amazon-url with a direct Amazon link."
            )

        self.stdout.write(self.style.SUCCESS(f"\nFound {len(products)} product(s) for '{topic}'.\n"))

        if options["dry_run"]:
            for index, product in enumerate(products, start=1):
                self._safe_write(f"\n--- Product {index} ---")
                for key, val in product.items():
                    self._safe_write(f"  {key}: {val}")
            return

        # --- Process through Gemini + Telegram ---
        pin_command = CreatePinCommand()
        for index, product in enumerate(products, start=1):
            self._safe_write(f"\nProcessing product {index}/{len(products)}: {product['title']}")
            copy = pin_command.generate_copy(product)
            pin_command.send_to_telegram(product, copy)
            self.stdout.write(self.style.SUCCESS("  Sent to Telegram!"))

        self.stdout.write(self.style.SUCCESS(f"\nDone! Created and sent {len(products)} pin(s) for '{topic}'."))

    # ------------------------------------------------------------------
    # Trend discovery: Google Trends RSS → Gemini filter → seasonal fallback
    # ------------------------------------------------------------------
    def get_trending_topics(self):
        """Multi-fallback strategy for discovering Pinterest-worthy topics."""

        # Strategy 1: Google Trends RSS
        self.stdout.write("Fetching trending topics from Google Trends...")
        google_topics = self._fetch_google_trends()
        if google_topics:
            self.stdout.write(f"  Found {len(google_topics)} Google Trends topics.")
            pinterest_topics = self._filter_topics_with_gemini(google_topics)
            if pinterest_topics:
                self.stdout.write(f"  Gemini selected {len(pinterest_topics)} Pinterest-worthy topics.")
                return pinterest_topics
            # If Gemini filtering fails, still try Google topics directly
            self.stdout.write("  Gemini filtering unavailable, using raw Google topics.")
            return google_topics

        # Strategy 2: Seasonal + evergreen fallback
        self.stdout.write(self.style.WARNING("Google Trends unavailable. Using seasonal fallback."))
        month = datetime.now(timezone.utc).month
        seasonal = SEASONAL_NICHES.get(month, [])
        combined = seasonal + random.sample(EVERGREEN_NICHES, min(3, len(EVERGREEN_NICHES)))
        random.shuffle(combined)
        return combined

    @staticmethod
    def _fetch_google_trends():
        """Fetch currently trending topics from Google Trends RSS feed."""
        rss_url = "https://trends.google.com/trending/rss?geo=US"
        try:
            response = requests.get(
                rss_url,
                headers={"User-Agent": random.choice(USER_AGENTS)},
                timeout=15,
            )
            response.raise_for_status()
            root = ET.fromstring(response.text)

            topics = []
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    topic = title_el.text.strip()
                    if topic and topic not in topics:
                        topics.append(topic)
            return topics[:20]  # Cap at 20

        except (requests.RequestException, ET.ParseError):
            return []

    def _filter_topics_with_gemini(self, topics):
        """Use Gemini to pick the most Pinterest-friendly, product-oriented topics."""
        api_key = getattr(settings, "GEMINI_API_KEY", "")
        if not api_key or api_key == "YOUR GEMINI API KEY":
            return []  # Skip Gemini filtering silently

        topic_list = "\n".join(f"- {t}" for t in topics)
        prompt = (
            "From the following trending topics, select up to 5 that would work best "
            "for Pinterest product affiliate pins. Pick topics where people would "
            "actually search for and buy physical products on Amazon.\n\n"
            f"Topics:\n{topic_list}\n\n"
            "Return ONLY a JSON array of strings with the selected topics, "
            "rephrased as Amazon product search queries. "
            "Example: [\"aesthetic desk organizer\", \"cozy throw blanket\"]\n"
            "If none are suitable, return an empty array: []"
        )

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True,
                    ),
                ),
            )
            text = (response.text or "").strip()
            # Clean markdown fences if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
            result = __import__("json").loads(text)
            if isinstance(result, list):
                return [str(t) for t in result if isinstance(t, str) and t.strip()]
        except Exception as exc:
            self.stdout.write(f"  Gemini topic filtering failed: {exc}")

        return []

    # ------------------------------------------------------------------
    # Amazon scraping with robustness improvements
    # ------------------------------------------------------------------
    @classmethod
    def _build_session(cls):
        """Create a requests.Session with realistic browser headers."""
        session = requests.Session()
        ua = random.choice(USER_AGENTS)
        session.headers.update({
            "User-Agent": ua,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
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
        })
        return session

    @staticmethod
    def _is_captcha_page(html_text):
        """Detect if Amazon returned a CAPTCHA page instead of results."""
        captcha_indicators = [
            "api-services-support@amazon.com",
            "Type the characters you see in this image",
            "Sorry, we just need to make sure you're not a robot",
            "captcha",
            "validateCaptcha",
        ]
        lower_text = html_text.lower()
        return any(indicator.lower() in lower_text for indicator in captcha_indicators)

    def search_amazon(self, topic, limit, domain="www.amazon.com"):
        """Search Amazon for products matching a topic, with retry on CAPTCHA."""
        search_url = f"https://{domain}/s?k={quote_plus(f'{topic} products')}"
        return self._fetch_and_parse_amazon(search_url, topic, limit, domain)

    def scrape_amazon_page(self, url, limit, domain="www.amazon.com"):
        """Scrape products from a specific Amazon URL."""
        return self._fetch_and_parse_amazon(url, "Direct URL", limit, domain)

    def _fetch_and_parse_amazon(self, url, topic, limit, domain):
        """Core Amazon fetch + parse logic with CAPTCHA retry."""
        max_attempts = 3
        for attempt in range(max_attempts):
            session = self._build_session()
            try:
                # First visit the homepage to get cookies
                try:
                    session.get(f"https://{domain}/", timeout=15)
                except requests.RequestException:
                    pass  # Non-critical; proceed without homepage cookies

                response = session.get(url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as exc:
                if attempt < max_attempts - 1:
                    self.stdout.write(f"  Retry {attempt + 1}: Request failed ({exc})")
                    continue
                raise CommandError(f"Could not fetch Amazon: {exc}") from exc

            if self._is_captcha_page(response.text):
                if attempt < max_attempts - 1:
                    self.stdout.write(
                        f"  Retry {attempt + 1}: Amazon returned CAPTCHA, rotating User-Agent..."
                    )
                    continue
                raise CommandError(
                    "Amazon is showing CAPTCHA. Try again later, use a different network, "
                    "or provide a direct Amazon product URL with --amazon-url."
                )

            # Parse the page
            products = self._extract_products(response.text, topic, limit, domain)
            if products:
                return products

            if attempt < max_attempts - 1:
                self.stdout.write(f"  Retry {attempt + 1}: No products found, retrying...")
                continue

        raise CommandError(
            "Amazon returned no parseable products. Amazon may have blocked the request. "
            "Try --topic with another query or provide a direct --amazon-url."
        )

    def _extract_products(self, html, topic, limit, domain):
        """Extract product data from Amazon search results HTML."""
        soup = BeautifulSoup(html, "html.parser")
        products = []

        for result in soup.select('div[data-component-type="s-search-result"]'):
            title_node = result.select_one("h2 span")
            link_node = result.select_one("h2 a") or result.select_one("a.a-link-normal")
            image_node = result.select_one("img.s-image")
            if not title_node or not link_node or not image_node:
                continue

            title = title_node.get_text(" ", strip=True)
            raw_href = link_node.get("href", "")
            product_url = urljoin(f"https://{domain}", raw_href)
            image_url = image_node.get("src") or image_node.get("data-src")

            # Upgrade thumbnail to high-res (320px -> 1500px)
            if image_url:
                image_url = re.sub(
                    r"\._[A-Z]{2}_[A-Z]{2}\d+_\.",  # e.g. ._AC_UL320_.
                    "._AC_SL1500_.",
                    image_url,
                )

            # Skip sponsored / ad redirect links (sspa/click)
            if "/sspa/click" in raw_href or "/gp/slredirect" in raw_href:
                continue

            # --- Extract price ---
            price = ""
            price_whole = result.select_one("span.a-price-whole")
            price_fraction = result.select_one("span.a-price-fraction")
            price_symbol = result.select_one("span.a-price-symbol")
            if price_whole:
                symbol = price_symbol.get_text(strip=True) if price_symbol else "$"
                whole = price_whole.get_text(strip=True).rstrip(".")
                fraction = price_fraction.get_text(strip=True) if price_fraction else "00"
                price = f"{symbol}{whole}.{fraction}"

            # --- Extract rating ---
            rating = ""
            rating_node = result.select_one("span.a-icon-alt")
            if rating_node:
                rating_text = rating_node.get_text(strip=True)
                rating_match = re.search(r"([\d.]+)\s*out\s*of\s*5", rating_text)
                if rating_match:
                    rating = f"{rating_match.group(1)}/5"

            # --- Extract review count ---
            review_count = ""
            review_node = result.select_one('span[data-component-type="s-client-side-analytics"] span.a-size-base')
            if not review_node:
                # Fallback: look for the review count link
                review_link = result.select_one("a[href*='customerReviews'] span")
                if review_link:
                    review_node = review_link
            if review_node:
                count_text = review_node.get_text(strip=True).replace(",", "")
                if count_text.isdigit():
                    review_count = count_text

            # --- Extract features ---
            feature_nodes = result.select(".a-row.a-size-base.a-color-secondary")
            features = " ".join(node.get_text(" ", strip=True) for node in feature_nodes)
            if not features:
                features = result.get_text(" ", strip=True)
            features = re.sub(r"\s+", " ", features).strip()

            # Skip media products
            searchable_text = f"{title} {features}".lower()
            if any(re.search(rf"\b{re.escape(term)}\b", searchable_text) for term in self.MEDIA_TERMS):
                continue

            # Build enriched features string
            enriched_features = f"Trend topic: {topic}."
            if price:
                enriched_features += f" Price: {price}."
            if rating:
                enriched_features += f" Rating: {rating}."
            if review_count:
                enriched_features += f" Reviews: {review_count}."
            enriched_features += f" {features}"

            products.append({
                "url": CreatePinCommand.clean_amazon_url(product_url),
                "title": title,
                "features": enriched_features.strip(),
                "image_url": image_url,
            })
            if len(products) >= limit:
                break

        return products

    def _safe_write(self, msg):
        """Write to stdout handling encoding errors on Windows."""
        try:
            self.stdout.write(msg)
        except UnicodeEncodeError:
            self.stdout.write(msg.encode("ascii", errors="replace").decode("ascii"))
