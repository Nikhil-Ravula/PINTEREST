<div align="center">

<img src="pin_orbit_logo.jpg" alt="PinOrbit Logo" width="140"/>

# 🪐 PinOrbit

### *AI-Powered Pinterest Affiliate Marketing Automation*

> Discover trending Amazon products → Generate AI-crafted Pinterest copy → Publish to your boards — all from Telegram.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-6.1-092E20?style=for-the-badge&logo=django&logoColor=white)](https://djangoproject.com)
[![Telegram](https://img.shields.io/badge/Telegram_Bot-API-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Pinterest](https://img.shields.io/badge/Pinterest-API-E60023?style=for-the-badge&logo=pinterest&logoColor=white)](https://developers.pinterest.com)
[![Gemini](https://img.shields.io/badge/Google_Gemini-AI-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)

</div>

---

## ✨ What is PinOrbit?

**PinOrbit** is a fully automated affiliate marketing assistant. You chat with your Telegram bot, it scrapes trending products from Amazon India, uses Google Gemini AI to write beautiful Pinterest pin copy, and publishes the pin directly to your Pinterest board — with your affiliate link embedded.

No manual searching. No copy-writing. No switching between apps.

---

## 🎯 Key Features

| Feature | Description |
|---|---|
| 🤖 **Telegram Bot** | Control everything via simple Telegram commands |
| 🛍️ **Amazon Scraper** | Finds fresh trending products across 8 categories |
| 🧠 **AI Copy Generation** | Gemini writes SEO-optimized titles, descriptions & alt text |
| 📌 **Pinterest Publisher** | Posts directly to your chosen board via Pinterest API |
| 🔁 **Duplicate Prevention** | Tracks every posted product — never repeats |
| ⏰ **Reminder System** | Scheduled reminders push you to post at regular intervals |
| 🌐 **Web Dashboard** | View product library, stats, and automation controls |
| 🔐 **Pinterest OAuth** | Secure token-based board access |

---

## 🛠️ Tech Stack

```
Backend       →  Django 6.1 (Python)
Bot           →  python-telegram-bot 21+
AI            →  Google Gemini API (google-genai)
Scraping      →  requests + BeautifulSoup4
Pinterest     →  Pinterest API v5 (OAuth2)
Database      →  SQLite (dev) / upgradeable
Hosting       →  PythonAnywhere (webhook mode)
```

---

## 📁 Project Structure

```
PIN/
│
├── manage.py                        ← Django entry point
├── requirements.txt                 ← Python dependencies
├── .env                             ← 🔒 Secret keys (never commit)
├── .gitignore
├── pin_orbit_logo.jpg
│
├── pinpro/                          ← Django project config
│   ├── settings.py                  ← All settings & env variables
│   ├── urls.py                      ← URL routing
│   ├── wsgi.py / asgi.py
│
└── pinapp/                          ← Main application
    ├── models.py                    ← SentProduct, PendingPin
    ├── views.py                     ← Web + webhook views
    ├── pinterest.py                 ← Pinterest API client
    ├── admin.py                     ← Django admin setup
    │
    ├── bot/
    │   └── runner.py                ← Bot application builder
    │
    ├── management/commands/
    │   ├── run_bot.py               ← 🤖 Telegram bot (main command)
    │   ├── automate_pins.py         ← Amazon scraper & product finder
    │   └── create_pin.py            ← AI copy generator (Gemini)
    │
    ├── migrations/                  ← Database migrations
    └── templates/pinapp/            ← HTML dashboard templates
        ├── index.html
        ├── library.html
        ├── automations.html
        └── privacy.html
```

---

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/Nikhil-Ravula/PINTEREST.git
cd PINTEREST
```

### 2. Create a Virtual Environment

```bash
# Create
python -m venv .venv

# Activate (macOS/Linux)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
# ── Django ─────────────────────────────────────
SECRET_KEY=your-secret-key-here
DEBUG=True

# ── Telegram ───────────────────────────────────
TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token
TELEGRAM_CHAT_ID=your_numeric_chat_id
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret

# ── Google Gemini AI ───────────────────────────
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
GEMINI_RETRIES=3

# ── Amazon Scraper ─────────────────────────────
AMAZON_REGION=IN
SCRAPER_API_KEY=your_scraper_api_key   # optional proxy

# ── Pinterest ──────────────────────────────────
PINTEREST_APP_ID=your_app_id
PINTEREST_APP_SECRET=your_app_secret
PINTEREST_ACCESS_TOKEN=your_access_token
PINTEREST_REFRESH_TOKEN=your_refresh_token
PINTEREST_BOARD_ID=your_default_board_id
PINTEREST_REDIRECT_URI=https://your-domain.pythonanywhere.com/pinterest/callback/

# ── Automation ─────────────────────────────────
REMINDER_INTERVAL_MINUTES=30
```

### 5. Apply Database Migrations

```bash
python manage.py migrate
```

### 6. Start the Development Server

```bash
python manage.py runserver
```

Then open → **http://127.0.0.1:8000/**

---

## 🤖 Telegram Bot Commands

| Command | Action |
|---|---|
| `/start` | Show welcome message |
| `/new` | Find 1 fresh trending product |
| `/remind` | Trigger a posting reminder |
| `/cancel` | Cancel the current pending product |
| `/stats` | Show total products posted |
| `/reset` | Clear posting history |
| `/help` | Show all commands |

### How the Bot Flow Works

```
You send /new
     ↓
Bot picks a random category & searches Amazon India
     ↓
Bot sends you the product photo + name
     ↓
You choose a Pinterest board (or type a number)
     ↓
You paste your affiliate link
     ↓
Gemini AI writes the pin title, description & alt text
     ↓
Pin is published to Pinterest ✅
```

---

## 🌐 Web Dashboard Routes

| Route | Page |
|---|---|
| `/` | Home dashboard |
| `/discovery/` | Product discovery interface |
| `/library/` | Posted product history |
| `/automations/` | Automation controls |
| `/privacy/` | Privacy policy |
| `/pinterest/connect/` | Start Pinterest OAuth |
| `/pinterest/callback/` | OAuth callback handler |
| `/telegram/webhook/` | Telegram webhook endpoint |
| `/telegram/trigger-reminder/` | Trigger reminder manually |
| `/api/sent-products/` | JSON list of sent products |
| `/api/reset/` | Reset sent product history |
| `/admin/` | Django admin panel |

---

## 📌 Pinterest Boards

PinOrbit is pre-configured with 8 niche boards:

1. 📱 Mobile Accessories & Gadgets
2. 🏠 Modern Home Decor
3. 💻 Laptop Accessories & Setup
4. 📲 Best Smartphones & Reviews
5. 🖥️ Best Laptops & Reviews
6. ⌚ Best Watches & Smartwatches
7. ☀️ Summer Beauty & Fashion
8. 👗 Women Outfit Ideas

---

## ☁️ Deploying on PythonAnywhere

### Initial Setup

```bash
# In PythonAnywhere Bash console
git clone https://github.com/Nikhil-Ravula/PINTEREST.git ~/PINTEREST
cd ~/PINTEREST
pip install -r requirements.txt
python manage.py migrate
```

### Set the Telegram Webhook

```bash
python manage.py set_webhook
```

### Pull Latest Updates

```bash
cd ~/PINTEREST
git pull
```

Then go to the **Web** tab and click **Reload** to apply changes.

---

## 🔄 Updating the Bot

Whenever you push changes from your local machine:

```bash
# Local machine
git add .
git commit -m "your message"
git push origin main
```

```bash
# PythonAnywhere Bash console
cd ~/PINTEREST && git pull
```

Then click **Reload** on PythonAnywhere Web tab.

---

## 🧩 Database Models

### `SentProduct`
Tracks every product that has been sent — prevents duplicates.

| Field | Type | Description |
|---|---|---|
| `asin` | CharField (unique) | Amazon product ID |
| `title` | CharField | Product name |
| `url` | URLField | Amazon product URL |
| `topic` | CharField | Trend topic used |
| `sent_at` | DateTimeField | When it was sent |

### `PendingPin`
Stores a product waiting for the user's affiliate link before publishing.

| Field | Type | Description |
|---|---|---|
| `chat_id` | CharField | Telegram chat ID |
| `asin` | CharField | Amazon product ID |
| `pin_title` | CharField | AI-generated pin title |
| `pin_description` | TextField | AI-generated description |
| `pin_alt_text` | TextField | AI-generated alt text |
| `board_name` | CharField | Chosen Pinterest board |

---

## 🔒 Security Notes

> [!IMPORTANT]
> - Never commit your `.env` file — it contains all your API secrets
> - Set `DEBUG=False` in production
> - Use a strong random `SECRET_KEY` in production
> - Keep `TELEGRAM_WEBHOOK_SECRET` private to prevent spoofed requests

---

## 📦 Dependencies

```
Django >= 6.1
google-genai >= 1.0.0
python-telegram-bot >= 21.0
requests >= 2.31.0
beautifulsoup4 >= 4.12.0
pydantic >= 2.0.0
python-dotenv >= 1.0.0
```

---

## 🤝 Contributing

1. Fork this repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m "Add my feature"`
4. Push to the branch: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

You are free to use, copy, modify, and distribute this project as long as you include the original copyright notice.

---

<div align="center">

Made with ❤️ by **Nikhil Ravula**

*PinOrbit — Pin smarter, not harder.*

</div>
