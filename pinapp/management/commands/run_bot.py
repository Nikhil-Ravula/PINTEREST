"""
Telegram bot that listens for /new commands and sends fresh Pinterest product pins.

Usage:
    python manage.py run_bot

Bot commands (send these in Telegram):
    /start  - Show welcome message and available commands
    /new    - Get 1 new trending product pin
    /new 3  - Get 3 new product pins
    /stats  - Show how many products have been sent
    /reset  - Clear sent product history (allows re-sending)
"""

import asyncio
import io
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from pinapp.models import SentProduct
from .automate_pins import Command as AutomateCommand, AMAZON_DOMAINS
from .create_pin import Command as CreatePinCommand

logger = logging.getLogger(__name__)


# ======================================================================
# Custom search topics organized by category
# ======================================================================

CATEGORIES = {
    "phones": {
        "label": "Phones",
        "topics": [
            "best smartphones under 20000",
            "latest 5G smartphones",
            "best camera phone",
            "samsung galaxy phone",
            "oneplus latest phone",
            "redmi note latest",
            "realme narzo phone",
            "best gaming phone",
            "foldable smartphone",
            "phone with best battery life",
            "slim lightweight smartphone",
            "iphone latest model",
        ],
    },
    "laptops": {
        "label": "Laptops",
        "topics": [
            "best laptop under 50000",
            "gaming laptop",
            "ultrabook thin laptop",
            "macbook air laptop",
            "hp pavilion laptop",
            "lenovo ideapad laptop",
            "asus vivobook laptop",
            "2 in 1 convertible laptop",
            "best laptop for students",
            "laptop for video editing",
        ],
    },
    "phoneacc": {
        "label": "Phone Accessories",
        "topics": [
            "phone case aesthetic",
            "wireless earbuds bluetooth",
            "fast charging cable usb c",
            "phone holder car mount",
            "tempered glass screen protector",
            "portable power bank 20000mah",
            "phone ring grip holder",
            "wireless charging pad",
            "phone camera lens kit",
            "phone stand desk adjustable",
            "magsafe accessories",
            "airpods pro case cover",
        ],
    },
    "laptopacc": {
        "label": "Laptop Accessories",
        "topics": [
            "laptop stand adjustable",
            "laptop bag backpack",
            "wireless mouse ergonomic",
            "mechanical keyboard compact",
            "laptop cooling pad",
            "usb c hub multiport adapter",
            "monitor riser desk organizer",
            "laptop sleeve protective",
            "external hard drive portable",
            "webcam 1080p hd",
            "laptop desk for bed",
            "bluetooth keyboard and mouse combo",
        ],
    },
    "homedecor": {
        "label": "Home Decor",
        "topics": [
            "aesthetic room decor",
            "wall art canvas painting",
            "led strip lights room",
            "table lamp bedside modern",
            "photo frame wall collage",
            "indoor plants artificial",
            "wall mirror decorative",
            "throw pillow covers aesthetic",
            "fairy lights for room",
            "floating shelves wall mounted",
            "scented candle gift set",
            "desk organizer aesthetic",
            "wall clock modern design",
            "curtains for living room",
            "rug carpet living room",
            "vase flower decorative",
            "wall stickers for bedroom",
            "neon sign room decor",
            "bookshelf organizer modern",
            "cozy throw blanket",
        ],
    },
}

# Short aliases so users can type less
CATEGORY_ALIASES = {
    "phone": "phones",
    "laptop": "laptops",
    "phoneaccessories": "phoneacc",
    "phone accessories": "phoneacc",
    "phone acc": "phoneacc",
    "laptopaccessories": "laptopacc",
    "laptop accessories": "laptopacc",
    "laptop acc": "laptopacc",
    "home decor": "homedecor",
    "home": "homedecor",
    "decor": "homedecor",
    "electronics": "phones",
}


def _resolve_category(name):
    """Resolve a category name or alias. Returns key or None."""
    key = name.lower().strip()
    if key in CATEGORIES:
        return key
    return CATEGORY_ALIASES.get(key)


