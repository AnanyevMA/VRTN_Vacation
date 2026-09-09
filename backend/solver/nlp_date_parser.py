import re
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple

MONTHS_MAP = {
    "январ": 1, "янв": 1,
    "феврал": 2, "фев": 2,
    "март": 3, "мар": 3,
    "апрел": 4, "апр": 4,
    "ма": 5, "май": 5, "мая": 5,
    "июн": 6,
    "июл": 7,
    "август": 8, "авг": 8,
    "сентябр": 9, "сен": 9, "сент": 9,
    "октябр": 10, "окт": 10,
    "ноябр": 11, "ноя": 11,
    "декабр": 12, "дек": 12,
}


def _get_month_number(month_str: str) -> Optional[int]:
    month_clean = month_str.lower().strip().rstrip(".")
    for prefix, num in sorted(MONTHS_MAP.items(), key=lambda x: -len(x[0])):
        if month_clean.startswith(prefix):
            return num
    return None


def extract_year_from_text(text: str, default_year: int = 2026) -> int:
    """Extracts explicit 4-digit year like 2026, 2027, 2028 if mentioned."""
    m = re.search(r"\b(202[5-9]|203[0-5])\b", text)
    if m:
        return int(m.group(1))
    return default_year


def parse_russian_vacation_text(text: str, default_year: int = 2026) -> List[Dict[str, date]]:
    """
    Parses natural language Russian text containing one or more vacation intervals.
    Automatically detects explicit years (e.g. 2027).
    """
    if not text:
        return []

    target_year = extract_year_from_text(text, default_year)
    text_lower = text.lower().replace("ё", "е")
    found_slots: List[Dict[str, date]] = []

    # Pattern 1: ISO format YYYY-MM-DD - YYYY-MM-DD
    iso_pattern = re.compile(
        r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*(?:по|-|до|—|–)\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})"
    )
    for m in iso_pattern.finditer(text_lower):
        y1, m1, d1, y2, m2, d2 = map(int, m.groups())
        try:
            st = date(y1, m1, d1)
            en = date(y2, m2, d2)
            if en >= st:
                found_slots.append({"start": st, "end": en})
        except ValueError:
            pass

    # Pattern 2: DD.MM[.YYYY] - DD.MM[.YYYY]
    dot_pattern = re.compile(
        r"(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?\s*(?:по|-|до|—|–)\s*(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?"
    )
    for m in dot_pattern.finditer(text_lower):
        d1, m1, y1_str, d2, m2, y2_str = m.groups()
        y1 = int(y1_str) if y1_str else (int(y2_str) if y2_str else target_year)
        if y1 < 100:
            y1 += 2000
        y2 = int(y2_str) if y2_str else y1
        if y2 < 100:
            y2 += 2000
        try:
            st = date(y1, int(m1), int(d1))
            en = date(y2, int(m2), int(d2))
            if en >= st and not any(s["start"] == st and s["end"] == en for s in found_slots):
                found_slots.append({"start": st, "end": en})
        except ValueError:
            pass

    # Pattern 3: "с D1 [месяца1] по D2 месяца2 [YYYY]" / "D1-D2 месяца [YYYY]"
    month_names_regex = r"(?:январ[яье]?|феврал[яье]?|март[а]?|апрел[яье]?|ма[яйе]?|июн[яье]?|июл[яье]?|август[а]?|сентябр[яье]?|октябр[яье]?|ноябр[яье]?|декабр[яье]?)"

    # Format 3a: "с 1 июля по 14 июля 2027"
    regex_3a = re.compile(
        rf"(?:с\s+)?(\d{{1,2}})\s+({month_names_regex})\s*(?:года|\s*г\.)?\s*(?:по|до|-|—|–)\s*(\d{{1,2}})\s+({month_names_regex})(?:\s*(\d{{4}}))?",
        re.IGNORECASE
    )
    for m in regex_3a.finditer(text_lower):
        d1, mon1_str, d2, mon2_str, yr_str = m.groups()
        m1 = _get_month_number(mon1_str)
        m2 = _get_month_number(mon2_str)
        yr = int(yr_str) if yr_str else target_year
        if m1 and m2:
            try:
                st = date(yr, m1, int(d1))
                en = date(yr, m2, int(d2))
                if en >= st and not any(s["start"] == st and s["end"] == en for s in found_slots):
                    found_slots.append({"start": st, "end": en})
            except ValueError:
                pass

    # Format 3b: "с 1 по 14 июля 2027" or "1-14 июля"
    regex_3b = re.compile(
        rf"(?:с\s+)?(\d{{1,2}})\s*(?:по|до|-|—|–)\s*(\d{{1,2}})\s+({month_names_regex})(?:\s*(\d{{4}}))?",
        re.IGNORECASE
    )
    for m in regex_3b.finditer(text_lower):
        d1, d2, mon_str, yr_str = m.groups()
        m_num = _get_month_number(mon_str)
        yr = int(yr_str) if yr_str else target_year
        if m_num:
            try:
                st = date(yr, m_num, int(d1))
                en = date(yr, m_num, int(d2))
                if en >= st and not any(s["start"] == st and s["end"] == en for s in found_slots):
                    found_slots.append({"start": st, "end": en})
            except ValueError:
                pass

    # Format 3c: "с D месяца на N дней" e.g. "с 10 июня на 14 дней 2027"
    regex_3c = re.compile(
        rf"с\s+(\d{{1,2}})\s+({month_names_regex})(?:\s*(\d{{4}}))?\s+на\s+(\d{{1,2}})\s+(?:дн|ден|сут)",
        re.IGNORECASE
    )
    for m in regex_3c.finditer(text_lower):
        d1, mon_str, yr_str, duration = m.groups()
        m_num = _get_month_number(mon_str)
        yr = int(yr_str) if yr_str else target_year
        dur = int(duration)
        if m_num and dur > 0:
            try:
                st = date(yr, m_num, int(d1))
                en = st + timedelta(days=dur - 1)
                if not any(s["start"] == st and s["end"] == en for s in found_slots):
                    found_slots.append({"start": st, "end": en})
            except ValueError:
                pass

    found_slots.sort(key=lambda s: s["start"])
    return found_slots


