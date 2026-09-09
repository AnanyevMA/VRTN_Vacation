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
            )
            .first()
        )

        if not employee:
            return {
                "authenticated": False,
                "message": "Номер телефона не найден в базе сотрудников фабрики. Доступ к боту закрыт.",
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

        first_name = employee.full_name.split()[1] if len(employee.full_name.split()) > 1 else employee.full_name
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

        first_name = employee.full_name.split()[1] if len(employee.full_name.split()) > 1 else employee.full_name
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

        # Check for Reset Intent
        if check_reset_intent(message_text):
            draft.slots = []
            draft.status = "DRAFTING"
            self.db.commit()

            response_text = (
                f"🔄 {first_name}, черновик графика отпуска очищен.\n\n"
                f"Ваша норма: **{expected_days} дней** (Республика Хакасия).\n"
                f"Вы можете отправлять периоды накопительно, например:\n"
                f"1️⃣ *«с 1 по 14 июля 2027»*\n"
                f"2️⃣ *«с 1 по 22 сентября 2027»*"
            )
            return self._reply(employee.id, response_text, {"action": "DRAFT_RESET"})

        # Check for Confirmation Intent when awaiting confirmation
        if draft.status == "AWAITING_CONFIRMATION" and (check_confirmation_intent(message_text) or message_text.strip().upper() == "CONFIRM"):
            # Commit draft to vacation_slots
            slots_to_commit = draft.slots
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
                f"Уважаемый(-ая) {first_name}, ваш график зафиксирован:\n\n"
                + "\n".join(lines)
                + f"\n\nВсего: **{expected_days} календарных дней**.\n"
                f"Руководитель цеха и кадровая служба увидят заявку в дашборде. "
                f"Если потребуется скорректировать график, просто напишите мне."
            )
            return self._reply(employee.id, response_text, {"action": "SUBMISSION_CONFIRMED", "slots": slots_to_commit})

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
                # Update draft with selected alternative slots
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
        if clean_text in ["привет", "здравствуйте", "добрый день", "статус", "помощь", "start", "/start", "меню"]:
            current_slots = draft.slots or []
            accum_days = sum(s.get("days", 0) for s in current_slots)
            rem_days = max(0, expected_days - accum_days)

            draft_summary = ""
            if current_slots:
                draft_summary = "\n\n📝 **Текущий черновик:**\n" + "\n".join(
                    [f"• {date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')} ({s.get('days')} дн.)" for s in current_slots]
                ) + f"\n*Набрано {accum_days} из {expected_days} дн. (осталось {rem_days} дн.)*"

            response_text = (
                f"Здравствуйте, {first_name}! 👋\n\n"
                f"Я ваш цифровой ассистент по планированию отпусков швейного производства.\n\n"
                f"📊 **Ваш баланс:**\n"
                f"• Должность: **{employee.role}** ({employee.shift})\n"
                f"• Доступно: **{expected_days} календарных дней** ({employee.region})\n"
                f"• Главное правило: минимум один неделимый блок $\\ge 14$ дней.\n\n"
                f"💡 **Вы можете присылать даты по частям!** Например:\n"
                f"1. *«с 1 по 14 июля 2027»*\n"
                f"2. *«и с 1 по 22 сентября 2027»*{draft_summary}"
            )
            return self._reply(employee.id, response_text, {"action": "GREETING", "draft_slots": current_slots})

        # Hybrid NLP Parse Vacation Dates (Deterministic Fast + Gemini Flash Fallback)
        detected_year = extract_year_from_text(message_text, draft.target_year or 2026)
        parsed_slots = llm_service.extract_dates(message_text, default_year=detected_year)

        if not parsed_slots:
            response_text = (
                f"{first_name}, я не смог распознать даты в вашем сообщении. 🤔\n\n"
                f"Вы можете прислать дату в любом удобном виде:\n"
                f"• *«с 1 по 14 июля 2027»*\n"
                f"• *«01.07.2027 - 14.07.2027»*\n"
                f"• *«с 10 августа на 14 дней»*\n\n"
                f"Или напишите *«Сброс»*, чтобы начать заново."
            )
            return self._reply(employee.id, response_text, {"action": "PARSE_ERROR"})

        # Accumulate slots into draft
        current_slots = list(draft.slots or [])
        draft.target_year = detected_year

        for p_slot in parsed_slots:
            dur = calculate_slot_days(p_slot["start"], p_slot["end"])
            # Prevent exact duplicate additions
            if not any(s["start"] == p_slot["start"].isoformat() and s["end"] == p_slot["end"].isoformat() for s in current_slots):
                current_slots.append({
                    "start": p_slot["start"].isoformat(),
                    "end": p_slot["end"].isoformat(),
                    "days": dur,
                })

        draft.slots = current_slots
        accum_days = sum(s["days"] for s in current_slots)
        rem_days = expected_days - accum_days

        # Case 1: Incomplete accumulation (accum_days < expected_days)
        if accum_days < expected_days:
            lines = [f"• {date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')} ({s['days']} дн.)" for s in current_slots]
            has_14 = any(s["days"] >= 14 for s in current_slots)
            hint_14 = "" if has_14 else " (не забудьте, что один из блоков должен быть от 14 дней!)"

            response_text = (
                f"✍️ **Период записан в черновик:**\n\n"
                + "\n".join(lines)
                + f"\n\n📊 **Набрано: {accum_days} из {expected_days} дней.**\n"
                f"Осталось распределить: **{rem_days} дн.**{hint_14}\n\n"
                f"👉 Отправьте следующий период отпуска."
            )
            draft.status = "DRAFTING"
            self.db.commit()
            return self._reply(employee.id, response_text, {"action": "DRAFT_UPDATED", "draft_slots": current_slots, "accum_days": accum_days, "rem_days": rem_days})

        # Case 2: Over limit (accum_days > expected_days)
        if accum_days > expected_days:
            lines = [f"• {date.fromisoformat(s['start']).strftime('%d.%m.%Y')} – {date.fromisoformat(s['end']).strftime('%d.%m.%Y')} ({s['days']} дн.)" for s in current_slots]
            response_text = (
                f"⚠️ {first_name}, общая сумма дней в черновике превысила вашу норму!\n\n"
                + "\n".join(lines)
                + f"\n\nСумма: **{accum_days} дн.** (ваша норма: **{expected_days} дн.**, превышение на {accum_days - expected_days} дн.).\n"
                f"Напишите *«Сброс»* или отправьте скорректированные даты."
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
                f"📋 **Проверьте ваш итоговый график перед отправкой руководителю:**\n\n"
                + "\n".join(lines)
                + f"\n\n"
                f"✨ **Итог проверки:**\n"
                f"• Всего дней: **{expected_days}** (норма соблюдена)\n"
                f"• Неделимый блок $\\ge 14$ дней: **Да**\n"
                f"• Пересечения по смене/цеху: **Отсутствуют (все свободно)** ✅\n\n"
                f"**Если вас все устраивает, подтвердите отправку:**"
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
                f"{first_name}, обратите внимание на требования:\n\n"
                f"{violations_text}\n\n"
                f"Напишите *«Сброс»* или отправьте корректные периоды."
            )
            return self._reply(employee.id, response_text, {"action": "INVALID_TK", "violations": opt_result.get("violations")})

        elif status == "CONFLICT":
            alternatives = opt_result.get("suggested_alternatives", [])
            alt_blocks = []
            for a in alternatives:
                slots_str = ", ".join(
                    [f"{date.fromisoformat(s['start']).strftime('%d.%m')} – {date.fromisoformat(s['end']).strftime('%d.%m')}" for s in a["slots"]]
                )
                emoji_num = ["1️⃣", "2️⃣", "3️⃣"][a["option"] - 1] if a["option"] <= 3 else f"{a['option']}."
                alt_blocks.append(f"{emoji_num} **{slots_str}**\n   *{a['reason']}*")

            options_text = "\n\n".join(alt_blocks)
            requested_str = ", ".join([f"{date.fromisoformat(s['start']).strftime('%d.%m')} – {date.fromisoformat(s['end']).strftime('%d.%m')}" for s in current_slots])

            response_text = (
                f"{first_name}, выбранный период (**{requested_str}**) пересекается с графиком коллег по должности «{employee.role}» "
                f"или пиковым сезоном цеха.\n\n"
                f"Я подобрал для вас 3 отличных свободных варианта:\n\n"
                f"{options_text}\n\n"
                f"**Выберите вариант 1, 2, 3 или напишите «Сброс», чтобы ввести другие даты.**"
            )
            return self._reply(
                employee.id,
                response_text,
                {
                    "action": "OFFER_ALTERNATIVES",
                    "conflicts": opt_result.get("violations"),
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