def find_new_products(count, category=None):
    """
    Search Amazon using curated topics and return products
    whose ASINs have never been sent before.
    Optionally filter by category.
    """
    import random

    automate = AutomateCommand()
    automate.stdout = io.StringIO()  # Suppress console output

    # Load already-sent ASINs from database
    sent_asins = set(SentProduct.objects.values_list("asin", flat=True))

    region = getattr(settings, "AMAZON_REGION", "US").upper()
    domain = AMAZON_DOMAINS.get(region, "www.amazon.com")

    # Pick topics from the chosen category or all categories
    if category and category in CATEGORIES:
        topics = list(CATEGORIES[category]["topics"])
    else:
        topics = []
        for cat in CATEGORIES.values():
            topics.extend(cat["topics"])

    random.shuffle(topics)

    new_products = []
    seen_asins = set(sent_asins)  # Also track within this batch

    # Fetch extra to have room after filtering out duplicates
    per_topic_limit = min(count + len(sent_asins) + 10, 48)

    for topic in topics:
        if len(new_products) >= count:
            break

        try:
            products = automate.search_amazon(topic, per_topic_limit, domain)
        except CommandError:
            continue

        for product in products:
            if len(new_products) >= count:
                break

            asin = CreatePinCommand.extract_asin(product["url"])

            # Skip if already sent or already picked in this batch
            if asin and asin in seen_asins:
                continue

            if asin:
                seen_asins.add(asin)

            product["topic"] = topic
            new_products.append(product)

    return new_products


