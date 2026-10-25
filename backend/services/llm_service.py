import os
import json
import logging
from datetime import date
from typing import List, Dict, Any, Optional
import httpx

import re

from backend.solver.nlp_date_parser import parse_russian_vacation_text, calculate_slot_days

logger = logging.getLogger("llm_service")

PHONE_REGEX = re.compile(r"(?<!\d)(?:\+7|8|7)[\s\.\-]*\(?\d{3}\)?(?:[\s\.\-]*\d){7}(?!\d)")
EMAIL_REGEX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def sanitize_prompt_pii(text: str) -> str:
    """
    Strips phone numbers and email addresses to protect employee PII (152-ФЗ)
    before sending prompts to external LLMs.
    """
    if not text:
        return ""
    cleaned = PHONE_REGEX.sub("", text)
    cleaned = EMAIL_REGEX.sub("", cleaned)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def _ensure_env_loaded():
    if not os.environ.get("GEMINI_API_KEY"):
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v

_ensure_env_loaded()

# Single lightweight Google AI Studio model (Free Tier)
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
FALLBACK_MODELS = ("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiFlashService:
    """
    Lightweight Google Gemini Flash-Lite Service.
    Used strictly as a fallback date/season extractor when deterministic regex finds no dates.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        _ensure_env_loaded()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self._client = httpx.Client(
            timeout=10.0,
            limits=httpx.Limits(max_keepalive_connections=2, max_connections=5),
        )

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def extract_dates(self, text: str, default_year: int = 2026) -> List[Dict[str, Any]]:
        slots, _ = self.extract_dates_with_context(text, default_year=default_year, remaining_days=36)
        return slots

    def extract_dates_with_context(
        self,
        text: str,
        default_year: int = 2026,
        remaining_days: int = 36,
    ) -> tuple[List[Dict[str, Any]], str]:
        """
        Hybrid Date Extraction:
        1. Instant deterministic local regex/parser (0 ms, 0 RAM/tokens).
        2. Single lightweight Google Gemini Flash-Lite fallback for informal/seasonal queries.
        """
        if not text or not text.strip():
            return [], ""

        # 1. Deterministic First
        fast_slots = parse_russian_vacation_text(text, default_year=default_year)
        if fast_slots:
            return fast_slots, ""

        # Skip LLM for very short inputs or strings without letters
        clean = text.strip()
        if len(clean) < 4 or not any(ch.isalpha() for ch in clean):
            return [], ""

        # 2. Single lightweight Gemini model fallback
        if not self.is_available():
            return [], ""

        try:
            return self._query_gemini_for_dates(clean, default_year=default_year, remaining_days=remaining_days)
        except Exception as e:
            logger.warning(f"Gemini API fallback error: {e}")

        return [], ""

    @staticmethod
    def sanitize_prompt_pii(text: str) -> str:
        return sanitize_prompt_pii(text)

    def _query_gemini_for_dates(self, text: str, default_year: int, remaining_days: int = 36) -> tuple[List[Dict[str, Any]], str]:
        sanitized_text = sanitize_prompt_pii(text)
        prompt = (
            f"Извлеки интервалы отпуска на {default_year} год из пожелания сотрудницы (доступно {remaining_days} дн., "
            f"минимум один блок >=14 дн.). Если указан сезон/погода/курорт, подбери даты в {default_year} г. на {remaining_days} дн. "
            f"Верни только JSON: {{\"slots\":[{{\"start\":\"YYYY-MM-DD\",\"end\":\"YYYY-MM-DD\"}}],\"comment\":\"до 10 слов\"}}. "
            f"Если текст не про отпуск: {{\"slots\":[],\"comment\":\"\"}}.\nТекст: \"{sanitized_text}\""
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 256,
                "responseMimeType": "application/json",
            },
        }

        url = GEMINI_API_URL.format(model=self.model)
        headers = {"x-goog-api-key": self.api_key}
        resp = self._client.post(url, json=payload, headers=headers)
        if resp.status_code == 404:
            for alt_model in FALLBACK_MODELS:
                if alt_model == self.model:
                    continue
                alt_url = GEMINI_API_URL.format(model=alt_model)
                resp = self._client.post(alt_url, json=payload, headers=headers)
                if resp.status_code == 200:
                    self.model = alt_model
                    break
        if resp.status_code != 200:
            logger.warning(f"Gemini model {self.model} returned status {resp.status_code}")
            return [], ""

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return [], ""

        parts = candidates[0].get("content", {}).get("parts", [])
        part_text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
        if part_text.startswith("```"):
            part_text = part_text.strip("`")
            if part_text.startswith("json"):
                part_text = part_text[4:].strip()

        parsed = json.loads(part_text)
        slots_raw = parsed.get("slots", [])
        comment = str(parsed.get("comment", "") or "").strip()

        valid_slots = []
        for item in slots_raw:
            try:
                s_date = date.fromisoformat(item["start"])
                e_date = date.fromisoformat(item["end"])
                if e_date >= s_date:
                    days = calculate_slot_days(s_date, e_date)
                    valid_slots.append({
                        "start": s_date,
                        "end": e_date,
                        "days": days,
                    })
            except Exception:
                continue
        return valid_slots, comment


# Global singleton instance
llm_service = GeminiFlashService()


