import json
import re
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic schema – guarantees Gemini returns exactly this JSON shape
# ---------------------------------------------------------------------------
class PinCopy(BaseModel):
    """Schema for the Pinterest pin copy returned by Gemini."""

    title: str = Field(
        ...,
        description="SEO-rich pin title, under 100 characters. Use power words and front-load keywords.",
    )
    description: str = Field(
        ...,
        description=(
            "Engaging pin description + hashtags, TOTAL under 800 characters. "
            "Write the description text first, then end with a line of "
            "high-traffic hashtags (5 relevant + #ad). Everything combined must be under 800 chars."
        ),
    )
    alt_text: str = Field(
        ...,
        description=(
            "Visual description of the product image for screen readers and Pinterest visual search, "
            "under 500 characters. Describe colors, shapes, materials, setting. No promotional language."
        ),
    )
    board_name: str = Field(
        ...,
        description="One highly searchable, niche-specific Pinterest board name that matches high-volume search terms.",
    )


# ---------------------------------------------------------------------------
# Gemini system prompt – heavy Pinterest SEO guidance
# ---------------------------------------------------------------------------
GEMINI_SYSTEM_PROMPT = """
You are an elite Pinterest SEO copywriter specialising in Amazon affiliate products.
Your single goal: maximise impressions, saves, and click-throughs on Pinterest.

Return ONLY a valid JSON object matching the provided schema. Follow every rule:

### TITLE (under 100 characters)
- Front-load the most-searched keyword.
- Use 1-2 power/emotional words (e.g. "Must-Have", "Stunning", "Game-Changer").
- NO clickbait, ALL CAPS, or excessive punctuation.
- Include the product type so Pinterest categorises correctly.

### DESCRIPTION (AIM FOR 750-800 characters TOTAL, including hashtags)
The description field contains BOTH the copy text AND the hashtags.
Structure it exactly like this:

<copy text>

<hashtags>

Rules for the copy text part (about 300-400 characters):
- Open with the primary keyword phrase naturally.
- Weave in 3-4 secondary long-tail keywords that people search on Pinterest.
- Write in a conversational, inspiring tone — imagine recommending it to a friend.
- Include a clear call-to-action ("Tap the link to grab yours!", "Shop now via the link!").

Rules for the hashtags part (placed at the very end after a blank line):
- Add 15 to 20 HIGH-TRAFFIC hashtags + #ad as the last one, space-separated.
- USE AS MANY HASHTAGS AS NEEDED to bring the total description close to 800 characters.
- Pick hashtags that get the MOST searches and impressions on Pinterest.
- Mix: 5 broad/high-volume + 5 mid-volume niche + 5-10 specific long-tail + #ad.
- Use popular Pinterest hashtags like: #AmazonFinds #TechGadgets #HomeDecor #GadgetLovers #Trending #OnlineShopping #BestDeals #MustHave #ProductReview #SmartHome etc.
- Example hashtags block: #TechGadgets #SmartphoneAccessories #GamingSetup #LaptopDeals #AmazonFinds #OnlineShopping #BestDeals #GadgetLovers #TrendingNow #MustHaveGadgets #PhoneAccessories #TechLovers #HomeOffice #ProductReview #DailyFinds #ad
- IMPORTANT: The TOTAL (copy + hashtags) MUST be between 750 and 800 characters. If under 750, add more hashtags.

### ALT TEXT (under 500 characters)
- Describe ONLY what is visually in the product image.
- Mention colors, materials, shapes, background/setting.
- Zero promotional language — this is for accessibility and visual search.

### BOARD NAME
- Suggest one board name that matches a high-volume Pinterest search query.
- Keep it specific enough to be a niche board, broad enough to hold 50+ pins.
- Example: "Aesthetic Desk Setup Ideas" not "Stuff I Like".

CRITICAL RULES:
- Do NOT invent prices, discounts, reviews, ratings, or availability.
- Use ONLY the supplied product data as your source of truth.
- Ensure every field respects its character limit.
- The description field MUST end with hashtags, and the last hashtag MUST be #ad.
- The description MUST be between 750 and 800 characters. Pack in more hashtags if under 750.
""".strip()


