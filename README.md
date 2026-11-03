# PINORBIT

A Django-based Pinterest product discovery and posting assistant built for automating product research, AI-driven pin creation, and Telegram-triggered workflows.

This project is designed to help identify trending products, generate Pinterest-ready copy, and publish them to Pinterest boards with minimal manual effort.

## Features

- Telegram bot workflow for product discovery and posting
- Amazon product discovery and trend-based product selection
- AI-generated Pinterest titles, descriptions, and alt text using Gemini
- Pinterest OAuth integration for secure board access
- Product tracking to prevent duplicate submissions
- Dashboard views for discovery, library, automations, and privacy pages
- Reminder flow for recurring posting checks
- SQLite-based local persistence for development

## Tech Stack

- Python
- Django 6
- Telegram Bot API
- Pinterest API
- Google Gemini API
- BeautifulSoup for scraping and data extraction
- SQLite database

## Repository Structure

```text
PINTEREST/
├── manage.py
├── requirements.txt
├── .gitignore
├── pinpro/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── pinapp/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── pinterest.py
│   ├── tests.py
│   ├── views.py
│   ├── bot/
│   ├── management/
│   ├── migrations/
│   └── templates/
├── pin_orbit_logo.jpg
└── db.sqlite3  (generated after setup)
```

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Nikhil-Ravula/PINTEREST.git
cd PINTEREST
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # On macOS/Linux
# .venv\Scripts\activate    # On Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root with the following variables:

```env
SECRET_KEY=your-secret-key
DEBUG=True
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.6-flash
AMAZON_REGION=US
SCRAPER_API_KEY=your_scraper_api_key
PINTEREST_APP_ID=your_pinterest_app_id
PINTEREST_APP_SECRET=your_pinterest_app_secret
PINTEREST_ACCESS_TOKEN=your_pinterest_access_token
PINTEREST_REFRESH_TOKEN=your_pinterest_refresh_token
PINTEREST_BOARD_ID=your_pinterest_board_id
PINTEREST_REDIRECT_URI=https://your-domain/pinterest/callback/
```

### 5. Run database migrations

```bash
python manage.py migrate
```

### 6. Start the development server

```bash
python manage.py runserver
```

Then open:

- http://127.0.0.1:8000/

## Usage

The application exposes both a web dashboard and a Telegram-integrated bot flow.

### Web dashboard

Routes include:

- `/` — home dashboard
- `/discovery/` — product discovery interface
- `/library/` — sent product library
- `/automations/` — automation controls
- `/privacy/` — privacy page

### OAuth flow

Pinterest authentication is handled through:

- `/pinterest/connect/`
- `/pinterest/callback/`

### Telegram webhook and reminder

- `/telegram/webhook/` — handles incoming Telegram updates
- `/telegram/trigger-reminder/` — sends reminder prompts for posting

## Production Notes

- The project is configured for Django deployment and already includes PythonAnywhere-friendly host settings.
- The app relies on environment variables rather than hardcoded secrets.
- For production deployment, set `DEBUG=False` and configure a secure `SECRET_KEY`.

## License

This project does not currently include a license file. If you plan to distribute or reuse it publicly, add an appropriate open-source license before publishing.

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Open a pull request

## Support

For questions or issues, open a GitHub issue in this repository.
