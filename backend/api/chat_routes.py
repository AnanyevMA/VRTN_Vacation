import re
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Employee, ChatMessage, BotAdmin
from backend.schemas import ChatMessageIn, ChatMessageOut, MaxWebhookPayload
from backend.agents.intake_agent import IntakeAgent
from backend.services.max_bot_client import max_bot_client

router = APIRouter(prefix="/api/chat", tags=["MAX Messenger Chat & Webhook"])


@router.post("/message")
def send_chat_message(msg_in: ChatMessageIn, db: Session = Depends(get_db)):
    """
    Sends message from employee to Intake & Negotiation Agent.
    Executes NLP, solver checks, empathy, and alternative generation.
    """
    agent = IntakeAgent(db)
    response = agent.process_message(
        employee_id=msg_in.employee_id,
        message_text=msg_in.message,
        max_user_id=msg_in.max_user_id,
    )
    return response


@router.get("/history/{employee_id}", response_model=List[ChatMessageOut])
def get_chat_history(employee_id: int, db: Session = Depends(get_db)):
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.employee_id == employee_id)
        .order_by(ChatMessage.timestamp.asc())
        .all()
    )
    return messages


@router.post("/reset/{employee_id}")
def reset_chat_history(employee_id: int, db: Session = Depends(get_db)):
    db.query(ChatMessage).filter(ChatMessage.employee_id == employee_id).delete()
    db.commit()
    return {"message": "История диалога очищена"}


@router.post("/webhook")
async def max_messenger_webhook(payload: MaxWebhookPayload, db: Session = Depends(get_db)):
    """
    Webhook endpoint for corporate MAX messenger bot integration.
    Receives incoming message or callback button click from MAX.
    Enforces administrator confirmation of employee phone numbers.
    """
    agent = IntakeAgent(db)

    # 1. Check if user is sending phone contact / auth
    if payload.phone:
        phone_raw = payload.phone.strip()
        phone_clean = re.sub(r"[^\d+]", "", phone_raw)
        if not phone_clean.startswith("+") and len(phone_clean) == 11 and phone_clean.startswith("8"):
            phone_clean = "+7" + phone_clean[1:]
        elif not phone_clean.startswith("+") and len(phone_clean) == 10:
            phone_clean = "+7" + phone_clean

        # Check if phone belongs to a Bot Administrator
        admin = db.query(BotAdmin).filter((BotAdmin.phone == phone_clean) | (BotAdmin.phone == phone_raw)).first()
        if admin:
            admin.max_user_id = payload.user_id
            db.commit()
            reply_text = f"👑 Здравствуйте, {admin.full_name}! Вы авторизованы как администратор бота ({admin.role_title}).\n\nКоманды:\n• Напишите «/admin» для просмотра статуса и ожидающих номеров."
            max_bot_client.send_message(payload.user_id, reply_text)
            return {"recipient_user_id": payload.user_id, "text": reply_text}

        # Check employee in database
        auth_res = agent.verify_employee_by_phone(phone=payload.phone, max_user_id=payload.user_id)
        if not auth_res["authenticated"]:
            msg = auth_res["message"]
            max_bot_client.send_message(payload.user_id, msg)
            return {"recipient_user_id": payload.user_id, "text": msg}

        reply_text = auth_res["message"] + f"\n\nВаш доступный баланс: {auth_res['total_days']} дней.\nНапишите желаемые даты отпуска."
        max_bot_client.send_message(payload.user_id, reply_text)
        return {"recipient_user_id": payload.user_id, "text": reply_text}

    # 2. Lookup if sender is a Bot Administrator
    admin = db.query(BotAdmin).filter(BotAdmin.max_user_id == payload.user_id).first()
    if admin:
        text_clean = (payload.text or "").strip().lower()
        if text_clean in ["/admin", "админ", "статус"]:
            total_emps = db.query(Employee).count()
            pending_emps = db.query(Employee).filter(Employee.bot_access == "PENDING").all()
            p_text = f"• Ожидают подтверждения номера: {len(pending_emps)}\n"
            if pending_emps:
                p_text += "\n".join(f"  - {e.full_name} ({e.phone})" for e in pending_emps[:5])
            reply = f"👑 **Панель администратора MAX:**\nВсего сотрудников в базе: {total_emps}\n{p_text}\n\nВы можете подтверждать номера в веб-дашборде фабрики."
            max_bot_client.send_message(payload.user_id, reply)
            return {"recipient_user_id": payload.user_id, "text": reply}

    # 3. Lookup employee by max_user_id
    employee = db.query(Employee).filter(Employee.max_user_id == payload.user_id).first()
    if not employee:
        reply_text = "Здравствуйте! Для доступа к боту подтвердите ваш номер телефона через кнопку ниже."
        max_bot_client.send_contact_request(payload.user_id, reply_text)
        return {
            "recipient_user_id": payload.user_id,
            "text": reply_text,
            "request_contact_button": True,
        }

    # 4. Enforce administrator confirmation
    bot_access = getattr(employee, "bot_access", "APPROVED") or "APPROVED"
    if bot_access == "PENDING":
        reply = f"⏳ {employee.full_name}, ваш номер телефона ожидает подтверждения администратором бота. Пожалуйста, обратитесь к руководству цеха."
        max_bot_client.send_message(payload.user_id, reply)
        return {"recipient_user_id": payload.user_id, "text": reply}
    elif bot_access == "BLOCKED":
        reply = f"🚫 Доступ к боту для номера {employee.phone} заблокирован администратором."
        max_bot_client.send_message(payload.user_id, reply)
        return {"recipient_user_id": payload.user_id, "text": reply}

    # 5. Process message text or callback
    text_to_process = payload.callback_data if payload.callback_data else (payload.text or "")
    response = agent.process_message(employee.id, text_to_process, payload.user_id)

    # Format reply buttons for MAX
    inline_buttons = []
    p = response.get("payload", {}) or {}
    if p.get("action") == "OFFER_ALTERNATIVES":
        alts = p.get("suggested_alternatives", [])
        for a in alts:
            inline_buttons.append({
                "text": f"Выбрать Вариант {a['option']}",
                "callback_data": f"вариант {a['option']}",
            })
    elif p.get("show_confirm_buttons"):
        inline_buttons.append({"text": "✅ Подтвердить отправку", "callback_data": "подтверждаю"})
        inline_buttons.append({"text": "🔄 Сброс", "callback_data": "сброс"})

    max_bot_client.send_message(payload.user_id, response["text"], inline_buttons if inline_buttons else None)

    return {
        "recipient_user_id": payload.user_id,
        "text": response["text"],
        "inline_keyboard": inline_buttons if inline_buttons else None,
    }
