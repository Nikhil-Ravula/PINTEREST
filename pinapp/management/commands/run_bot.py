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
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

from pinapp.models import SentProduct, PendingPin
from pinapp.pinterest import publish_pin_to_pinterest, get_configured_boards
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
        f"<b>Pin Orbit | Pinterest Affiliate Bot</b>\n\n"
        f"<b>How it works:</b>\n"
        f"1. Send <code>/new</code> (or <code>/new phones</code>) to find a product.\n"
        f"2. Bot replies with the product image and normal Amazon link.\n"
        f"3. <b>Reply with your affiliate link</b> (e.g. <code>https://amzn.to/...</code>).\n"
        f"4. Bot creates the Pin on Pinterest and replies with all pin data!\n\n"
        f"<b>Commands:</b>\n"
        f"/new - Find 1 product\n"
        f"/new [category] - Find by category\n"
        f"/cancel - Cancel pending product\n"
        f"/stats - Products sent so far\n"
        f"/reset - Clear sent history\n\n"
        f"<b>Categories:</b>\n"
        f"{cat_lines}\n\n"
        f"Total unique products sent: <b>{total_sent}</b>",
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


ACTIVE_SEARCHES = set()


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new [category] — find 1 product and ask user for affiliate link."""
    chat_id = str(update.effective_chat.id)
    if chat_id in ACTIVE_SEARCHES:
        await update.message.reply_text(
            "⏳ <b>A product search is already running!</b>\n"
            "Please wait a few seconds for your product to arrive before requesting another.",
            parse_mode=ParseMode.HTML,
        )
        return

    category = None
    cat_label = "random"

    args = list(context.args) if context.args else []

    if args:
        resolved = _resolve_category(args[0])
        if resolved:
            category = resolved
            cat_label = CATEGORIES[resolved]["label"]
        elif len(args) >= 2:
            resolved = _resolve_category(f"{args[0]} {args[1]}")
            if resolved:
                category = resolved
                cat_label = CATEGORIES[resolved]["label"]
            else:
                cat_list = ", ".join(CATEGORIES.keys())
                await update.message.reply_text(
                    f"Unknown category: <b>{args[0]}</b>\n\n"
                    f"Available: {cat_list}\n"
                    f"Usage: /new [category]",
                    parse_mode=ParseMode.HTML,
                )
                return
        else:
            cat_list = ", ".join(CATEGORIES.keys())
            await update.message.reply_text(
                f"Unknown category: <b>{args[0]}</b>\n\n"
                f"Available: {cat_list}\n"
                f"Usage: /new [category]",
                parse_mode=ParseMode.HTML,
            )
            return

    ACTIVE_SEARCHES.add(chat_id)
    status_msg = await update.message.reply_text(
        f"🔍 Searching Amazon India for a fresh {cat_label} product...\nThis may take 15–25 seconds."
    )

    try:
        try:
            products = await asyncio.to_thread(find_new_products, 1, category)
        except Exception as exc:
            logger.error(f"Error finding products: {exc}", exc_info=True)
            await status_msg.edit_text(f"Error finding products: {exc}")
            return

        if not products:
            await status_msg.edit_text(
                f"Couldn't find any fresh {cat_label} products right now.\n"
                "Amazon may be rate-limiting. Try again in a couple minutes."
            )
            return

        product = products[0]
        try:
            await status_msg.edit_text("✨ Product found! Preparing Pinterest SEO copy...")
        except Exception:
            pass

        create_pin = CreatePinCommand()
        create_pin.stdout = io.StringIO()

        try:
            copy = await asyncio.to_thread(create_pin.generate_copy, product)
        except Exception as exc:
            logger.error(f"Copy generation failed: {exc}", exc_info=True)
            await status_msg.edit_text(f"Failed to generate copy: {exc}")
            return

        asin = CreatePinCommand.extract_asin(product["url"]) or ""

        # Save to PendingPin (replace any previous pending pin for this chat)
        def _save_pending():
            PendingPin.objects.filter(chat_id=chat_id).delete()
            return PendingPin.objects.create(
                chat_id=chat_id,
                asin=asin,
                title=product["title"][:500],
                original_url=product["url"],
                image_url=product["image_url"],
                topic=product.get("topic", "")[:200],
                pin_title=copy["title"],
                pin_description=copy["description"],
                pin_alt_text=copy["alt_text"],
                board_name=copy["board_name"],
            )

        await asyncio.to_thread(_save_pending)

        boards = get_configured_boards()
        board_menu_text, markup = build_board_menu(boards, copy["board_name"])

        short_title = CreatePinCommand._escape_html(product["title"][:120])
        escaped_url = CreatePinCommand._escape_html(product["url"])

        # 1. Send the product photo first
        photo_caption = f"🎯 <b>Product Found for Pin!</b>\n\n📦 <b>{short_title}...</b>"
        try:
            await update.message.reply_photo(
                photo=product["image_url"],
                caption=photo_caption,
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning(f"Could not send photo directly ({exc})")

        # 2. Send the Amazon Link and Board Selection Menu as a new message directly below the photo
        menu_text = (
            f"🔗 <b>Amazon Link:</b>\n"
            f"{escaped_url}\n\n"
            f"{board_menu_text}\n\n"
            f"👉 <b>Tap a button below or reply with a number (1–{len(boards)} or 0)</b>,\n"
            f"or directly paste your <b>Affiliate Link</b> (e.g. <code>https://amzn.to/...</code>)!\n\n"
            f"<i>(Send /cancel to skip this product)</i>"
        )

        try:
            await update.message.reply_text(
                menu_text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.error(f"Error sending board menu: {exc}", exc_info=True)
            await update.message.reply_text(
                f"🔗 Amazon Link:\n{product['url']}\n\n{board_menu_text}\n\n👉 Reply with board number or your affiliate link!",
                reply_markup=markup,
            )

        # 3. Clean up the initial search status message
        try:
            await status_msg.delete()
        except Exception:
            pass

    finally:
        ACTIVE_SEARCHES.discard(chat_id)


def build_board_menu(boards, ai_board):
    """Build formatted board list text and inline keyboard buttons."""
    lines = ["📋 <b>Choose Pinterest Board:</b>"]
    for i, b in enumerate(boards, 1):
        lines.append(f"  <b>{i}</b>. {CreatePinCommand._escape_html(b)}")
    lines.append(f"  <b>0</b>. ✨ AI Suggested: <i>{CreatePinCommand._escape_html(ai_board)}</i>")

    keyboard = []
    row = []
    for i, b in enumerate(boards, 1):
        label = f"{i}. {b[:18]}..." if len(b) > 20 else f"{i}. {b}"
        row.append(InlineKeyboardButton(label, callback_data=f"set_board_{i}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(f"✨ 0. AI Default: {ai_board[:22]}", callback_data="set_board_0")
    ])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def handle_board_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle tap on inline board selection buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if not data.startswith("set_board_"):
        return

    chat_id = str(query.message.chat.id)
    idx_str = data.replace("set_board_", "")
    boards = get_configured_boards()

    def _update_board():
        pending = PendingPin.objects.filter(chat_id=chat_id).first()
        if not pending:
            return None, None
        if idx_str == "0":
            chosen = pending.board_name
        else:
            try:
                idx = int(idx_str) - 1
                chosen = boards[idx]
                pending.board_name = chosen
                pending.save()
            except (ValueError, IndexError):
                chosen = pending.board_name
        return pending, chosen

    pending, chosen_board = await asyncio.to_thread(_update_board)
    if not pending:
        await query.message.reply_text("No active pending pin. Send /new to pick a product.")
        return

    await query.message.reply_text(
        f"✅ <b>Board selected:</b> {CreatePinCommand._escape_html(chosen_board)}\n\n"
        f"👉 <b>Now reply with your Affiliate Link</b> (e.g. <code>https://amzn.to/...</code>) to publish to Pinterest!\n\n"
        f"<i>(Send /cancel to skip this product)</i>",
        parse_mode=ParseMode.HTML,
    )


async def handle_affiliate_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Listen for user's board selection number OR affiliate link."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    chat_id = str(update.effective_chat.id)

    def _get_pending():
        return PendingPin.objects.filter(chat_id=chat_id).first()

    pending = await asyncio.to_thread(_get_pending)
    if not pending:
        return

    boards = get_configured_boards()

    # Case 1: User typed a board number (0 to len(boards))
    if text.isdigit():
        val = int(text)
        if val == 0:
            await update.message.reply_text(
                f"✅ <b>Board confirmed:</b> {CreatePinCommand._escape_html(pending.board_name)} (AI Suggested)\n\n"
                f"👉 <b>Now reply with your Affiliate Link</b> (e.g. <code>https://amzn.to/...</code>) to publish to Pinterest!\n\n"
                f"<i>(Send /cancel to skip this product)</i>",
                parse_mode=ParseMode.HTML,
            )
            return
        elif 1 <= val <= len(boards):
            chosen_board = boards[val - 1]
            def _save_board():
                pending.board_name = chosen_board
                pending.save()
            await asyncio.to_thread(_save_board)
            await update.message.reply_text(
                f"✅ <b>Board selected:</b> {CreatePinCommand._escape_html(chosen_board)}\n\n"
                f"👉 <b>Now reply with your Affiliate Link</b> (e.g. <code>https://amzn.to/...</code>) to publish to Pinterest!\n\n"
                f"<i>(Send /cancel to skip this product)</i>",
                parse_mode=ParseMode.HTML,
            )
            return
        else:
            await update.message.reply_text(
                f"⚠️ Invalid number. Please pick between 1 and {len(boards)} (or 0 for AI default).",
                parse_mode=ParseMode.HTML,
            )
            return

    # Case 2: User pasted an affiliate link
    match = re.search(r"https?://[^\s]+", text)
    if not match:
        await update.message.reply_text(
            f"⚠️ Please type a board number (1–{len(boards)} or 0) or send your affiliate link (e.g. <code>https://amzn.to/...</code>).\n\n"
            f"<i>(Send /cancel to discard this product)</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    affiliate_link = match.group(0).strip()
    status_msg = await update.message.reply_text(
        f"⏳ Publishing pin to board <b>{CreatePinCommand._escape_html(pending.board_name)}</b>...",
        parse_mode=ParseMode.HTML,
    )

    # Attempt publishing to Pinterest via API
    pin_res = await asyncio.to_thread(
        publish_pin_to_pinterest,
        title=pending.pin_title,
        description=pending.pin_description,
        link=affiliate_link,
        image_url=pending.image_url,
        alt_text=pending.pin_alt_text,
        board_name=pending.board_name,
    )

    # Save ASIN to SentProduct so it is never reused
    def _finalize():
        if pending.asin:
            SentProduct.objects.get_or_create(
                asin=pending.asin,
                defaults={
                    "title": pending.title[:500],
                    "url": pending.original_url,
                    "topic": pending.topic[:200],
                },
            )
        pending.delete()

    await asyncio.to_thread(_finalize)

    # Build response with all requested fields
    if pin_res.get("success"):
        header = "🎉 <b>PIN PUBLISHED TO PINTEREST!</b>"
        live_pin = f"📌 <b>LIVE PIN URL:</b>\n{pin_res['pin_url']}\n\n"
    else:
        header = "📝 <b>PIN DATA COMPLETED</b>"
        err = pin_res.get("error", "")
        live_pin = f"ℹ️ <i>Pinterest status: {err}</i>\n\n" if err else ""

    response_text = (
        f"{header}\n\n"
        f"{live_pin}"
        f"📌 <b>TITLE</b>\n"
        f"<code>{CreatePinCommand._escape_html(pending.pin_title)}</code>\n\n"
        f"📝 <b>DESCRIPTION</b>\n"
        f"<code>{CreatePinCommand._escape_html(pending.pin_description)}</code>\n\n"
        f"🖼️ <b>ALT TEXT</b>\n"
        f"<code>{CreatePinCommand._escape_html(pending.pin_alt_text)}</code>\n\n"
        f"📋 <b>BOARD NAME</b>\n"
        f"<code>{CreatePinCommand._escape_html(pending.board_name)}</code>\n\n"
        f"🔗 <b>AFFILIATE LINK</b>\n"
        f"{affiliate_link}"
    )

    await status_msg.edit_text(
        response_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel — discard active pending pin and stop active search."""
    chat_id = str(update.effective_chat.id)
    ACTIVE_SEARCHES.discard(chat_id)

    def _do_cancel():
        n = PendingPin.objects.filter(chat_id=chat_id).delete()
        return n[0] if n else 0

    count = await asyncio.to_thread(_do_cancel)
    if count > 0:
        await update.message.reply_text("❌ Cancelled pending product. Send /new to pick a fresh one.")
    else:
        await update.message.reply_text("No pending product to cancel. Send /new to pick one.")


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
        app.add_handler(CommandHandler("cancel", cmd_cancel))
        app.add_handler(CommandHandler("stats", cmd_stats))
        app.add_handler(CommandHandler("reset", cmd_reset))
        app.add_handler(CallbackQueryHandler(handle_board_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_affiliate_link))
        app.add_error_handler(error_handler)

        self.stdout.write(self.style.SUCCESS(
            "Bot is running! Send /start or /new in Telegram."
        ))
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
