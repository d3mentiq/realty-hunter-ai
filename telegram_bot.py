"""Telegram UI bot for browsing, scoring, and moderating property listings."""

from __future__ import annotations

import html
import sys
import threading
from typing import Any
import telebot
from telebot import types

import tracker_db
from config import get_config
from vision_judge import judge_apartment_photos

try:
    from scrapers.avito_scraper import fetch_avito_single
except ImportError:
    fetch_avito_single = None

_cfg = get_config()
bot = telebot.TeleBot(_cfg.telegram_bot_token, parse_mode="HTML")
USER_STATES: dict[int, dict[str, Any]] = {}


def is_user_allowed(user_id: int) -> bool:
    allowed = get_config().allowed_user_ids
    if not allowed:
        return False
    return user_id in allowed


def get_menu_keyboard(chat_id: int | None = None) -> types.InlineKeyboardMarkup:
    counts = tracker_db.get_counts()
    markup = types.InlineKeyboardMarkup(row_width=2)
    b_mod = types.InlineKeyboardButton(f"🆕 На модерацию ({counts.get('unreviewed', 0)})", callback_data="mod:0")
    b_cool = types.InlineKeyboardButton(f"🔥 Отобранные ({counts['cool']})", callback_data="cat:cool:0")
    b_comp = types.InlineKeyboardButton(f"⚖️ Компромисс ({counts['compromise']})", callback_data="cat:compromise:0")
    b_trash = types.InlineKeyboardButton(f"❌ Отклоненные ({counts['trash']})", callback_data="cat:trash:0")
    b_add = types.InlineKeyboardButton("➕ Добавить по ссылке", callback_data="prompt_add_url")

    markup.add(b_mod)
    markup.add(b_cool, b_comp)
    markup.add(b_trash, b_add)
    return markup


