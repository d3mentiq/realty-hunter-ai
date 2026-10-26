# AGENTS.md — Agent Setup & Contribution Guide

This document is intended for AI coding agents and automated orchestrators working on `realty-hunter-ai`.

---

## Architecture Overview

`realty-hunter-ai` is an autonomous apartment hunting pipeline and moderation engine:

1. **Scrapers (`scrapers/`)**: Fetches listings concurrently from Cian, Avito, and Yandex Realty using stealth HTTP clients (`curl_cffi`).
2. **Text Heuristics (`regex_engine.py`)**: Filters listings based on price thresholds, forbidden keywords, floor requirements, and room configurations. Parses deposits, commission fees, and utility bills.
3. **Visual Evaluator (`vision_judge.py`)**: Submits compressed property photos to Google Gemini Vision to evaluate renovation quality, basic appliances, and living conditions.
4. **Data Persistence (`tracker_db.py`)**: SQLite storage with atomic transactions, category tagging (`cool`, `compromise`, `trash`), and user review state tracking.
5. **Interactive UI (`telegram_bot.py`)**: Interactive Telegram bot offering a moderation queue, manual score overrides (1–10), and direct note-taking.
6. **Continuous Runner (`hunter.py`, `hunter_worker.py`)**: Periodically triggers hunt cycles and sends alerts for approved listings.

---

## Agent Setup Guide

### 1. Environment & Dependencies

```bash
python -m venv venv
# Linux / macOS
source venv/bin/activate
# Windows PowerShell
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 2. Configuration Setup

Copy the example template and supply environment parameters:

```bash
cp .env.example .env
```

Minimal required variables in `.env`:
- `TELEGRAM_BOT_TOKEN`: Telegram bot token from @BotFather.
- `ALLOWED_USER_IDS`: Comma-separated Telegram user IDs allowed to interact with the bot.
- `CITY`: Name of target city (e.g. `Москва` or `Санкт-Петербург`).
- `MIN_PRICE`: Minimum rent price (integer).
- `MAX_PRICE`: Maximum rent price (integer).
- `GEMINI_API_KEY`: (Optional) API key for Google Gemini Vision evaluation.

### 3. Database Initialization & Verification

Run the initialization check:

```bash
python -c "import tracker_db; tracker_db.init_db(); print('Database OK')"
```

### 4. Running a Dry Run

Test a single scrape and filtering pass without starting background workers:

```bash
python hunter.py --once
```

### 5. Running the Services

To run the interactive Telegram bot:
```bash
python telegram_bot.py
```

To run the scheduled scraper worker in background:
```bash
python hunter_worker.py
```

---

## Adding New Scrapers

When extending the pipeline with a new rental portal:

1. Create `scrapers/<source>_scraper.py`.
2. Implement a scraping function returning list of dictionaries:
   ```python
   def fetch_source_flats(min_price: int | None = None, max_price: int | None = None, max_pages: int = 5) -> list[dict[str, Any]]:
       ...
   ```
   Required keys per item: `id`, `source`, `url`, `addr`, `price`, `floor_num`, `floor_total`, `floor_str`, `photos`, `desc`.
3. Register the scraper in `hunter.py` inside `run_hunter_cycle()`.
4. Update scanner metrics using `tracker_db.update_scanner_status()`.

---

## Code Quality & Security Standards for Agents

- **Zero Hardcoded Personal Data**: Never commit personal search districts, personal user IDs, or specific flat limits into code. Everything must flow through `Config` and `FilterRules`.
- **No Unsolicited Dependencies**: Use existing standard library and `curl_cffi`, `pyTelegramBotAPI`, and `Pillow`.
- **Clean SQLite Schema**: Always use parameterized SQL statements to prevent injection and corruption.
- **Fail Gracefully**: External scrapers or network drops must be handled with appropriate try-catch blocks and logged via `logging`.
