"""Visual evaluation of apartment photos using Google Gemini Vision API."""

from __future__ import annotations

import base64
import io
import json
import urllib.request
from typing import Any
from PIL import Image

from config import get_config


def download_and_compress(url: str, max_dim: int = 600, quality: int = 75) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        im = Image.open(io.BytesIO(raw))
        im.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return None


def call_gemini_vision(parts: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = get_config()
    if not cfg.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    model = cfg.gemini_model or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={cfg.gemini_api_key}"

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    raw_text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
    return json.loads(raw_text.strip())


def judge_apartment_photos(photo_urls: list[str], offer_info: dict[str, Any] | None = None) -> dict[str, Any]:
    default_result: dict[str, Any] = {
        "score": 5,
        "category": "compromise",
        "summary": "Фотографии не были оценены",
        "why_it_fits": [],
        "why_fails": [],
        "appliances": {},
    }

    if not photo_urls:
        default_result.update({"score": 3, "category": "trash", "summary": "В объявлении отсутствуют фотографии"})
        return default_result

    # Compress up to 6 representative photos
    b64_photos: list[str] = []
    selected = photo_urls[:6] if len(photo_urls) <= 8 else (photo_urls[:3] + photo_urls[3:8:2] + [photo_urls[-1]])[:6]
    for u in selected:
        b64 = download_and_compress(u)
        if b64:
            b64_photos.append(b64)

    if not b64_photos:
        default_result.update({"score": 3, "category": "trash", "summary": "Не удалось загрузить фотографии"})
        return default_result

    desc_snippet = ""
    if offer_info:
        desc_snippet = str(offer_info.get("desc", ""))[:500]

    prompt = (
        "Ты — строгий визуальный оценщик квартир в аренду. Оцени фотографии жилья.\n"
        "Ответь СТРОГО JSON-объектом следующей структуры:\n"
        "{\n"
        '  "score": 1-10,\n'
        '  "category": "cool" | "compromise" | "trash",\n'
        '  "repair_quality": "современный" | "косметический" | "устаревший" | "требует ремонта",\n'
        '  "has_sleeping_place": true | false,\n'
        '  "appliances": {\n'
        '    "fridge": true | false,\n'
        '    "washing_machine": true | false,\n'
        '    "stove": true | false,\n'
        '    "microwave": true | false\n'
        "  },\n"
        '  "why_it_fits": ["краткий плюс 1", "краткий плюс 2"],\n'
        '  "why_fails": ["краткий минус 1", "краткий минус 2"],\n'
        '  "summary": "краткий объективный вердикт на 1 предложение"\n'
        "}\n\n"
        "Критерии оценки:\n"
        "- cool: свежий чистый ремонт, нормальная мебель, базовая техника в порядке.\n"
        "- compromise: простой косметический ремонт, пригодное состояние без критических дефектов.\n"
        "- trash (score <= 4): запущенное состояние, разбитый ремонт, ковры на стенах, дряхлая мебель, грязь или отсутствие спального места при сдаче с мебелью."
    )

    if desc_snippet:
        prompt += f"\nОписание из объявления: {desc_snippet}"

    parts: list[dict[str, Any]] = [{"text": prompt}]
    for b64 in b64_photos:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    try:
        data = call_gemini_vision(parts)
        score = int(data.get("score", 5))
        cat = str(data.get("category", "compromise")).lower()
        if cat not in ("cool", "compromise", "trash"):
            cat = "cool" if score >= 8 else ("compromise" if score >= 5 else "trash")

        return {
            "score": score,
            "category": cat,
            "summary": data.get("summary", ""),
            "why_it_fits": data.get("why_it_fits", []),
            "why_fails": data.get("why_fails", []),
            "appliances": data.get("appliances", {}),
            "repair_quality": data.get("repair_quality", ""),
        }
    except Exception as e:
        default_result["summary"] = f"Оценка ИИ пропущена: {e}"
        return default_result
