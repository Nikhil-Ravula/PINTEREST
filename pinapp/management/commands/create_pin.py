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
import logging

logger = logging.getLogger(__name__)


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
- STRICTLY FORBIDDEN: Do NOT include prices (e.g. ₹, $, Rs), discounts, review ratings (e.g. 4.5/5), review counts, delivery dates, or bank/cashback card offers (e.g. ICICI, Amazon Pay) in ANY field.
- STRICTLY FORBIDDEN: Do NOT use ellipses ('...', '..', '…') or cut off sentences with dots in any field.
- Ensure every field respects its character limit and all sentences are complete and natural.
- The description field MUST end with hashtags, and the last hashtag MUST be #ad.
- The description MUST be between 700 and 800 characters. Pack in more hashtags if under 700.
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

    @staticmethod
    def clean_title(raw_title: str, max_chars: int = 60) -> str:
        """
        Produce a clean, human-readable product name without trailing dots,
        seller keyword spam, duplicate punctuation, or awkward ellipses.
        """
        if not raw_title:
            return "Trending Amazon Find"

        # Remove unicode ellipses, consecutive periods, or existing dots
        t = re.sub(r"[…]+", " ", str(raw_title))
        t = re.sub(r"\.{2,}", " ", t)

        # Normalize whitespace
        t = re.sub(r"\s+", " ", t).strip()

        # If title has multiple parts separated by | or - or – or :, take the most descriptive primary part
        major_parts = re.split(r"\s+[|–—]\s+", t)
        if major_parts and 20 <= len(major_parts[0].strip()) <= max_chars:
            t = major_parts[0].strip()
        else:
            comma_parts = re.split(r",\s*", t)
            if comma_parts and 20 <= len(comma_parts[0].strip()) <= max_chars:
                t = comma_parts[0].strip()

        t = t.rstrip(" ,-–—|:;.")
        if len(t) > max_chars:
            t = t[:max_chars].rsplit(" ", 1)[0].rstrip(" ,-–—|:;.")

        # Strip dangling prepositions or conjunctions at end
        t = re.sub(r"\b(for|with|and|or|in|on|at|to|a|an|the|of|by|from)\s*$", "", t, flags=re.IGNORECASE).rstrip(" ,-–—|:;.")
        return t

    @classmethod
    def generate_fallback_copy(cls, product):
        """
        Generate high-quality Pinterest SEO copy directly from product data
        if Gemini API is experiencing 503 high demand or temporary downtime.
        Guarantees clean, aesthetic copy with zero prices, ratings, delivery dates,
        cashback offers, or ellipses (...).
        """
        raw_title = product.get("title", "Trending Amazon Find").strip()
        clean_name = cls.clean_title(raw_title, max_chars=60)

        # Categorize by niche
        topic_str = f"{product.get('topic', '')} {clean_name} {raw_title}".lower()

        if any(w in topic_str for w in ["decor", "home", "living", "pillow", "cushion", "lamp", "curtain", "rug", "candle", "vase", "poster", "rack", "shelf"]):
            board_name = "Modern Home Decor"
            title_hook = "Aesthetic Modern Home Decor Idea"
            intro = (
                f"Elevate your living space with this gorgeous {clean_name}! "
                f"Featuring a sleek modern aesthetic, it effortlessly brings cozy vibes, stylish charm, "
                f"and functional elegance to any bedroom, living room, or apartment setup. "
                f"Whether you are planning a room makeover or looking for a thoughtful gift, "
                f"this piece adds the perfect aesthetic touch. "
                f"Tap the link to explore more styling inspiration and get yours today!"
            )
            hashtags = (
                "#HomeDecor #ModernHomeDecor #AestheticHome #LivingRoomDecor #InteriorStyling "
                "#AmazonHome #RoomMakeover #CozyHomeVibes #HomeFinds #ApartmentTherapy "
                "#HomeInspiration #DecorIdeas #TrendingHome #MustHaveDecor #AmazonFinds #ad"
            )
        elif any(w in topic_str for w in ["laptop", "macbook", "computer", "pc", "monitor", "keyboard", "mouse", "desk", "stand"]):
            board_name = "Laptop Accessories & Setup" if any(w in topic_str for w in ["setup", "accessory", "stand", "mouse", "keyboard", "pad"]) else "Best Laptops & Reviews"
            title_hook = "Must-Have Desk Setup & Tech Essential"
            intro = (
                f"Level up your workspace with this top-rated {clean_name}! "
                f"Engineered for high performance, sleek comfort, and everyday productivity, "
                f"it keeps your desk clutter-free and your workflow seamless. "
                f"The ultimate essential for work-from-home pros, gamers, and students alike. "
                f"Tap the link to check all the details and upgrade your desk setup today!"
            )
            hashtags = (
                "#DeskSetup #WorkFromHome #ProductivitySetup #TechGadgets #LaptopAccessories "
                "#DeskInspiration #MinimalistSetup #AmazonFinds #TechReview #WorkspaceGoals "
                "#AmazonTech #OfficeDecor #SmartGadgets #DailyFinds #BestDeals #ad"
            )
        elif any(w in topic_str for w in ["phone", "mobile", "charger", "magsafe", "earbuds", "audio", "case", "cable", "headphone"]):
            board_name = "Mobile Accessories & Gadgets"
            title_hook = "Must-Have Smart Gadget & Mobile Tech"
            intro = (
                f"Never compromise on convenience with this innovative {clean_name}! "
                f"Sleek, durable, and designed for effortless everyday use, it delivers reliable performance "
                f"wherever you go. An essential upgrade for your mobile device that combines practicality with modern style. "
                f"Tap the link to discover full specs and shop yours today!"
            )
            hashtags = (
                "#MobileAccessories #TechGadgets #PhoneAccessories #SmartGadgets #AmazonFinds "
                "#MustHaveTech #EverydayCarry #GadgetLovers #TechTrends #TrendingNow "
                "#DailyTech #OnlineShopping #BestDeals #CoolGadgets #TechAddict #ad"
            )
        elif any(w in topic_str for w in ["watch", "smartwatch", "fitness", "band", "tracker"]):
            board_name = "Best Watches & Smartwatches"
            title_hook = "Chic Smartwatch & Timepiece Essential"
            intro = (
                f"Track your lifestyle in style with this stunning {clean_name}! "
                f"Blending cutting-edge features with a premium aesthetic design, it is built to keep you connected, "
                f"active, and fashionable all day long. Perfect for daily fitness tracking or styling with any outfit. "
                f"Tap the link to view current availability and get yours now!"
            )
            hashtags = (
                "#Smartwatches #WatchLovers #FitnessTracker #TechStyle #WristGame "
                "#AmazonDeals #DailyStyle #SmartTech #FitnessGoals #ModernStyle "
                "#TrendingNow #MustHaveGadgets #AmazonFinds #ProductReview #ad"
            )
        elif any(w in topic_str for w in ["beauty", "skin", "makeup", "hair", "fragrance", "perfume", "serum"]):
            board_name = "Summer Beauty & Fashion"
            title_hook = "Glow-Up Beauty & Self-Care Essential"
            intro = (
                f"Pamper yourself with this viral beauty favorite: {clean_name}! "
                f"Formulated to give you that effortless radiant glow, this essential fits seamlessly into "
                f"your daily self-care and skincare regimen. Treat yourself to the pampering you deserve or gift it to someone special. "
                f"Tap the link to reveal all the details and shop yours on Amazon today!"
            )
            hashtags = (
                "#BeautyFinds #SkincareRoutine #SelfCareSunday #GlowUpTips #AmazonBeauty "
                "#BeautyMustHaves #SkincareLovers #AestheticVibes #CleanBeauty #SummerGlow "
                "#DailyRoutine #AmazonFinds #TrendingNow #BestDeals #ad"
            )
        elif any(w in topic_str for w in ["dress", "outfit", "wear", "shoes", "fashion", "bag", "jewelry"]):
            board_name = "Women Outfit Ideas"
            title_hook = "Chic Aesthetic Outfit Inspo"
            intro = (
                f"Step out in effortless style with this stunning {clean_name}! "
                f"Designed with comfortable silhouettes and chic modern details, this piece makes outfit styling simple "
                f"and versatile for everyday casual wear or special occasions. Elevate your wardrobe with this trending favorite. "
                f"Tap the link to explore more styling looks and grab yours today!"
            )
            hashtags = (
                "#OutfitInspo #FashionTrends #StyleInspo #AmazonFashion #WardrobeEssentials "
                "#LookOfTheDay #OOTD #AestheticFashion #EverydayStyle #ChicStyle "
                "#FashionAddict #TrendingNow #MustHaveFashion #DailyFinds #ad"
            )
        else:
            board_name = "Mobile Accessories & Gadgets"
            title_hook = "Trending Amazon Find & Must-Have Deal"
            intro = (
                f"Discover why everyone is talking about this trending {clean_name}! "
                f"A versatile and stylish pick crafted to bring ease, quality, and modern design to your daily routine. "
                f"Whether treating yourself or searching for the perfect gift, this popular find is an absolute winner. "
                f"Tap the link to check price and availability on Amazon today!"
            )
            hashtags = (
                "#AmazonFinds #TrendingDeals #MustHave #ViralProducts #DailyFinds "
                "#BestDeals #OnlineShopping #TrendingNow #SmartFinds #ShoppingHaul "
                "#ProductReview #DailyMustHaves #AmazonHome #TechGadgets #ad"
            )

        pin_title = f"{clean_name}: {title_hook}"
        if len(pin_title) > 95:
            pin_title = cls.clean_title(clean_name, max_chars=50) + f": {title_hook}"
        pin_title = pin_title[:100].rstrip(" ,-–—|:;.")

        description = f"{intro}\n\n{hashtags}"[:800]

        alt_text = (
            f"High-resolution product photo of {clean_name} showcasing clean modern aesthetic design, "
            f"premium finish, and elegant details against a clean background."
        )[:500].rstrip(" ,-–—|:;.") + "."

        return {
            "title": pin_title,
            "description": description,
            "alt_text": alt_text,
            "board_name": board_name,
        }

    # ------------------------------------------------------------------
    # Gemini copy generation with resilient fallback
    # ------------------------------------------------------------------
    def generate_copy(self, product):
        api_key = getattr(settings, "GEMINI_API_KEY", "")
        if not api_key or api_key == "YOUR GEMINI API KEY":
            copy = self.generate_fallback_copy(product)
            self.validate_copy(copy, product)
            return copy

        user_prompt = (
            "Create Pinterest copy from this raw Amazon product data.\n"
            f"URL: {product['url']}\n"
            f"Title: {product['title']}\n"
            f"Features: {product.get('features', '')}\n"
            f"Image URL: {product['image_url']}"
        )

        try:
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=25000),
            )
        except Exception as client_err:
            logger.warning(f"Failed to initialize Gemini client: {client_err}")
            client = None

        preferred_model = getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash")
        candidate_models = [preferred_model, "gemini-flash-latest"]
        models_to_try = list(dict.fromkeys(candidate_models))

        copy = None
        if client:
            for attempt, current_model in enumerate(models_to_try):
                try:
                    response = client.models.generate_content(
                        model=current_model,
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
                    text = self._response_text(response)
                    if text:
                        copy = json.loads(text)
                        break
                except Exception as exc:
                    logger.warning(f"Gemini model {current_model} failed (attempt {attempt+1}/{len(models_to_try)}): {exc}")
                    time.sleep(1)

        if copy is None:
            logger.info("All Gemini models busy (503/timeout). Using high-quality SEO fallback copy.")
            copy = self.generate_fallback_copy(product)

        self.validate_copy(copy, product)
        return copy

    @staticmethod
    def _response_text(response):
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        return text

    # ------------------------------------------------------------------
    # Validation (Auto-healing, sanitizes dots, prices, and overflows)
    # ------------------------------------------------------------------
    @staticmethod
    def validate_copy(copy, product=None):
        required_keys = {"title", "description", "alt_text", "board_name"}
        for k in required_keys:
            if k not in copy or not str(copy[k]).strip():
                if k == "title" and product:
                    copy["title"] = CreatePinCommand.clean_title(product.get("title", "Trending Product"), max_chars=60)
                elif k == "board_name":
                    copy["board_name"] = "Modern Home Decor"
                elif k == "alt_text":
                    copy["alt_text"] = "High-resolution product photo showcasing modern design and details against a clean background."
                elif k == "description":
                    copy["description"] = "Discover this stunning trending product on Amazon! Tap the link to check details and shop today. #AmazonFinds #Trending #HomeDecor #ad"

        # Sanitize all text fields from ellipses, repeated dots, and accidental scraper junk
        junk_patterns = [
            r"(?i)Price:\s*[₹$€£\d.,]+[^\.\n]*\.?",
            r"(?i)Rating:\s*[\d.]+/5[^\.\n]*\.?",
            r"(?i)FREE delivery[^\.\n]*\.?",
            r"(?i)Or fastest delivery[^\.\n]*\.?",
            r"(?i)Up to \d+% back[^\.\n]*\.?",
            r"(?i)Amazon Pay[^\.\n]*\.?",
            r"(?i)Save extra with Cashback[^\.\n]*\.?",
            r"(?i)Trend topic:\s*[^.]+\.?",
            r"(?i)Highlights:\s*",
        ]

        for field in ["title", "description", "alt_text"]:
            val = str(copy.get(field, "")).strip()
            # Remove unicode ellipses and consecutive dots
            val = re.sub(r"[…]+", " ", val)
            val = re.sub(r"\.{2,}", " ", val)
            # Remove scraper junk if present in description
            if field == "description":
                for pat in junk_patterns:
                    val = re.sub(pat, " ", val)
            # Normalize whitespace
            val = re.sub(r"\s+", " ", val).strip()
            # Fix dangling punctuation before colons or commas
            val = re.sub(r",\s*:", ":", val)
            val = re.sub(r"\s+:", ":", val)
            if field == "title":
                val = val.rstrip(" ,-–—|:;.")
            copy[field] = val

        limits = {"title": 100, "description": 800, "alt_text": 500}
        for field, limit in limits.items():
            val = str(copy.get(field, "")).strip()
            if len(val) > limit:
                copy[field] = val[:limit].rstrip(" ,-–—|:;.")

        # Ensure at least 3 hashtags and #ad
        desc = copy.get("description", "")
        hashtag_list = re.findall(r"(?<!\w)#([A-Za-z0-9_]+)", desc)
        if len(hashtag_list) < 3:
            desc = (desc[:720] + " #AmazonFinds #Trending #HomeDecor #ad")
        if "#ad" not in desc:
            desc = (desc[:790] + " #ad")
        copy["description"] = desc[:800]

    # ------------------------------------------------------------------
    # Telegram delivery
    # ------------------------------------------------------------------
    def send_to_telegram(self, product, copy):
        bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
        if not bot_token or bot_token == "YOUR BOT TOKEN" or not chat_id or chat_id == "YOUR CHAT ID":
            raise CommandError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env before running the command.")

        api_url = f"https://api.telegram.org/bot{bot_token}"

        def _post_with_retry(endpoint, data, max_attempts=3):
            for attempt in range(max_attempts):
                try:
                    resp = requests.post(f"{api_url}/{endpoint}", data=data, timeout=30)
                    resp.raise_for_status()
                    self._check_telegram_response(resp)
                    return resp
                except requests.RequestException as exc:
                    if attempt < max_attempts - 1:
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise CommandError(f"Telegram {endpoint} failed after {max_attempts} attempts: {exc}") from exc

        # --- Message 1: Product image with short caption ---
        photo_caption = f"📌 {copy['title']}\n\n📋 Board: {copy['board_name']}"
        _post_with_retry("sendPhoto", {
            "chat_id": chat_id,
            "photo": product["image_url"],
            "caption": photo_caption,
            "parse_mode": "HTML",
        })

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

        _post_with_retry("sendMessage", {
            "chat_id": chat_id,
            "text": copy_message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })

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
