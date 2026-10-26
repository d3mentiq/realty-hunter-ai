"""SQLite storage layer for listings, review state, user sessions, and scanner metrics."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from config import get_config


def _resolve_db_path(db_path: Path | str | None = None) -> Path:
    if db_path is not None:
        p = Path(db_path)
    else:
        try:
            p = get_config().db_path
        except Exception:
            p = Path("data/flats.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def get_connection(db_path: Path | str | None = None) -> Generator[sqlite3.Connection, None, None]:
    path = _resolve_db_path(db_path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS flats (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            addr TEXT NOT NULL,
            price INTEGER NOT NULL,
            deposit INTEGER DEFAULT 0,
            commission INTEGER DEFAULT 0,
            move_in_cost INTEGER DEFAULT 0,
            bills_info TEXT DEFAULT '',
            floor_str TEXT DEFAULT '',
            rooms INTEGER DEFAULT 1,
            score INTEGER DEFAULT 0,
            category TEXT DEFAULT 'trash' CHECK(category IN ('cool', 'compromise', 'trash')),
            user_category_override TEXT CHECK(user_category_override IS NULL OR user_category_override IN ('cool', 'compromise', 'trash')),
            user_score_override INTEGER,
            user_note TEXT DEFAULT '',
            is_reviewed INTEGER DEFAULT 0,
            summary TEXT DEFAULT '',
            why_it_fits TEXT DEFAULT '[]',
            why_fails TEXT DEFAULT '[]',
            photos TEXT DEFAULT '[]',
            tags TEXT DEFAULT '[]',
            meta TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_flats_cat ON flats (category);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_flats_reviewed ON flats (is_reviewed);")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            mode TEXT DEFAULT 'default',
            last_moderation_ts REAL DEFAULT 0
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS scanner_status (
            source_key TEXT PRIMARY KEY,
            host TEXT NOT NULL,
            platform TEXT NOT NULL,
            status TEXT NOT NULL,
            status_code INTEGER DEFAULT 200,
            details TEXT DEFAULT '',
            items_found INTEGER DEFAULT 0,
            last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_scanned_ts REAL
        );
        """)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for field in ("why_it_fits", "why_fails", "photos", "tags"):
        raw = d.get(field)
        d[field] = json.loads(raw) if raw else []
    raw_meta = d.get("meta")
    d["meta"] = json.loads(raw_meta) if raw_meta else {}
    d["effective_category"] = d["user_category_override"] or d["category"]
    d["effective_score"] = d["user_score_override"] if d.get("user_score_override") is not None else d.get("score", 0)
    return d