# ---------------------------------------------------------------------------
# Django management command
# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = "Generate Pinterest affiliate copy with Gemini and send it to Telegram."

    def add_arguments(self, parser):
        parser.add_argument("--url", required=True, help="Raw Amazon product URL.")
        parser.add_argument("--title", required=True, help="Raw Amazon product title.")
        parser.add_argument(
            "--features",
            required=True,
            help="Raw product features, separated by semicolons or new lines.",
        )
        parser.add_argument(
            "--image-url",
            required=True,
            help="Public product image URL that Telegram can fetch.",
        )

    def handle(self, *args, **options):
        canonical_url = self.clean_amazon_url(options["url"])
        product = {
            "url": canonical_url,
            "title": options["title"].strip(),
            "features": options["features"].strip(),
            "image_url": options["image_url"].strip(),
        }

        self.stdout.write(f"Canonical Amazon URL: {canonical_url}")
        copy = self.generate_copy(product)
        self.send_to_telegram(product, copy)
        self.stdout.write(self.style.SUCCESS("Pinterest copy and product image sent to Telegram."))

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------
    @staticmethod
    def clean_amazon_url(raw_url):
        parts = urlsplit(raw_url.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise CommandError("--url must be a complete http(s) Amazon product URL.")

        hostname = parts.hostname or ""
        if not re.fullmatch(r"(?:www\.)?amazon\.[a-z.]+", hostname.lower()):
            raise CommandError("--url must point to an Amazon domain.")

        netloc = hostname.lower()
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        product_match = re.search(r"/dp/([A-Za-z0-9]{10})(?:/|$)", parts.path)
        if product_match:
            return urlunsplit(("https", netloc, f"/dp/{product_match.group(1)}", "", ""))
        path = parts.path.rstrip("/") or "/"
        return urlunsplit(("https", netloc, path, "", ""))

    @staticmethod
    def extract_asin(url):
        """Extract the 10-character ASIN from an Amazon product URL, or None."""
        match = re.search(r"/dp/([A-Za-z0-9]{10})(?:/|$)", url)
        return match.group(1) if match else None

    # ------------------------------------------------------------------
    # Gemini copy generation
    # ------------------------------------------------------------------
    def generate_copy(self, product):
        api_key = getattr(settings, "GEMINI_API_KEY", "")
        if not api_key or api_key == "YOUR GEMINI API KEY":
            raise CommandError("Set GEMINI_API_KEY in .env before running the command.")

        user_prompt = (
            "Create Pinterest copy from this raw Amazon product data.\n"
            f"URL: {product['url']}\n"
            f"Title: {product['title']}\n"
            f"Features: {product['features']}\n"
            f"Image URL: {product['image_url']}"
        )

        client = genai.Client(api_key=api_key)
        retries = max(1, getattr(settings, "GEMINI_RETRIES", 5))
        copy = None
        for attempt in range(retries):
            try:
                response = client.models.generate_content(
                    model=getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash"),
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=GEMINI_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=PinCopy,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True,
                        ),
                    ),
                )
                copy = json.loads(self._response_text(response))
                break
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise CommandError(f"Gemini returned invalid JSON: {exc}") from exc
            except Exception as exc:
                error_text = str(exc).lower()
                transient = any(
                    marker in error_text
                    for marker in ("503", "429", "unavailable", "resource_exhausted", "temporarily")
                )
                if not transient or attempt == retries - 1:
                    raise CommandError(f"Gemini request failed: {exc}") from exc
                delay = 5 * (2 ** attempt)  # 5s, 10s, 20s, 40s ...
                self.stdout.write(f"Gemini is temporarily busy; retrying in {delay}s (attempt {attempt + 1}/{retries})...")
                time.sleep(delay)

        if copy is None:
            raise CommandError("Gemini did not return a valid response after all retries.")

        self.validate_copy(copy)
        return copy

    @staticmethod
    def _response_text(response):
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        return text

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def validate_copy(copy):
        required_keys = {"title", "description", "alt_text", "board_name"}
        missing = required_keys - set(copy)
        if missing:
            raise CommandError(f"Gemini response is missing keys: {missing}")

        limits = {"title": 100, "description": 800, "alt_text": 500}
        for field, limit in limits.items():
            if not isinstance(copy[field], str) or not copy[field].strip():
                raise CommandError(f"Gemini returned an empty {field}.")
            if len(copy[field]) > limit:
                raise CommandError(f"Gemini {field} must be under {limit} characters (got {len(copy[field])}).")

        # Validate hashtags exist inside description
        hashtag_list = re.findall(r"(?<!\w)#([A-Za-z0-9_]+)", copy["description"])
        if len(hashtag_list) < 5:
            raise CommandError(f"Description must contain at least 5 hashtags + #ad (got {len(hashtag_list)}).")

        # Board name must not be empty
        if not isinstance(copy.get("board_name"), str) or not copy["board_name"].strip():
            raise CommandError("Gemini returned an empty board_name.")

    # ------------------------------------------------------------------
    # Telegram delivery
    # ------------------------------------------------------------------
    def send_to_telegram(self, product, copy):
        bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
        if not bot_token or bot_token == "YOUR BOT TOKEN" or not chat_id or chat_id == "YOUR CHAT ID":
            raise CommandError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env before running the command.")

        api_url = f"https://api.telegram.org/bot{bot_token}"

        # --- Message 1: Product image with short caption ---
        photo_caption = f"📌 {copy['title']}\n\n📋 Board: {copy['board_name']}"
        try:
            photo_response = requests.post(
                f"{api_url}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "photo": product["image_url"],
                    "caption": photo_caption,
                    "parse_mode": "HTML",
                },
                timeout=30,
            )
            photo_response.raise_for_status()
            self._check_telegram_response(photo_response)
        except requests.RequestException as exc:
            raise CommandError(f"Telegram sendPhoto failed: {exc}") from exc

        # --- Message 2: Full structured copy (HTML formatted) ---
        copy_message = (
            f"📌 <b>TITLE</b>\n"
            f"<code>{self._escape_html(copy['title'])}</code>\n\n"
            f"📝 <b>DESCRIPTION</b>\n"
            f"<code>{self._escape_html(copy['description'])}</code>\n\n"
            f"🖼️ <b>ALT TEXT</b>\n"
            f"<code>{self._escape_html(copy['alt_text'])}</code>\n\n"
            f"📋 <b>BOARD NAME</b>\n"
            f"<code>{self._escape_html(copy['board_name'])}</code>\n\n"
            f"🔗 <b>PRODUCT LINK</b>\n"
            f"{self._escape_html(product['url'])}"
        )

        try:
            message_response = requests.post(
                f"{api_url}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": copy_message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
                timeout=30,
            )
            message_response.raise_for_status()
            self._check_telegram_response(message_response)
        except requests.RequestException as exc:
            raise CommandError(f"Telegram sendMessage failed: {exc}") from exc

    @staticmethod
    def _escape_html(text):
        """Escape special HTML characters for Telegram HTML parse mode."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @staticmethod
    def _check_telegram_response(response):
        payload = response.json()
        if not payload.get("ok"):
            raise CommandError(f"Telegram API error: {payload.get('description', 'Unknown error')}")