# ======================================================================
# Bot command handlers
# ======================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — show welcome message."""
    total_sent = await asyncio.to_thread(SentProduct.objects.count)

    cat_lines = "\n".join(
        f"  /new {key} - {cat['label']}" for key, cat in CATEGORIES.items()
    )

    await update.message.reply_text(
        f"<b>Pinterest Product Bot</b>\n\n"
        f"<b>Commands:</b>\n"
        f"/new - 1 random product\n"
        f"/new 3 - 3 random products\n\n"
        f"<b>By category:</b>\n"
        f"{cat_lines}\n\n"
        f"<b>Category + count:</b>\n"
        f"  /new phones 3\n"
        f"  /new homedecor 2\n\n"
        f"/stats - Products sent so far\n"
        f"/reset - Clear sent history\n\n"
        f"Total sent: <b>{total_sent}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats — show sent product statistics."""
    total = await asyncio.to_thread(SentProduct.objects.count)

    def _get_recent():
        return list(
            SentProduct.objects.order_by("-sent_at")[:5]
            .values_list("title", flat=True)
        )

    recent = await asyncio.to_thread(_get_recent)

    text = f"<b>Stats</b>\nTotal products sent: <b>{total}</b>\n"
    if recent:
        text += "\nRecent products:\n"
        for title in recent:
            short = title[:60] + ("..." if len(title) > 60 else "")
            text += f"- {short}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset — clear sent product history."""
    def _do_reset():
        n = SentProduct.objects.count()
        SentProduct.objects.all().delete()
        return n

    count = await asyncio.to_thread(_do_reset)
    await update.message.reply_text(
        f"Cleared <b>{count}</b> sent product records.\n"
        f"All products can now be sent again.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new [category] [count] — find and send new product pins."""

    # --- Parse arguments: category and/or count ---
    category = None
    count = 1
    cat_label = "random"

    args = list(context.args) if context.args else []

    # Try to parse category from first arg
    if args:
        resolved = _resolve_category(args[0])
        if resolved:
            category = resolved
            cat_label = CATEGORIES[resolved]["label"]
            args.pop(0)
        else:
            # Maybe it's just a number
            try:
                count = int(args[0])
                args.pop(0)
            except ValueError:
                # Try joining first two args as category (e.g. "phone accessories")
                if len(args) >= 2:
                    resolved = _resolve_category(f"{args[0]} {args[1]}")
                    if resolved:
                        category = resolved
                        cat_label = CATEGORIES[resolved]["label"]
                        args = args[2:]
                    else:
                        cat_list = ", ".join(CATEGORIES.keys())
                        await update.message.reply_text(
                            f"Unknown category: <b>{args[0]}</b>\n\n"
                            f"Available: {cat_list}\n"
                            f"Usage: /new [category] [count]",
                            parse_mode=ParseMode.HTML,
                        )
                        return
                else:
                    cat_list = ", ".join(CATEGORIES.keys())
                    await update.message.reply_text(
                        f"Unknown category: <b>{args[0]}</b>\n\n"
                        f"Available: {cat_list}\n"
                        f"Usage: /new [category] [count]",
                        parse_mode=ParseMode.HTML,
                    )
                    return

    # Try to parse count from remaining args
    if args:
        try:
            count = int(args[0])
        except ValueError:
            pass

    if count < 1 or count > 10:
        await update.message.reply_text("Please request between 1 and 10 products.")
        return

    # --- Status message ---
    status_msg = await update.message.reply_text(
        f"Searching for {count} fresh {cat_label} product(s)...\nThis may take a moment."
    )

    # --- Find new products (sync, runs in thread) ---
    try:
        products = await asyncio.to_thread(find_new_products, count, category)
    except Exception as exc:
        logger.error(f"Error finding products: {exc}", exc_info=True)
        await status_msg.edit_text(f"Error finding products: {exc}")
        return

    if not products:
        await status_msg.edit_text(
            f"Couldn't find any new {cat_label} products right now.\n"
            "Amazon may be rate-limiting requests. Try again in a few minutes."
        )
        return

    await status_msg.edit_text(
        f"Found {len(products)} {cat_label} product(s)! Generating Pinterest copy with AI..."
    )

    # --- Process each product: Gemini -> Telegram -> save ---
    create_pin = CreatePinCommand()
    create_pin.stdout = io.StringIO()  # Suppress console output
    sent_count = 0

    for i, product in enumerate(products):
        try:
            # Generate SEO copy via Gemini
            copy = await asyncio.to_thread(create_pin.generate_copy, product)

            # Send photo + formatted text to Telegram
            await asyncio.to_thread(create_pin.send_to_telegram, product, copy)

            # Save ASIN to database — never send this product again
            asin = CreatePinCommand.extract_asin(product["url"])
            if asin:
                await asyncio.to_thread(
                    SentProduct.objects.get_or_create,
                    asin=asin,
                    defaults={
                        "title": product["title"][:500],
                        "url": product["url"],
                        "topic": product.get("topic", "")[:200],
                    },
                )

            sent_count += 1

            # Small delay between products to avoid Telegram rate limits
            if i < len(products) - 1:
                await asyncio.sleep(2)

        except Exception as exc:
            logger.error(f"Error processing product {i + 1}: {exc}", exc_info=True)
            try:
                short_title = product["title"][:40]
                await update.message.reply_text(
                    f"Skipped product {i + 1} ({short_title}...): {exc}"
                )
            except Exception:
                pass

    # --- Final summary ---
    total_sent = await asyncio.to_thread(SentProduct.objects.count)
    await status_msg.edit_text(
        f"Done! Sent {sent_count}/{len(products)} product(s).\n"
        f"Total unique products sent: {total_sent}"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors cleanly instead of spamming tracebacks."""
    logger.error("Bot error: %s", context.error)


class Command(BaseCommand):
    help = "Run the Telegram bot. Send /new to get fresh Pinterest product pins."

    def handle(self, *args, **options):
        bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not bot_token or bot_token == "YOUR BOT TOKEN":
            raise CommandError("Set TELEGRAM_BOT_TOKEN in .env before running the bot.")

        self.stdout.write("Starting Pinterest Product Bot...")
        self.stdout.write("Press Ctrl+C to stop.\n")

        app = Application.builder().token(bot_token).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_start))
        app.add_handler(CommandHandler("new", cmd_new))
        app.add_handler(CommandHandler("stats", cmd_stats))
        app.add_handler(CommandHandler("reset", cmd_reset))
        app.add_error_handler(error_handler)

        self.stdout.write(self.style.SUCCESS(
            "Bot is running! Send /start or /new in Telegram."
        ))
        # drop_pending_updates=True ensures clean startup even if
        # a previous instance was running
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
