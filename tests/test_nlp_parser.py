from datetime import date
from backend.solver.nlp_date_parser import (
    parse_russian_vacation_text,
    calculate_slot_days,
    check_option_selection,
    check_confirmation_intent,
    check_reset_intent,
    extract_year_from_text,
)


def test_parse_russian_month_names_multi_year():
    text = "Хочу уйти с 1 по 14 июля 2027 и еще с 1 по 22 сентября 2027"
    slots = parse_russian_vacation_text(text, default_year=2026)
    assert len(slots) == 2
    assert slots[0]["start"] == date(2027, 7, 1)
    assert slots[0]["end"] == date(2027, 7, 14)
    assert slots[1]["start"] == date(2027, 9, 1)
    assert slots[1]["end"] == date(2027, 9, 22)

    d1 = calculate_slot_days(slots[0]["start"], slots[0]["end"])
    d2 = calculate_slot_days(slots[1]["start"], slots[1]["end"])
    assert d1 == 14
    assert d2 == 22
    assert d1 + d2 == 36


def test_extract_year():
    assert extract_year_from_text("отпуск в 2027 году", default_year=2026) == 2027
    assert extract_year_from_text("хочу в августе", default_year=2026) == 2026


def test_confirmation_and_reset_intents():
    assert check_confirmation_intent("да, подтверждаю") is True
    assert check_confirmation_intent("отправь руководителю") is True
    assert check_confirmation_intent("ок") is True
    assert check_reset_intent("сброс") is True
    assert check_reset_intent("начать заново") is True


def test_option_selection_does_not_match_dates():
    assert check_option_selection("1") == 1
    assert check_option_selection("Вариант 2") == 2
    assert check_option_selection("выбираю вариант 3") == 3
    # Must NOT match date strings containing digits 1, 2, or 3
    assert check_option_selection("Хочу с 1 по 14 августа 2026") is None
    assert check_option_selection("с 2 по 15 сентября 2026") is None
    assert check_option_selection("с 3 октября на 14 дней") is None

