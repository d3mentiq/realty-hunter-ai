"""Smoke test suite verifying config, SQLite storage, and text filter heuristics."""

import os
import sys
import tempfile
from pathlib import Path

# Set dummy env vars for testing before importing config
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:dummy_test_token"
os.environ["ALLOWED_USER_IDS"] = "111222333"

import config
import tracker_db
from regex_engine import FilterRules, analyze_text


def test_config() -> None:
    cfg = config.get_config()
    assert cfg.telegram_bot_token == "123456:dummy_test_token"
    assert cfg.allowed_user_ids == (111222333,)
    assert cfg.db_path.is_absolute(), "DB_PATH must be anchored to an absolute path"
    print("  [OK] Config initialization and path anchoring")


def test_tracker_db() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_flats.db"
        tracker_db.init_db(test_db)

        # Upsert test listing
        sample_flat = {
            "id": "cian_999999",
            "source": "Циан",
            "url": "https://cian.ru/rent/flat/999999/",
            "addr": "ул. Тестовая, 10",
            "price": 30000,
            "deposit": 30000,
            "commission": 15000,
            "move_in_cost": 60000,
            "bills_info": "+ счетчики",
            "floor_str": "5/10",
            "rooms": 1,
            "score": 8,
            "category": "cool",
            "summary": "Чистая квартира с ремонтом",
            "why_it_fits": ["Свежий ремонт", "Вся техника"],
            "why_fails": [],
            "photos": ["https://example.com/p1.jpg"],
            "meta": {"appliances": {"fridge": True, "washing_machine": True}},
        }
        tracker_db.upsert_flat(sample_flat, test_db)

        # Retrieve and verify
        retrieved = tracker_db.get_flat("cian_999999", test_db)
        assert retrieved is not None
        assert retrieved["price"] == 30000
        assert retrieved["effective_category"] == "cool"
        assert retrieved["meta"]["appliances"]["fridge"] is True

        # Test review state update
        tracker_db.mark_reviewed("cian_999999", new_category="compromise", db_path=test_db)
        updated = tracker_db.get_flat("cian_999999", test_db)
        assert updated["effective_category"] == "compromise"
        assert updated["is_reviewed"] == 1

        # Test counts
        counts = tracker_db.get_counts(db_path=test_db)
        assert counts["compromise"] == 1
        assert counts["total"] == 1

        # Test user touch and moderation check
        tracker_db.touch_moderation(111222333, db_path=test_db)
        assert tracker_db.is_user_moderating(111222333, timeout_seconds=60, db_path=test_db) is True

    print("  [OK] SQLite schema, WAL mode, CRUD, and review tracking")


def test_regex_engine() -> None:
    rules = FilterRules(
        min_price=20000,
        max_price=45000,
        max_commission=15000,
        max_move_in_cost=70000,
        disallowed_floors=(1,),
        disallowed_keywords=("промзона", "подвал"),
    )

    # 1. Floor 1 must be dropped
    offer_bad_floor = {"addr": "Центр", "desc": "Отличная квартира", "price": 30000, "floor_num": 1}
    assert analyze_text(offer_bad_floor, rules)["passed"] is False

    # 2. Disallowed keyword must be dropped
    offer_bad_kw = {"addr": "Промзона, дом 1", "desc": "Обычная квартира", "price": 30000, "floor_num": 3}
    assert analyze_text(offer_bad_kw, rules)["passed"] is False

    # 3. Female-only trigger must be dropped
    offer_female_only = {"addr": "Центр", "desc": "Сдам только для девушки студентки", "price": 30000, "floor_num": 3}
    assert analyze_text(offer_female_only, rules)["passed"] is False

    # 4. Valid offer passes and computes financials correctly
    offer_good = {
        "addr": "ул. Мира, 5",
        "desc": "Сдам уютную квартиру на длительный срок. Залог 20 000 руб (можно разбить на 2 месяца). Комиссия 50%. Свет и вода по счетчикам.",
        "price": 30000,
        "floor_num": 4,
    }
    res = analyze_text(offer_good, rules)
    assert res["passed"] is True
    assert res["deposit"] == 20000
    assert res["commission"] == 15000
    # move_in_cost = 30000 rent + (20000/2) deposit part + 15000 commission = 55000
    assert res["move_in_cost"] == 55000

    print("  [OK] FilterRules heuristic checks, drop triggers, and financial calculations")


def main() -> None:
    print("Running realty-hunter-ai smoke test suite:")
    test_config()
    test_tracker_db()
    test_regex_engine()
    print("\nALL SMOKE TESTS PASSED!")


if __name__ == "__main__":
    main()
