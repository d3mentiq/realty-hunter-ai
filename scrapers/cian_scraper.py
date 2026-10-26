"""Cian.ru rental listings scraper via curl_cffi."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any
from curl_cffi import requests

from config import get_config

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_cian_flats(
    min_price: int | None = None,
    max_price: int | None = None,
    max_pages: int = 5,
    text_query: str | None = None,
) -> list[dict[str, Any]]:
    cfg = get_config()
    min_p = min_price if min_price is not None else cfg.min_price
    max_p = max_price if max_price is not None else (cfg.max_price or 999999)
    region_id = cfg.cian_region_id or "1"

    offers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    query_param = f"&text={urllib.parse.quote(text_query)}" if text_query else ""

    for page in range(1, max_pages + 1):
        url = (
            f"https://cian.ru/cat.php?deal_type=rent&engine_version=2&offer_type=flat"
            f"&room1=1&maxprice={max_p}&minprice={min_p}&region={region_id}&p={page}{query_param}"
        )
        try:
            res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=15)
            if res.status_code != 200:
                break

            html = res.text
            cards = re.findall(r'<article[^>]*data-name="CardComponent"[^>]*>(.*?)</article>', html, re.DOTALL)
            if not cards:
                break

            for c in cards:
                m_link = re.search(r'href="(https://[^"]*cian\.ru/rent/flat/(\d+)/?[^"]*)"', c)
                if not m_link:
                    continue
                flat_url = m_link.group(1).split("?")[0]
                flat_id = f"cian_{m_link.group(2)}"
                if flat_id in seen_ids:
                    continue
                seen_ids.add(flat_id)

                m_price = re.search(r"(\d+[\s\xa0]\d+)\s*₽", c)
                price = int(m_price.group(1).replace("\xa0", "").replace(" ", "")) if m_price else 0
                if price < min_p or (max_p and price > max_p):
                    continue

                m_title = re.search(r'data-name="GeneralInfoTitle"[^>]*>(.*?)</div>', c)
                title = re.sub(r"<[^>]+>", " ", m_title.group(1)).strip() if m_title else "1-комн. квартира"

                m_addr = re.findall(r'<a[^>]*data-name="GeoLabel"[^>]*>(.*?)</a>', c)
                addr = ", ".join(m_addr) if m_addr else cfg.city

                m_floor = re.search(r"(\d+)/(\d+)\s*эт", c) or re.search(r"(\d+)/(\d+)\s*эт", title)
                floor_num = int(m_floor.group(1)) if m_floor else 2
                floor_tot = int(m_floor.group(2)) if m_floor else 9
                floor_str = f"{floor_num}/{floor_tot}"

                photos = list(set(re.findall(r"https://images\.cdn-cian\.ru/images/[^\"'\s]+\.jpg", c)))

                m_desc = re.search(r'data-name="Description"[^>]*>(.*?)</div>', c)
                desc = re.sub(r"<[^>]+>", " ", m_desc.group(1)).strip() if m_desc else ""

                comm_pct = 0
                m_comm = re.search(r"комисси[яи]\s*(\d+)%", c, re.I)
                if m_comm:
                    comm_pct = int(m_comm.group(1))

                offers.append({
                    "id": flat_id,
                    "source": "Циан",
                    "url": flat_url,
                    "title": title,
                    "addr": addr,
                    "price": price,
                    "floor_num": floor_num,
                    "floor_total": floor_tot,
                    "floor_str": floor_str,
                    "photos": photos,
                    "desc": desc,
                    "commission": comm_pct,
                })
        except Exception:
            break

    return offers