def format_flat_card_html(flat: dict[str, Any], index: int | None = None, total: int | None = None, is_moderation: bool = False) -> str:
    cat = flat.get("effective_category", flat.get("category", "trash"))
    cat_badge = "🔥 ОТОБРАНО" if cat == "cool" else ("⚖️ КОМПРОМИСС" if cat == "compromise" else "❌ ОТКЛОНЕНО")

    ai_score = flat.get("score", 5)
    user_score = flat.get("user_score_override")
    if user_score is not None:
        score_text = f"⭐ <b>{user_score}/10</b> <i>(ручная оценка, ИИ: {ai_score}/10)</i>"
    else:
        score_text = f"<b>{ai_score}/10</b>"

    addr = html.escape(str(flat.get("addr", "Не указан")))
    price = int(flat.get("price", 0))
    bills = html.escape(str(flat.get("bills_info", "")))
    floor = html.escape(str(flat.get("floor_str", "")))
    url = flat.get("url", "")
    summary = html.escape(str(flat.get("summary", "")))
    user_note = html.escape(str(flat.get("user_note", "")))

    dep = int(flat.get("deposit", 0) or 0)
    comm = int(flat.get("commission", 0) or 0)
    move_in = int(flat.get("move_in_cost", 0) or (price + (dep // 2) + comm))

    dep_str = f"залог {dep:,} ₽".replace(",", " ") if dep > 0 else "без залога"
    comm_str = f"комса {comm:,} ₽".replace(",", " ") if comm > 0 else "без комиссии"

    meta = flat.get("meta", {})
    appliances = meta.get("appliances", {}) if isinstance(meta, dict) else {}
    app_icons = []
    if appliances.get("fridge"):
        app_icons.append("✅ Холодильник")
    if appliances.get("washing_machine"):
        app_icons.append("✅ Стиралка")
    if appliances.get("stove"):
        app_icons.append("✅ Плита")
    if appliances.get("microwave"):
        app_icons.append("✅ СВЧ")
    tech_line = " • ".join(app_icons) if app_icons else "не распознано"

    header = f"<b>{cat_badge} • Оценка: {score_text}</b>"
    if index is not None and total is not None:
        header = f"[{index + 1}/{total}] {header}"

    lines = [
        header,
        f"📍 <b>Адрес:</b> {addr}" + (f" (эт. {floor})" if floor else ""),
        f"💰 <b>Аренда:</b> {price:,} ₽/мес".replace(",", " ") + (f" <i>({bills})</i>" if bills else ""),
        f"💸 <b>Въезд:</b> <b>{move_in:,} ₽</b> <i>(аренда + {dep_str} + {comm_str})</i>".replace(",", " "),
        f"👁 <b>Техника:</b> {tech_line}",
    ]
    if summary:
        lines.append(f"💡 <b>Вердикт:</b> <i>{summary}</i>")
    if user_note:
        lines.append(f"📝 <b>Заметка:</b> <code>{user_note}</code>")
    if url:
        lines.append(f"🔗 <a href='{url}'>Открыть объявление на сайте</a>")

    return "\n".join(lines)


def get_card_keyboard(flat_id: str, index: int, total: int, source_view: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=3)
    b_cool = types.InlineKeyboardButton("🔥 В отобранные", callback_data=f"setcat:{flat_id}:cool:{source_view}:{index}")
    b_comp = types.InlineKeyboardButton("⚖️ 50/50", callback_data=f"setcat:{flat_id}:compromise:{source_view}:{index}")
    b_trash = types.InlineKeyboardButton("❌ В мусор", callback_data=f"setcat:{flat_id}:trash:{source_view}:{index}")
    markup.add(b_cool, b_comp, b_trash)

    # Score buttons 1..10
    score_btns = [
        types.InlineKeyboardButton(str(s), callback_data=f"setscore:{flat_id}:{s}:{source_view}:{index}")
        for s in range(1, 11)
    ]
    markup.row(*score_btns[:5])
    markup.row(*score_btns[5:])

    # Navigation
    nav_btns = []
    if index > 0:
        nav_btns.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"page:{source_view}:{index - 1}"))
    if index < total - 1:
        nav_btns.append(types.InlineKeyboardButton("Вперед ➡️", callback_data=f"page:{source_view}:{index + 1}"))
    if nav_btns:
        markup.row(*nav_btns)

    b_note = types.InlineKeyboardButton("📝 Добавить заметку", callback_data=f"prompt_note:{flat_id}:{source_view}:{index}")
    b_menu = types.InlineKeyboardButton("🔙 Главное меню", callback_data="open_menu")
    markup.row(b_note, b_menu)
    return markup


@bot.message_handler(commands=["start", "menu"])
def cmd_start(message: types.Message) -> None:
    if not is_user_allowed(message.from_user.id):
        bot.reply_to(message, "Доступ ограничен.")
        return
    bot.send_message(
        message.chat.id,
        "🏠 <b>Бот поиска и модерации квартир</b>\nВыберите категорию для просмотра:",
        reply_markup=get_menu_keyboard(message.chat.id),
    )


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call: types.CallbackQuery) -> None:
    if not is_user_allowed(call.from_user.id):
        bot.answer_callback_query(call.id, "Доступ запрещен", show_alert=True)
        return

    tracker_db.touch_moderation(call.message.chat.id)
    data = call.data

    if data == "open_menu":
        bot.edit_message_text(
            "🏠 <b>Главное меню:</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_menu_keyboard(call.message.chat.id),
        )
        return

    if data.startswith("mod:"):
        idx = int(data.split(":")[1])
        flats = tracker_db.get_unreviewed_flats()
        if not flats:
            bot.answer_callback_query(call.id, "Нет новых непросмотренных квартир!")
            return
        idx = max(0, min(idx, len(flats) - 1))
        f = flats[idx]
        text = format_flat_card_html(f, idx, len(flats), is_moderation=True)
        kb = get_card_keyboard(f["id"], idx, len(flats), "mod")
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, disable_web_page_preview=False)
        return

    if data.startswith("cat:"):
        _, cat, idx_str = data.split(":")
        idx = int(idx_str)
        flats = tracker_db.get_flats_by_category(cat)
        if not flats:
            bot.answer_callback_query(call.id, f"Категория {cat} пуста")
            return
        idx = max(0, min(idx, len(flats) - 1))
        f = flats[idx]
        text = format_flat_card_html(f, idx, len(flats))
        kb = get_card_keyboard(f["id"], idx, len(flats), f"cat_{cat}")
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, disable_web_page_preview=False)
        return

    if data.startswith("setcat:"):
        _, fid, new_cat, source_view, idx_str = data.split(":")
        idx = int(idx_str)
        tracker_db.mark_reviewed(fid, new_category=new_cat)
        bot.answer_callback_query(call.id, f"Категория изменена: {new_cat}")

        # Refresh view
        if source_view == "mod":
            flats = tracker_db.get_unreviewed_flats()
        elif source_view.startswith("cat_"):
            flats = tracker_db.get_flats_by_category(source_view.split("_")[1])
        else:
            flats = []

        if not flats:
            bot.edit_message_text("Список пуст.", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_menu_keyboard())
            return
        idx = max(0, min(idx, len(flats) - 1))
        f = flats[idx]
        text = format_flat_card_html(f, idx, len(flats), is_moderation=(source_view == "mod"))
        kb = get_card_keyboard(f["id"], idx, len(flats), source_view)
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
        return

    if data.startswith("setscore:"):
        _, fid, score_str, source_view, idx_str = data.split(":")
        tracker_db.update_user_score(fid, int(score_str))
        bot.answer_callback_query(call.id, f"Оценка: {score_str}/10 ⭐")
        f = tracker_db.get_flat(fid)
        if f:
            total = 1
            text = format_flat_card_html(f, int(idx_str), total)
            kb = get_card_keyboard(f["id"], int(idx_str), total, source_view)
            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
        return

    if data.startswith("page:"):
        _, source_view, idx_str = data.split(":")
        idx = int(idx_str)
        if source_view == "mod":
            flats = tracker_db.get_unreviewed_flats()
        elif source_view.startswith("cat_"):
            flats = tracker_db.get_flats_by_category(source_view.split("_")[1])
        else:
            flats = []
        if not flats:
            return
        idx = max(0, min(idx, len(flats) - 1))
        f = flats[idx]
        text = format_flat_card_html(f, idx, len(flats), is_moderation=(source_view == "mod"))
        kb = get_card_keyboard(f["id"], idx, len(flats), source_view)
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
        return

    if data.startswith("prompt_note:"):
        _, fid, source_view, idx_str = data.split(":")
        USER_STATES[call.message.chat.id] = {
            "state": "waiting_note",
            "flat_id": fid,
            "source_view": source_view,
            "index": int(idx_str),
        }
        bot.send_message(call.message.chat.id, "Отправьте текст заметки в ответном сообщении:")
        return

    if data == "prompt_add_url":
        USER_STATES[call.message.chat.id] = {"state": "waiting_add_url"}
        bot.send_message(call.message.chat.id, "Отправьте ссылку на квартиру (Циан, Авито, Яндекс):")
        return


