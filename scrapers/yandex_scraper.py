"""Yandex Realty scraper via public HTML initial state."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from config import get_config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_yandex_flats(
    min_price: int | None = None,
    max_price: int | None = None,
    max_pages: int = 5,
    text_query: str | None = None,
) -> list[dict[str, Any]]:
    cfg = get_config()
    min_p = min_price if min_price is not None else cfg.min_price
    max_p = max_price if max_price is not None else (cfg.max_price or 999999)
    city_slug = cfg.yandex_city_slug or "moskva"

    offers: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        query_param = f"&text={urllib.parse.quote(text_query)}" if text_query else ""
        url = (
            f"https://realty.ya.ru/{city_slug}/snyat/kvartira/odnokomnatnaya/?"
            f"priceMax={max_p}&priceMin={min_p}&page={page}{query_param}"
        )
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            m = re.search(r"INITIAL_STATE\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
            if not m:
                break

            data = json.loads(m.group(1))
            ents = data.get("search", {}).get("offers", {}).get("entities", [])
            if not ents:
                break

            for e in ents:
                oid = str(e.get("offerId", ""))
                if not oid or oid in seen:
                    continue
                seen.add(oid)

                loc = e.get("location", {})
                addr = loc.get("address", cfg.city)

                fl_num = e.get("floorsOffered", [0])[0] if e.get("floorsOffered") else 2
                fl_tot = e.get("floorsTotal", 0)
                floor_str = f"{fl_num}/{fl_tot}"

                price = int(e.get("price", {}).get("value", 0))
                author_type = e.get("author", {}).get("category", "UNKNOWN")

                comm = e.get("agentFee")
                if comm is None:
                    comm = e.get("commissionFee", 0)
                comm = int(comm) if comm is not None else 0

                dep = e.get("rentPledge") or 0
                desc = e.get("description", "") or ""

                raw_imgs = (
                    e.get("fullImages", [])
                    or e.get("origImages", [])
                    or e.get("mainImages", [])
                    or e.get("large1242Images", [])
                )
                photos: list[str] = []
                for img_val in raw_imgs:
                    if isinstance(img_val, str):
                        u = f"https:{img_val}" if img_val.startswith("//") else img_val
                        photos.append(u)
                    elif isinstance(img_val, dict):
                        u = img_val.get("orig") or img_val.get("full") or img_val.get("large")
                        if u:
                            u_str = f"https:{u}" if u.startswith("//") else u
                            photos.append(u_str)

                offers.append({
                    "id": f"yandex_{oid}",
                    "source": "Яндекс.Недвижимость",
                    "url": f"https://realty.yandex.ru/offer/{oid}/",
                    "addr": addr,
                    "price": price,
                    "floor_num": fl_num,
                    "floor_total": fl_tot,
                    "floor_str": floor_str,
                    "author_type": author_type,
                    "commission": comm,
                    "deposit": dep,
                    "desc": desc,
                    "photos": photos,
                })
        except Exception:
            break

    return offers
