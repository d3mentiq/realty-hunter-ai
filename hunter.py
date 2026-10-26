"""Main pipeline orchestrator for scraping, filtering, AI visual evaluation, and alerts."""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

import tracker_db
from config import get_config
from regex_engine import FilterRules, analyze_text
from scrapers.avito_scraper import fetch_avito_catalog
from scrapers.cian_scraper import fetch_cian_flats
from scrapers.yandex_scraper import fetch_yandex_flats
from telegram_bot import bot, format_flat_card_html, get_menu_keyboard
from vision_judge import judge_apartment_photos

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hunter")


def load_known_ids() -> set[str]:
    seen: set[str] = set()
    with tracker_db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM flats")
        seen.update(r["id"] for r in cur.fetchall())
    return seen


def notify_users_new_flat(flat: dict[str, Any]) -> None:
    cfg = get_config()
    for user_id in cfg.allowed_user_ids:
        if tracker_db.is_user_moderating(user_id):
            continue
        try:
            text = format_flat_card_html(flat)
            bot.send_message(user_id, f"⚡ <b>Новая подходящая квартира!</b>\n\n{text}", reply_markup=get_menu_keyboard())
        except Exception as e:
            logger.warning("Failed to send notification to user %s: %s", user_id, e)


def run_hunter_cycle() -> int:
    cfg = get_config()
    rules = FilterRules.from_config(cfg)
    tracker_db.init_db()

    known_ids = load_known_ids()
    logger.info("Known listings in database: %d", len(known_ids))

    all_raw_offers: list[dict[str, Any]] = []

    # 1. Cian
    try:
        cian_items = fetch_cian_flats()
        all_raw_offers.extend(cian_items)
        tracker_db.update_scanner_status("hunter", "cian", "ok", 200, items_found=len(cian_items))
        logger.info("Cian fetched %d listings", len(cian_items))
    except Exception as e:
        tracker_db.update_scanner_status("hunter", "cian", "error", 500, str(e))
        logger.error("Cian error: %s", e)

    # 2. Avito
    try:
        avito_items = fetch_avito_catalog()
        all_raw_offers.extend(avito_items)
        tracker_db.update_scanner_status("hunter", "avito", "ok", 200, items_found=len(avito_items))
        logger.info("Avito fetched %d listings", len(avito_items))
    except Exception as e:
        tracker_db.update_scanner_status("hunter", "avito", "error", 500, str(e))
        logger.error("Avito error: %s", e)

    # 3. Yandex
    try:
        yandex_items = fetch_yandex_flats()
        all_raw_offers.extend(yandex_items)
        tracker_db.update_scanner_status("hunter", "yandex", "ok", 200, items_found=len(yandex_items))
        logger.info("Yandex fetched %d listings", len(yandex_items))
    except Exception as e:
        tracker_db.update_scanner_status("hunter", "yandex", "error", 500, str(e))
        logger.error("Yandex error: %s", e)

    new_offers = [o for o in all_raw_offers if o["id"] not in known_ids]
    logger.info("Total fetched: %d, New to process: %d", len(all_raw_offers), len(new_offers))

    accepted_count = 0
    for offer in new_offers:
        res = analyze_text(offer, rules)
        if not res["passed"]:
            continue

        photos = offer.get("photos", [])
        if cfg.gemini_api_key and photos:
            try:
                eval_data = judge_apartment_photos(photos, offer)
                score = eval_data.get("score", 6)
                category = eval_data.get("category", "compromise")
                summary = eval_data.get("summary", "")
                why_fits = eval_data.get("why_it_fits", [])
                why_fails = eval_data.get("why_fails", [])
                meta = {"appliances": eval_data.get("appliances", {})}
            except Exception as e:
                logger.warning("Vision evaluation error: %s", e)
                score = 6
                category = "compromise"
                summary = "Оценка ИИ временно недоступна"
                why_fits, why_fails, meta = [], [], {}
        else:
            score = 6
            category = "compromise"
            summary = "Прошел текстовые фильтры"
            why_fits, why_fails, meta = [], [], {}

        flat_record = {
            "id": offer["id"],
            "source": offer.get("source", ""),
            "url": offer.get("url", ""),
            "addr": offer.get("addr", ""),
            "price": offer.get("price", 0),
            "deposit": res["deposit"],
            "commission": res["commission"],
            "move_in_cost": res["move_in_cost"],
            "bills_info": res["bills_info"],
            "floor_str": offer.get("floor_str", ""),
            "rooms": offer.get("rooms", 1),
            "score": score,
            "category": category,
            "summary": summary,
            "why_it_fits": why_fits,
            "why_fails": why_fails,
            "photos": photos,
            "meta": meta,
        }

        tracker_db.upsert_flat(flat_record)
        accepted_count += 1

        if category in ("cool", "compromise"):
            notify_users_new_flat(flat_record)

    logger.info("Cycle completed. Filtered and stored %d new flats", accepted_count)
    return accepted_count


def run_continuous_loop() -> None:
    cfg = get_config()
    logger.info("Starting Realty Hunter continuous worker (interval %d sec)...", cfg.scan_interval_sec)
    while True:
        try:
            run_hunter_cycle()
        except Exception as e:
            logger.error("Hunter loop unhandled exception: %s", e)
        time.sleep(cfg.scan_interval_sec)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_hunter_cycle()
    else:
        run_continuous_loop()