def upsert_flat(flat: dict[str, Any], db_path: Path | str | None = None) -> None:
    raw_cat = flat.get("category", "trash")
    if "cool" in raw_cat.lower() or "крут" in raw_cat.lower():
        cat = "cool"
    elif "comp" in raw_cat.lower() or "50" in raw_cat:
        cat = "compromise"
    else:
        cat = "trash"

    price = int(flat.get("price", 0))
    deposit = int(flat.get("deposit", 0) or 0)
    commission = int(flat.get("commission", 0) or 0)
    move_in_cost = flat.get("move_in_cost")
    if move_in_cost is None:
        move_in_cost = price + (deposit // 2) + commission

    params = {
        "id": str(flat["id"]),
        "source": flat.get("source", ""),
        "url": flat.get("url", ""),
        "addr": flat.get("addr", ""),
        "price": price,
        "deposit": deposit,
        "commission": commission,
        "move_in_cost": int(move_in_cost),
        "bills_info": flat.get("bills_info", ""),
        "floor_str": flat.get("floor_str", ""),
        "rooms": int(flat.get("rooms", 1)),
        "score": int(flat.get("score", 0)),
        "category": cat,
        "summary": flat.get("summary", ""),
        "why_it_fits": json.dumps(flat.get("why_it_fits", []), ensure_ascii=False),
        "why_fails": json.dumps(flat.get("why_fails", []), ensure_ascii=False),
        "photos": json.dumps(flat.get("photos", []), ensure_ascii=False),
        "tags": json.dumps(flat.get("tags", []), ensure_ascii=False),
        "meta": json.dumps(flat.get("meta", {}), ensure_ascii=False),
    }

    with get_connection(db_path) as conn:
        conn.execute("""
        INSERT INTO flats (
            id, source, url, addr, price, deposit, commission, move_in_cost,
            bills_info, floor_str, rooms, score, category, summary,
            why_it_fits, why_fails, photos, tags, meta
        ) VALUES (
            :id, :source, :url, :addr, :price, :deposit, :commission, :move_in_cost,
            :bills_info, :floor_str, :rooms, :score, :category, :summary,
            :why_it_fits, :why_fails, :photos, :tags, :meta
        )
        ON CONFLICT(id) DO UPDATE SET
            source=excluded.source,
            url=excluded.url,
            addr=excluded.addr,
            price=excluded.price,
            deposit=excluded.deposit,
            commission=excluded.commission,
            move_in_cost=excluded.move_in_cost,
            bills_info=excluded.bills_info,
            floor_str=excluded.floor_str,
            rooms=excluded.rooms,
            score=excluded.score,
            category=excluded.category,
            summary=excluded.summary,
            why_it_fits=excluded.why_it_fits,
            why_fails=excluded.why_fails,
            photos=excluded.photos,
            tags=excluded.tags,
            meta=excluded.meta,
            updated_at=CURRENT_TIMESTAMP;
        """, params)


def get_flat(flat_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM flats WHERE id = ?", (flat_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def get_flats_by_category(category: str, tag: str | None = None, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        query = """
        SELECT * FROM flats
        WHERE COALESCE(user_category_override, category) = ?
        """
        params: list[Any] = [category]
        if tag is not None:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        query += " ORDER BY COALESCE(user_score_override, score) DESC, price ASC"
        cur.execute(query, params)
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_unreviewed_flats(tag: str | None = None, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        query = "SELECT * FROM flats WHERE COALESCE(is_reviewed, 0) = 0"
        params: list[Any] = []
        if tag is not None:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        query += " ORDER BY COALESCE(user_score_override, score) DESC, price ASC"
        cur.execute(query, params)
        return [_row_to_dict(r) for r in cur.fetchall()]


def mark_reviewed(flat_id: str, new_category: str | None = None, db_path: Path | str | None = None) -> None:
    with get_connection(db_path) as conn:
        if new_category:
            conn.execute("""
            UPDATE flats
            SET is_reviewed = 1, user_category_override = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """, (new_category, flat_id))
        else:
            conn.execute("""
            UPDATE flats
            SET is_reviewed = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """, (flat_id,))


def update_user_score(flat_id: str, new_score: int, db_path: Path | str | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("""
        UPDATE flats
        SET user_score_override = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (new_score, flat_id))


def set_user_note(flat_id: str, note: str, db_path: Path | str | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("""
        UPDATE flats
        SET user_note = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (note.strip(), flat_id))


def get_counts(tag: str | None = None, db_path: Path | str | None = None) -> dict[str, int]:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cat_query = "SELECT COALESCE(user_category_override, category) as cat, COUNT(*) as cnt FROM flats"
        unreviewed_query = "SELECT COUNT(*) FROM flats WHERE COALESCE(is_reviewed, 0) = 0"
        params: list[Any] = []
        if tag is not None:
            where_tag = " WHERE tags LIKE ?"
            cat_query += where_tag + " GROUP BY cat"
            unreviewed_query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        else:
            cat_query += " GROUP BY cat"

        cur.execute(cat_query, params)
        rows = cur.fetchall()

        cur.execute(unreviewed_query, params)
        unreviewed_cnt = cur.fetchone()[0]

    counts = {"cool": 0, "compromise": 0, "trash": 0, "total": 0, "unreviewed": unreviewed_cnt}
    for r in rows:
        c = r["cat"]
        if c in counts:
            counts[c] = r["cnt"]
            counts["total"] += r["cnt"]
    return counts


def touch_moderation(chat_id: int, db_path: Path | str | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("""
        INSERT INTO users (chat_id, last_moderation_ts)
        VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET last_moderation_ts = excluded.last_moderation_ts;
        """, (chat_id, time.time()))


def is_user_moderating(chat_id: int, timeout_seconds: float = 600.0, db_path: Path | str | None = None) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT last_moderation_ts FROM users WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        if row and row["last_moderation_ts"]:
            return (time.time() - float(row["last_moderation_ts"])) < timeout_seconds
        return False


def get_user_mode(chat_id: int, db_path: Path | str | None = None) -> str:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT mode FROM users WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        return row["mode"] if row and row["mode"] else "default"


def set_user_mode(chat_id: int, mode: str, db_path: Path | str | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("""
        INSERT INTO users (chat_id, mode) VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET mode = excluded.mode;
        """, (chat_id, mode))


def update_scanner_status(
    host: str,
    platform: str,
    status: str,
    status_code: int = 200,
    details: str = "",
    items_found: int = 0,
    db_path: Path | str | None = None,
) -> None:
    key = f"{host.lower()}_{platform.lower()}"
    with get_connection(db_path) as conn:
        conn.execute("""
        INSERT INTO scanner_status (source_key, host, platform, status, status_code, details, items_found, last_scanned, last_scanned_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            status = excluded.status,
            status_code = excluded.status_code,
            details = excluded.details,
            items_found = excluded.items_found,
            last_scanned = CURRENT_TIMESTAMP,
            last_scanned_ts = excluded.last_scanned_ts;
        """, (key, host, platform, status, status_code, details, items_found, time.time()))


def get_all_scanner_statuses(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scanner_status ORDER BY host DESC, platform ASC")
        return [dict(r) for r in cur.fetchall()]
