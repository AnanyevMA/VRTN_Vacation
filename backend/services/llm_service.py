import os
import json
import logging
from datetime import date
from typing import List, Dict, Any, Optional
import httpx

from backend.solver.nlp_date_parser import parse_russian_vacation_text, calculate_slot_days

logger = logging.getLogger("llm_service")

# Google AI Studio Gemini Flash Free Tier
DEFAULT_MODEL = "gemini-1.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiFlashService:
    """
    Google Gemini Flash Free Tier Service
    Provides zero-cost intelligent date extraction and polite conversational empathy for garment factory workers.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def extract_dates(self, text: str, default_year: int = 2026) -> List[Dict[str, Any]]:
        """
        Hybrid Date Extraction:
        1. First try instant deterministic local regex/parser (0 ms, 100% precision).
        2. If regex finds nothing and Gemini API key is configured, query Gemini Flash Free Tier.
        """
        # 1. Deterministic First
        fast_slots = parse_russian_vacation_text(text, default_year=default_year)
        if fast_slots:
            return fast_slots

        # 2. Gemini Flash Fallback (for complex/conversational sentences)
        if not self.is_available():
            return []

        try:
            gemini_slots = self._query_gemini_for_dates(text, default_year=default_year)
            if gemini_slots:
                return gemini_slots
        except Exception as e:
            logger.warning(f"Gemini API fallback error: {e}")

        return []

    def _query_gemini_for_dates(self, text: str, default_year: int) -> List[Dict[str, Any]]:
        url = GEMINI_API_URL.format(model=DEFAULT_MODEL) + f"?key={self.api_key}"
        prompt = f"""
Ты — помощник кадровой службы швейной фабрики.
Текущий год по умолчанию: {default_year}.
Проанализируй текст сотрудницы швейного цеха и извлеки желаемые интервалы дат отпуска.
Верни ТОЛЬКО валидный JSON следующего формата:
{{"slots": [{{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}]}}

Текст сотрудницы: "{text}"
Если даты или временные рамки не указаны, верни {{"slots": []}}.
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }

        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning(f"Gemini API status {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return []

            part_text = candidates[0]["content"]["parts"][0]["text"]
            parsed = json.loads(part_text)
            slots_raw = parsed.get("slots", [])

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
            return valid_slots

    def explain_conflict_politely(
        self,
        employee_name: str,
        role: str,
        conflict_reason: str,
        alternatives: List[Dict[str, Any]],
    ) -> str:
        """Generates a warm, supportive explanation in Russian if Gemini is configured."""
        if not self.is_available():
            return ""

        url = GEMINI_API_URL.format(model=DEFAULT_MODEL) + f"?key={self.api_key}"
        alt_text = "\n".join(f"- Вариант {a.get('option', i+1)}: {a.get('text', '')}" for i, a in enumerate(alternatives))
        prompt = f"""
Напиши короткий, вежливый и поддерживающий ответ от лица виртуального помощника швейной фабрики для сотрудницы {employee_name} ({role}).
Ситуация: запрошенные даты отпуска совпали с ограничением производства: "{conflict_reason}".
Предложенные альтернативные свободные периоды:
{alt_text}

Правила ответа:
1. Обращайся тепло и уважительно по имени.
2. Просто и по-человечески объясни, почему на эти даты цех не может отпустить двоих швей одновременно.
3. Предложи выбрать одну из свободных дат.
4. Текст должен быть кратким (до 4-5 предложений).
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4}
        }

        try:
            with httpx.Client(timeout=6.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        return candidates[0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            logger.warning(f"Gemini politeness explanation error: {e}")
        return ""


# Global singleton instance
llm_service = GeminiFlashService()
