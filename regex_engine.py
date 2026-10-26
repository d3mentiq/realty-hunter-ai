"""Text parsing and heuristic rule engine for rental property listings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from config import Config

DEFAULT_DROP_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"(?i)(только\s+девушк|для\s+одной\s+девушк|студентк[еи]|женщин[еы]|без\s+мужчин|парней\s+не\s+сда|молодым\s+людям\s+не\s+беспокоить)",
        "Ограничение по полу: только для девушек/женщин",
    ),
    (
        r"(?i)(строго\s+для\s+одного|только\s+один\s+жилец|для\s+одного\s+человек|строго\s+1\s+человек)",
        "Ограничение по количеству: только для 1 жильца",
    ),
    (
        r"(?i)(койко-мест|комнат[аы]\s+в\s+квартир|в\s+соседней\s+комнат|подселени|доля\s+в|гостинк[аи]\s+без\s+удобств|душ\s+на\s+этаж)",
        "Не отдельное жилье: комната, доля или подселение",
    ),
    (
        r"(?i)(под\s+бьюти|кабинет\s+массаж|маникюр|под\s+офис|под\s+склад|юридический\s+адрес|коммерческ)",
        "Коммерческое назначение / услуги",
    ),
    (
        r"(?i)(без\s+ремонта|черновая\s+отделк|требуется\s+ремонт|под\s+чистовую|в\s+счет\s+аренды\s+доделаете|после\s+пожара|голые\s+стены)",
        "Непригодное состояние: черновая отделка или требуется ремонт",
    ),
    (
        r"(?i)(посуточн|на\s+сесси|на\s+1-2\s+месяц|до\s+лета|до\s+мая|до\s+июня|на\s+время\s+продажи|квартира\s+выставлена\s+на\s+продажу)",
        "Временная аренда / выселение к лету",
    ),
)


@dataclass(frozen=True)
class FilterRules:
    min_price: int = 0
    max_price: int | None = None
    max_commission: int | None = None
    max_move_in_cost: int | None = None
    disallowed_floors: tuple[int, ...] = (1,)
    disallowed_keywords: tuple[str, ...] = ()
    target_districts: tuple[str, ...] = ()
    drop_patterns: tuple[tuple[str, str], ...] = DEFAULT_DROP_PATTERNS
    utility_estimate_full: int = 4500
    utility_estimate_counters: int = 2000

    @classmethod
    def from_config(cls, cfg: Config) -> FilterRules:
        return cls(
            min_price=cfg.min_price,
            max_price=cfg.max_price,
            max_commission=cfg.max_commission,
            max_move_in_cost=cfg.max_move_in_cost,
            disallowed_floors=cfg.disallowed_floors,
            disallowed_keywords=cfg.disallowed_keywords,
            target_districts=cfg.target_districts,
        )


def extract_bills(desc: str, est_full: int, est_counters: int) -> tuple[int, str]:
    m_num = re.search(
        r"(?i)(?:другие\s+жку|прочие\s+жку|коммуналк[аи]|квитанци[яи]|плюс\s+ку|квартплат[аы])\s*[:=-]?\s*(\d{3,5})",
        desc,
    )
    if m_num:
        val = int(m_num.group(1))
        return val, f"+ ЖКУ по квитанции {val} ₽"

    if re.search(
        r"(?i)(вся\s+квитанци|полная\s+квитанци|квитанции\s+полностью|все\s+квитки|коммунальные\s+платежи\s+на\s+арендатор|плюс\s+отоплени)",
        desc,
    ):
        return est_full, f"+ вся квитанция (~{est_full} ₽)"

    if re.search(r"(?i)(вс[её]\s+включено|ку\s+включен[ыо]|без\s+доплат)", desc):
        return 0, "КУ включены в стоимость"

    if re.search(r"(?i)(только\s+счетчик|по\s+счетчикам|свет\s+и\s+вода)", desc):
        return est_counters, f"+ счетчики (~{est_counters} ₽)"

    return 0, "только счетчики"


def extract_deposit(desc: str, raw_deposit: int = 0) -> tuple[int, int]:
    deposit_val = raw_deposit
    if not deposit_val:
        m_dep = re.search(r"(?i)(?:залог|депозит|обеспечительный\s+платеж)\s*[-—:=]?\s*(\d+[\s\xa0]\d*|\d+)", desc)
        if m_dep:
            deposit_val = int(m_dep.group(1).replace("\xa0", "").replace(" ", ""))
        elif re.search(r"(?i)(без\s+залога)", desc):
            deposit_val = 0

    is_indivisible = bool(
        re.search(r"(?i)(не\s+делим|не\s+снижа|без\s+разбив|не\s+разбива|строго\s+полн|сразу\s+полн)", desc)
    )
    dep_first_month = deposit_val if is_indivisible else (deposit_val // 2)
    return deposit_val, dep_first_month


def extract_commission(desc: str, base_price: int, raw_comm: int | None = None, author_type: str = "") -> tuple[int, int]:
    if author_type == "OWNER" or raw_comm == 0:
        return 0, 0
    if raw_comm is not None:
        pct = int(raw_comm)
    else:
        m_comm = re.search(r"(?i)(?:комисси[яи]|риелторск(?:ие)?)\s*[-—:=]?\s*(\d{1,3})\s*%", desc)
        if m_comm:
            pct = int(m_comm.group(1))
        elif re.search(r"(?i)(без\s+комиссии)", desc):
            pct = 0
        else:
            pct = 0
    comm_rub = int(base_price * (pct / 100.0))
    return pct, comm_rub


def analyze_text(offer: dict[str, Any], rules: FilterRules) -> dict[str, Any]:
    addr = str(offer.get("addr", "")).lower()
    desc = str(offer.get("desc", ""))
    desc_lower = desc.lower()
    full_text = f"{addr} {desc_lower}"
    base_price = int(offer.get("price", 0))
    floor = int(offer.get("floor_num", 2))

    def _fail(reason: str) -> dict[str, Any]:
        return {
            "passed": False,
            "drop_reason": reason,
            "total_price": 0,
            "deposit": 0,
            "commission": 0,
            "move_in_cost": 0,
            "bills_info": "",
        }

    # 1. Floor filter
    if floor in rules.disallowed_floors:
        return _fail(f"Неподходящий этаж: {floor}")

    # 2. Target districts (if configured)
    if rules.target_districts:
        has_match = any(d.lower() in full_text for d in rules.target_districts)
        if not has_match:
            return _fail("Вне целевых районов")

    # 3. Disallowed keywords
    for kw in rules.disallowed_keywords:
        if kw in full_text:
            return _fail(f"Запрещенное ключевое слово: {kw}")

    # 4. Stop patterns
    for pattern, reason in rules.drop_patterns:
        if re.search(pattern, desc):
            return _fail(reason)

    # 5. Price limits
    if rules.min_price and base_price < rules.min_price:
        return _fail(f"Цена {base_price} ₽ ниже минимальной ({rules.min_price} ₽)")
    if rules.max_price and base_price > rules.max_price:
        return _fail(f"Цена {base_price} ₽ выше максимальной ({rules.max_price} ₽)")

    # 6. Financial estimates
    extra_jku, bills_info = extract_bills(desc, rules.utility_estimate_full, rules.utility_estimate_counters)
    total_price = base_price + extra_jku

    dep_total, dep_first_month = extract_deposit(desc, int(offer.get("deposit", 0) or 0))
    comm_pct, comm_rub = extract_commission(
        desc, base_price, offer.get("commission"), offer.get("author_type", "")
    )

    if rules.max_commission is not None and comm_rub > rules.max_commission:
        return _fail(f"Комиссия {comm_rub} ₽ превышает лимит {rules.max_commission} ₽")

    move_in_cost = base_price + dep_first_month + comm_rub
    if rules.max_move_in_cost is not None and move_in_cost > rules.max_move_in_cost:
        return _fail(f"Первый взнос {move_in_cost} ₽ превышает лимит {rules.max_move_in_cost} ₽")

    return {
        "passed": True,
        "drop_reason": "",
        "total_price": total_price,
        "deposit": dep_total,
        "commission": comm_rub,
        "move_in_cost": move_in_cost,
        "bills_info": bills_info,
    }
