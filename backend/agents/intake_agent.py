import re
from datetime import date, datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from backend.models import Employee, VacationSlot, ChatMessage, EmployeeDraft
from backend.solver.nlp_date_parser import (
    parse_russian_vacation_text,
    calculate_slot_days,
    check_option_selection,
    check_confirmation_intent,
    check_reset_intent,
    extract_year_from_text,
)
from backend.agents.solver_agent import SolverAgent
from backend.services.llm_service import llm_service


class IntakeAgent:
    """
    Agent 1: Intake & Negotiation Agent (Garment Factory Edition)
    Supports accumulative date intake, draft state management, and pre-submission confirmation.
    """

    def __init__(self, db: Session):
        self.db = db
        self.solver_agent = SolverAgent(db)

    def _get_or_create_draft(self, employee: Employee) -> EmployeeDraft:
        draft = self.db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == employee.id).first()
        if not draft:
            draft = EmployeeDraft(
                employee_id=employee.id,
                target_year=2026,
                slots=[],
                status="DRAFTING",
            )
            self.db.add(draft)
            self.db.commit()
            self.db.refresh(draft)
        return draft

    def verify_employee_by_phone(self, phone: str, max_user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Tool 1: verify_employee_by_phone
        Validates phone against Employee database and verifies administrator authorization.
        """
        phone_clean = re.sub(r"[^\d+]", "", phone.strip())
        if not phone_clean.startswith("+") and len(phone_clean) == 11 and phone_clean.startswith("8"):
            phone_clean = "+7" + phone_clean[1:]
        elif not phone_clean.startswith("+") and len(phone_clean) == 10:
            phone_clean = "+7" + phone_clean

        employee = (
            self.db.query(Employee)
            .filter(
                (Employee.phone == phone_clean)
                | (Employee.phone == phone)
                | (Employee.phone.like(f"%{phone_clean[-10:]}"))
            )
            .first()
        )

        if not employee:
            return {
                "authenticated": False,
                "message": f"Номер телефона {phone_clean} не найден в базе сотрудников фабрики. Доступ к боту закрыт.",
                "total_days": 36,
                "planned_days": 0,
                "remaining_days": 36,
                "slots": [],
                "draft_slots": [],
            }

        # Check administrator approval for bot access
        bot_access = getattr(employee, "bot_access", "APPROVED") or "APPROVED"
        if bot_access == "PENDING":
            return {
                "authenticated": False,
                "bot_access": "PENDING",
                "message": f"Здравствуйте, {employee.full_name}! Ваш номер ({employee.phone}) ожидает подтверждения администратором бота. Доступ будет открыт после проверки.",
                "total_days": employee.total_vacation_days or 36,
                "planned_days": 0,
                "remaining_days": employee.total_vacation_days or 36,
                "slots": [],
                "draft_slots": [],
            }
        elif bot_access == "BLOCKED":
            return {
                "authenticated": False,
                "bot_access": "BLOCKED",
                "message": f"Доступ к боту для номера {employee.phone} приостановлен администратором.",
                "total_days": employee.total_vacation_days or 36,
                "planned_days": 0,
                "remaining_days": employee.total_vacation_days or 36,
                "slots": [],
                "draft_slots": [],
            }

        if max_user_id and employee.max_user_id != max_user_id:
            self.db.query(Employee).filter(
                Employee.max_user_id == max_user_id,
                Employee.id != employee.id,
            ).update({"max_user_id": None})
            employee.max_user_id = max_user_id
            self.db.commit()

        slots = (
            self.db.query(VacationSlot)
            .filter(VacationSlot.employee_id == employee.id)
            .order_by(VacationSlot.start_date.asc())
            .all()
        )
        planned_days = sum(s.days_count for s in slots)
        remaining_days = max(0, (employee.total_vacation_days or 36) - planned_days)

        draft = self._get_or_create_draft(employee)

        slot_dicts = [
            {
                "id": s.id,
                "start": s.start_date.isoformat(),
                "end": s.end_date.isoformat(),
                "days": s.days_count,
                "is_primary": s.is_primary_block,
                "status": s.status,
                "conflict_reason": s.conflict_reason,
            }
            for s in slots
        ]

        first_name = self._extract_first_name(employee.full_name)
        return {
            "authenticated": True,
            "employee_id": employee.id,
            "name": employee.full_name,
            "role": employee.role,
            "department": employee.department.name if employee.department else "Швейный цех",
            "shift": employee.shift,
            "region": employee.region,
            "total_days": employee.total_vacation_days or 36,
            "planned_days": planned_days,
            "remaining_days": remaining_days,
            "slots": slot_dicts,
            "draft_slots": draft.slots or [],
            "message": f"Здравствуйте, {first_name}! Рады приветствовать вас в сервисе планирования отпусков.",
        }

    @staticmethod
    def _extract_first_name(full_name: str) -> str:
        if not full_name:
            return "коллега"
        parts = full_name.strip().split()
        return parts[1] if len(parts) > 1 else parts[0]

    def process_message(
        self,
        employee_id: int,
        message_text: str,
        max_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Processes incoming message from employee in MAX messenger / web simulator.
        Supports accumulative multi-step date accumulation, previewing, and final submission.
        """
        employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            return {
                "sender": "AGENT",
                "text": "Ошибка авторизации: сотрудник не найден.",
                "payload": None,
            }

        first_name = self._extract_first_name(employee.full_name)
        expected_days = employee.total_vacation_days or 36
        draft = self._get_or_create_draft(employee)

        # Save user message to history
        user_msg = ChatMessage(
            employee_id=employee.id,
            sender="USER",
            text=message_text,
            payload=None,
            timestamp=datetime.now(timezone.utc),
        )
        self.db.add(user_msg)
        self.db.commit()

        # Check 152-ФЗ consent dialog on first interaction
        if not getattr(employee, "consent_152fz", False):
            txt_lower = message_text.strip().lower()
            is_consent_yes = any(
                phrase in txt_lower
                for phrase in ["согласна", "согласен", "согласие", "даю согласие", "согласен/на", "✅", "confirm", "accept", "yes"]
            ) and not any(phrase in txt_lower for phrase in ["отказ", "не соглас", "❌"])

            is_consent_no = any(
                phrase in txt_lower
                for phrase in ["отказаться", "отказ", "не согласна", "не согласен", "❌", "decline", "reject", "no"]
            )

            if is_consent_yes:
                employee.consent_152fz = True
                self.db.commit()
                has_dates_or_other = any(
                    m in txt_lower
                    for m in ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр", "202", "с ", "по ", "недел", "дней", "дня"]
                )
                if not has_dates_or_other:
                    response_text = (
                        f"✅ Спасибо, {first_name}! Согласие на обработку персональных данных (152-ФЗ) принято.\n\n"
                        f"📊 Ваша норма отпуска: **{expected_days} дней** ({employee.role}, {employee.shift}).\n"
                        f"• Минимум один неделимый период должен быть от 14 дней.\n\n"
                        f"💡 Напишите желаемые даты отпуска (например, *«с 1 по 14 июля 2026»*)."
                    )
                    return self._reply(employee.id, response_text, {"action": "CONSENT_GRANTED", "draft_slots": draft.slots or []})
            elif is_consent_no:
                response_text = (
                    f"{first_name}, без согласия на обработку персональных данных (152-ФЗ) "
                    f"планирование и согласование графика отпусков невозможно.\n\n"
                    f"Если вы передумаете, нажмите «✅ Согласна» ниже."
                )
                return self._reply(
                    employee.id,
                    response_text,
                    {"action": "CONSENT_REQUEST", "buttons": ["✅ Согласна", "❌ Отказаться"]}
                )
            else:
                response_text = (
                    f"Здравствуйте, {first_name}! 👋\n\n"
                    f"В соответствии с Федеральным законом № 152-ФЗ «О персональных данных» для составления и согласования графика отпусков "
                    f"требуется ваше согласие на обработку персональных данных.\n\n"
                    f"Пожалуйста, подтвердите согласие для продолжения работы:"
                )
                return self._reply(
                    employee.id,
                    response_text,
                    {"action": "CONSENT_REQUEST", "buttons": ["✅ Согласна", "❌ Отказаться"]}
                )

        # Check for Reset Intent
        if check_reset_intent(message_text):
            draft.slots = []
            draft.status = "DRAFTING"
            self.db.commit()

            response_text = (
                f"🔄 {first_name}, черновик графика отпуска очищен.\n\n"
                f"Ваша норма: **{expected_days} дней** ({employee.region}).\n"
                f"Вы можете отправлять периоды по частям или сразу целиком, например:\n"
                f"• *«с 1 по 14 июля 2026»*\n"
                f"• *«с 1 по 22 сентября 2026»*"
            )
            return self._reply(employee.id, response_text, {"action": "DRAFT_RESET", "draft_slots": []})

        # Check for Confirmation Intent when awaiting confirmation
        if draft.status == "AWAITING_CONFIRMATION" and (check_confirmation_intent(message_text) or message_text.strip().upper() == "CONFIRM"):
            slots_to_commit = draft.slots or []
            self.solver_agent.commit_approved_slots(employee.id, slots_to_commit, status="REQUESTED")
            draft.status = "COMMITTED"
            self.db.commit()

            lines = []
            for s in slots_to_commit:
                st = date.fromisoformat(s["start"])
                en = date.fromisoformat(s["end"])
                lines.append(f"• **{st.strftime('%d.%m.%Y')} – {en.strftime('%d.%m.%Y')}** ({s['days']} дн.)")

            response_text = (
                f"🎉 **Заявка официально отправлена руководителю!**\n\n"
                f"{first_name}, ваш график зафиксирован:\n\n"
                + "\n".join(lines)
                + f"\n\nВсего: **{expected_days} дн.** Руководитель цеха увидит заявку в панели управления."
            )
            return self._reply(employee.id, response_text, {"action": "SUBMISSION_CONFIRMED", "slots": slots_to_commit, "draft_slots": []})

        # Check if user is selecting an alternative option (1, 2, 3)
        last_agent_msg = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.employee_id == employee.id, ChatMessage.sender == "AGENT")
            .order_by(ChatMessage.timestamp.desc())
            .first()
        )
        option_idx = check_option_selection(message_text)
        if option_idx and last_agent_msg and last_agent_msg.payload and "suggested_alternatives" in last_agent_msg.payload:
            alternatives = last_agent_msg.payload["suggested_alternatives"]
            selected_alt = next((a for a in alternatives if a.get("option") == option_idx), None)
            if selected_alt:
                draft_slots = []
                for s in selected_alt["slots"]:
                    st = date.fromisoformat(s["start"])
                    en = date.fromisoformat(s["end"])
                    dur = calculate_slot_days(st, en)
                    draft_slots.append({"start": st.isoformat(), "end": en.isoformat(), "days": dur})

                draft.slots = draft_slots
                draft.status = "AWAITING_CONFIRMATION"
                self.db.commit()

                lines = [f"• **{date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')}** ({s['days']} дн.)" for s in draft_slots]
                response_text = (
                    f"👍 Вы выбрали **Вариант {option_idx}**:\n\n"
                    + "\n".join(lines)
                    + f"\n\nВсего дней: **{selected_alt.get('total_days', expected_days)}**.\n"
                    f"Подтвердите отправку руководителю на утверждение или сбросьте черновик."
                )
                return self._reply(
                    employee.id,
                    response_text,
                    {
                        "action": "AWAITING_CONFIRMATION",
                        "draft_slots": draft_slots,
                        "show_confirm_buttons": True,
                    }
                )

        # Check for Greeting or Status query
        clean_text = message_text.lower().strip()
        if not clean_text or clean_text in [
            "привет", "здравствуйте", "добрый день", "статус", "помощь",
            "start", "/start", "старт", "/старт", "меню", "запустить", "запуск", "/help", "help", "начать"
        ]:
            current_slots = draft.slots or [] if draft.status != "COMMITTED" else []
            accum_days = sum(s.get("days", 0) for s in current_slots)
            rem_days = max(0, expected_days - accum_days)
            is_ready_to_confirm = (draft.status == "AWAITING_CONFIRMATION" and accum_days == expected_days)

            draft_summary = ""
            if current_slots:
                status_hint = (
                    f"\n✅ *Набрано {accum_days} из {expected_days} дн. Подтвердите отправку или напишите «Сброс».*"
                    if is_ready_to_confirm
                    else f"\n*Набрано {accum_days} из {expected_days} дн. (осталось {rem_days} дн.)*"
                )
                draft_summary = "\n\n📝 **Текущий черновик:**\n" + "\n".join(
                    [f"• {date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')} ({s.get('days')} дн.)" for s in current_slots]
                ) + status_hint

            response_text = (
                f"Здравствуйте, {first_name}! 👋\n\n"
                f"Я ассистент по планированию отпусков фабрики.\n"
                f"📊 Ваша норма: **{expected_days} дн.** ({employee.role}, {employee.shift}).\n"
                f"• Минимум один неделимый блок — от 14 дней.\n\n"
                f"💡 Напишите желаемые даты (можно частями), например:\n"
                f"• *«с 1 по 14 июля 2026»*\n"
                f"• *«с 1 по 22 сентября 2026»*{draft_summary}"
            )
            return self._reply(
                employee.id,
                response_text,
                {
                    "action": "AWAITING_CONFIRMATION" if is_ready_to_confirm else "GREETING",
                    "draft_slots": current_slots,
                    "show_confirm_buttons": is_ready_to_confirm,
                },
            )

        # Hybrid NLP Parse Vacation Dates (Deterministic Fast + Single Gemini Flash-Lite Fallback)
        detected_year = extract_year_from_text(message_text, draft.target_year or 2026)

        if draft.status in ("COMMITTED", "AWAITING_CONFIRMATION"):
            current_slots = []
            draft.status = "DRAFTING"
        else:
            current_slots = list(draft.slots or [])

        already_drafted_days = sum(s.get("days", 0) for s in current_slots)
        rem_before = max(0, expected_days - already_drafted_days)

        parsed_slots, llm_comment = llm_service.extract_dates_with_context(
            message_text,
            default_year=detected_year,
            remaining_days=rem_before if rem_before > 0 else expected_days,
        )

        if not parsed_slots:
            response_text = (
                f"{first_name}, не удалось распознать даты отпуска. 🤔\n\n"
                f"Пришлите период в удобном формате, например:\n"
                f"• *«с 1 по 14 июля 2026»*\n"
                f"• *«с 10 июня на 14 дней»*\n"
                f"• *«в бархатный сезон»*\n\n"
                f"Или напишите *«Сброс»*, чтобы очистить черновик."
            )
            return self._reply(employee.id, response_text, {"action": "PARSE_ERROR", "draft_slots": current_slots})

        # Sort and deduplicate newly parsed slots
        unique_parsed: List[Dict[str, Any]] = []
        for p_slot in parsed_slots:
            dur = calculate_slot_days(p_slot["start"], p_slot["end"])
            if not any(u["start"] == p_slot["start"] and u["end"] == p_slot["end"] for u in unique_parsed):
                unique_parsed.append({"start": p_slot["start"], "end": p_slot["end"], "days": dur})

        new_batch_days = sum(u["days"] for u in unique_parsed)

        # If employee sent a complete schedule (e.g. 36 days) in one message while having an incomplete draft,
        # replace the incomplete draft cleanly instead of causing an artificial OVER_LIMIT error.
        if current_slots and new_batch_days == expected_days:
            current_slots = []

        # Check for self-overlap among the new slots or with existing draft slots
        temp_slots = list(current_slots)
        for u in unique_parsed:
            u_st, u_en = u["start"], u["end"]
            u_st_iso, u_en_iso = u_st.isoformat(), u_en.isoformat()
            if any(s["start"] == u_st_iso and s["end"] == u_en_iso for s in temp_slots):
                continue

            overlap_slot = None
            for s in temp_slots:
                s_st = date.fromisoformat(s["start"])
                s_en = date.fromisoformat(s["end"])
                if max(u_st, s_st) <= min(u_en, s_en):
                    overlap_slot = (s_st, s_en)
                    break

            if overlap_slot:
                ov_st, ov_en = overlap_slot
                response_text = (
                    f"⚠️ {first_name}, период **{u_st.strftime('%d.%m.%Y')} – {u_en.strftime('%d.%m.%Y')}** "
                    f"накладывается на уже выбранный вами период **{ov_st.strftime('%d.%m.%Y')} – {ov_en.strftime('%d.%m.%Y')}**.\n\n"
                    f"Пожалуйста, укажите непересекающиеся даты или напишите *«Сброс»*."
                )
                return self._reply(employee.id, response_text, {"action": "PARSE_ERROR", "draft_slots": current_slots})

            temp_slots.append({
                "start": u_st_iso,
                "end": u_en_iso,
                "days": u["days"],
            })

        current_slots = temp_slots
        draft.target_year = detected_year
        draft.slots = current_slots
        accum_days = sum(s["days"] for s in current_slots)
        rem_days = expected_days - accum_days
        comment_prefix = f"💡 {llm_comment}\n\n" if llm_comment else ""

        # Case 1: Incomplete accumulation (accum_days < expected_days)
        if accum_days < expected_days:
            lines = [f"• {date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')} ({s['days']} дн.)" for s in current_slots]
            has_14 = any(s["days"] >= 14 for s in current_slots)
            hint_14 = "" if has_14 else " (один из блоков должен быть не менее 14 дней)"

            response_text = (
                f"{comment_prefix}✍️ **Записано в черновик:**\n\n"
                + "\n".join(lines)
                + f"\n\n📊 Набрано: **{accum_days} из {expected_days} дн.** (осталось распределить: **{rem_days} дн.**{hint_14}).\n"
                f"👉 Отправьте следующий период отпуска."
            )
            draft.status = "DRAFTING"
            self.db.commit()
            return self._reply(employee.id, response_text, {"action": "DRAFT_UPDATED", "draft_slots": current_slots, "accum_days": accum_days, "rem_days": rem_days})

        # Case 2: Over limit (accum_days > expected_days)
        if accum_days > expected_days:
            lines = [f"• {date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')} ({s['days']} дн.)" for s in current_slots]
            response_text = (
                f"⚠️ {first_name}, превышен лимит дней отпуска!\n\n"
                + "\n".join(lines)
                + f"\n\nСумма: **{accum_days} дн.** при вашей норме **{expected_days} дн.** (превышение на {accum_days - expected_days} дн.).\n"
                f"Напишите *«Сброс»*, чтобы очистить черновик и ввести корректные даты."
            )
            self.db.commit()
            return self._reply(employee.id, response_text, {"action": "OVER_LIMIT", "draft_slots": current_slots})

        # Case 3: Exactly accumulated (accum_days == expected_days) -> Run Solver & Present Preview!
        slots_to_test = [{"start": date.fromisoformat(s["start"]), "end": date.fromisoformat(s["end"])} for s in current_slots]
        opt_result = self.solver_agent.run_vacation_optimizer(
            employee_id=employee.id,
            requested_slots=slots_to_test,
            window_search_days=45,
        )

        status = opt_result.get("status")

        if status == "VALID":
            draft.status = "AWAITING_CONFIRMATION"
            self.db.commit()

            lines = [f"• **{date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')}** ({s['days']} дн.)" for s in current_slots]
            response_text = (
                f"{comment_prefix}📋 **Проверьте ваш итоговый график перед отправкой:**\n\n"
                + "\n".join(lines)
                + f"\n\n"
                f"✨ Итог: **{expected_days} дн.** (блок 14+ соблюден, пересечений с коллегами и ограничений нет ✅)\n\n"
                f"**Подтвердите отправку руководителю:**"
            )
            return self._reply(
                employee.id,
                response_text,
                {
                    "action": "AWAITING_CONFIRMATION",
                    "draft_slots": current_slots,
                    "show_confirm_buttons": True,
                }
            )

        elif status == "INVALID_TK":
            violations_text = "\n".join([f"⚠️ {v}" for v in opt_result.get("violations", [])])
            response_text = (
                f"{first_name}, не соблюдены требования ТК РФ:\n\n"
                f"{violations_text}\n\n"
                f"Напишите *«Сброс»* или отправьте другие даты."
            )
            return self._reply(employee.id, response_text, {"action": "INVALID_TK", "violations": opt_result.get("violations"), "draft_slots": current_slots})

        elif status == "CONFLICT":
            alternatives = opt_result.get("suggested_alternatives", [])
            violations = opt_result.get("violations", [])
            alt_blocks = []
            for a in alternatives:
                slots_str = ", ".join(
                    [f"{date.fromisoformat(s['start']).strftime('%d.%m')} – {date.fromisoformat(s['end']).strftime('%d.%m')}" for s in a["slots"]]
                )
                emoji_num = ["1️⃣", "2️⃣", "3️⃣"][a["option"] - 1] if a["option"] <= 3 else f"{a['option']}."
                alt_blocks.append(f"{emoji_num} **{slots_str}**\n   *{a['reason']}*")

            requested_str = ", ".join([f"{date.fromisoformat(s['start']).strftime('%d.%m')} – {date.fromisoformat(s['end']).strftime('%d.%m')}" for s in current_slots])
            if violations:
                reasons_str = "\n".join(f"⚠️ {v}" for v in violations)
            else:
                reasons_str = f"⚠️ Период **{requested_str}** пересекается с графиком смены или цеха."

            if alt_blocks:
                options_text = "\n\n".join(alt_blocks)
                response_text = (
                    f"{first_name}, выбранные даты (**{requested_str}**) недоступны:\n"
                    f"{reasons_str}\n\n"
                    f"Свободные варианты без пересечений:\n\n"
                    f"{options_text}\n\n"
                    f"**Выберите вариант (1, 2, 3), пришлите другие даты или напишите «Сброс».**"
                )
            else:
                response_text = (
                    f"{first_name}, выбранные даты (**{requested_str}**) недоступны:\n"
                    f"{reasons_str}\n\n"
                    f"Пожалуйста, пришлите другие даты или напишите *«Сброс»*."
                )

            return self._reply(
                employee.id,
                response_text,
                {
                    "action": "OFFER_ALTERNATIVES",
                    "conflicts": violations,
                    "suggested_alternatives": alternatives,
                    "draft_slots": current_slots,
                }
            )

        return self._reply(employee.id, "Произошла ошибка при обработке запроса. Напишите «Сброс» для повторной попытки.", None)

    def _reply(self, employee_id: int, text: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        agent_msg = ChatMessage(
            employee_id=employee_id,
            sender="AGENT",
            text=text,
            payload=payload,
            timestamp=datetime.now(timezone.utc),
        )
        self.db.add(agent_msg)
        self.db.commit()
        return {
            "sender": "AGENT",
            "text": text,
            "payload": payload,
        }
