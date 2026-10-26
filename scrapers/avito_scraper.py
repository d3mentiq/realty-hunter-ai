"""Avito.ru rental listings scraper via mobile endpoint."""

from __future__ import annotations

import json
import re
from typing import Any
from curl_cffi import requests

from config import get_config

MOBILE_HEADERS = {
    "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "ru",
}


def fetch_avito_catalog(
    min_price: int | None = None,
    max_price: int | None = None,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    cfg = get_config()
    min_p = min_price if min_price is not None else cfg.min_price
    max_p = max_price if max_price is not None else (cfg.max_price or 999999)
    city_slug = cfg.avito_city_slug or "moskva"

    offers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        session = requests.Session()
        session.headers.update(MOBILE_HEADERS)
        url = f"https://m.avito.ru/{city_slug}/kvartiry/sdam/na_dlitelnyy_srok/1-komnatnye?pmin={min_p}&pmax={max_p}&p={page}"
        try:
            r = session.get(url, impersonate="safari15_5", timeout=15)
            if r.status_code != 200:
                break

            html = r.text
            marker = '__initialData__ = "'
            idx = html.find(marker)
            if idx == -1:
                break

            start_pos = idx + len(marker)
            decoder = json.JSONDecoder()
            parsed_json_str, _ = decoder.raw_decode(html[start_pos:])
            data = json.loads(parsed_json_str)

            all_items = data.get("search", {}).get("allItems", {})
            if not all_items:
                break

            for item_id, item_data in all_items.items():
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                val = item_data.get("value", {})
                title = val.get("title", "1-к. квартира")
                uri = val.get("uri", "")
                full_url = "https://www.avito.ru" + uri.split("?")[0] if uri.startswith("/") else uri

                price_obj = val.get("price", {})
                price_str = price_obj.get("current", "") if isinstance(price_obj, dict) else str(price_obj)
                m_price = re.search(r"(\d+[\s\xa0]\d+|\d+)", price_str)
                price = int(m_price.group(1).replace("\xa0", "").replace(" ", "")) if m_price else 0

                if price < min_p or (max_p and price > max_p):
                    continue

                geo = val.get("geo", {})
                geo_refs = geo.get("geoReferences", []) if isinstance(geo, dict) else []
                addr_parts = [g.get("content", "") for g in geo_refs if isinstance(g, dict)]
                addr = ", ".join(addr_parts) if addr_parts else cfg.city

                m_floor = re.search(r"(\d+)/(\d+)\s*эт", title)
                floor_num = int(m_floor.group(1)) if m_floor else 2
                floor_tot = int(m_floor.group(2)) if m_floor else 9
                floor_str = f"{floor_num}/{floor_tot}"

                photos: list[str] = []
                images = val.get("images", [])
                for img in images:
                    if isinstance(img, dict):
                        u = img.get("640x480") or img.get("1280x960") or img.get("url")
                        if u:
                            photos.append(u)

                desc = val.get("description", "") or ""

                offers.append({
                    "id": f"avito_{item_id}",
                    "source": "Авито",
                    "url": full_url,
                    "title": title,
                    "addr": addr,
                    "price": price,
                    "floor_num": floor_num,
                    "floor_total": floor_tot,
                    "floor_str": floor_str,
                    "photos": photos,
                    "desc": desc,
                })
        except Exception:
            break

    return offers


def fetch_avito_single(url: str) -> dict[str, Any] | None:
    session = requests.Session()
    session.headers.update(MOBILE_HEADERS)
    m_id = re.search(r"_(\d+)$", url.rstrip("/"))
    item_id = m_id.group(1) if m_id else ""
    try:
        r = session.get(url, impersonate="safari15_5", timeout=15)
        if r.status_code != 200:
            return None
        html = r.text
        m_title = re.search(r"<title>(.*?)</title>", html, re.I)
        title = m_title.group(1) if m_title else "Квартира на Авито"

        m_price = re.search(r'"price":\s*(\d+)', html)
        price = int(m_price.group(1)) if m_price else 0

        photos = list(set(re.findall(r"https://\d+\.img\.avito\.st/image/\d+/[^\"']+\.jpg", html)))

        return {
            "id": f"avito_{item_id}" if item_id else f"avito_{hash(url)}",
            "source": "Авито",
            "url": url,
            "title": title,
            "addr": "",
            "price": price,
            "photos": photos,
            "desc": "",
        }
    except Exception:
        return None