@bot.message_handler(func=lambda msg: True)
def handle_user_text(message: types.Message) -> None:
    if not is_user_allowed(message.from_user.id):
        return

    state_info = USER_STATES.pop(message.chat.id, None)
    if not state_info:
        return

    if state_info.get("state") == "waiting_note":
        fid = state_info["flat_id"]
        note = message.text.strip()
        tracker_db.set_user_note(fid, note)
        bot.reply_to(message, "Заметка сохранена! Обновите карточку.")
        return

    if state_info.get("state") == "waiting_add_url":
        url = message.text.strip()
        bot.reply_to(message, "Обрабатываю ссылку...")
        # Simple manual insert fallback
        flat_data = {
            "id": f"manual_{abs(hash(url))}",
            "source": "Вручную",
            "url": url,
            "addr": "Добавлено пользователем",
            "price": 0,
            "summary": "Добавлено вручную по ссылке",
            "category": "cool",
        }
        tracker_db.upsert_flat(flat_data)
        bot.send_message(message.chat.id, "Квартира добавлена в список!", reply_markup=get_menu_keyboard())


def start_bot_background() -> threading.Thread:
    def _run() -> None:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"[TelegramBot Error] {e}", file=sys.stderr)

    t = threading.Thread(target=_run, daemon=True, name="TelegramBotWorker")
    t.start()
    return t


if __name__ == "__main__":
    tracker_db.init_db()
    print("Starting bot polling...")
    bot.infinity_polling()