def calculate_slot_days(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 0
    return (end_date - start_date).days + 1


def check_option_selection(text: str) -> Optional[int]:
    text_clean = text.lower().strip()
    if text_clean in ["1", "1️⃣", "первый", "вариант 1", "вариант 1️⃣", "1 вариант", "выбираю 1", "давай 1", "номер 1"]:
        return 1
    if text_clean in ["2", "2️⃣", "второй", "вариант 2", "вариант 2️⃣", "2 вариант", "выбираю 2", "давай 2", "номер 2"]:
        return 2
    if text_clean in ["3", "3️⃣", "третий", "вариант 3", "вариант 3️⃣", "3 вариант", "выбираю 3", "давай 3", "номер 3"]:
        return 3

    m = re.search(r"(?:вариант|опци[яю]|номер)?\s*([1-3])\b", text_clean)
    if m:
        return int(m.group(1))
    return None


def check_confirmation_intent(text: str) -> bool:
    """Returns True if text expresses confirmation to submit draft to manager."""
    text_clean = text.lower().strip()
    keywords = [
        "подтверждаю", "подтвердить", "да", "отправь", "отправить", "отправляй",
        "согласен", "согласна", "все верно", "всё верно", "подходит", "готово",
        "отправить руководителю", "да, отправить", "confirm", "submit", "ок", "ok"
    ]
    return any(k in text_clean for k in keywords)


def check_reset_intent(text: str) -> bool:
    """Returns True if text requests clearing or resetting the draft."""
    text_clean = text.lower().strip()
    keywords = [
        "сброс", "сбросить", "начать заново", "очистить", "заново", "отмена",
        "переделать", "reset", "clear", "сбросить черновик"
    ]
    return any(k in text_clean for k in keywords)
