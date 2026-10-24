import json
import logging
import os
import re
import secrets
import time
from typing import List, Optional, Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.database import get_db
from backend.models import Employee, ChatMessage, BotAdmin, EmployeeDraft
from backend.schemas import ChatMessageIn, ChatMessageOut, MaxWebhookPayload
from backend.agents.intake_agent import IntakeAgent
from backend.services.max_bot_client import max_bot_client

logger = logging.getLogger(__name__)

# --- In-Memory Sliding Window Rate Limiter ---
_rate_limit_history: Dict[str, List[float]] = {}
RATE_LIMIT_WINDOW = 60.0  # seconds
RATE_LIMIT_MAX_REQUESTS = 10


def check_rate_limit(key: str) -> bool:
    """
    In-memory sliding window rate limiter: maximum 10 requests per minute per key.
    Returns True if allowed, False if rate limited.
    """
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    history = _rate_limit_history.get(key, [])
    history = [t for t in history if t > window_start]
    if len(history) >= RATE_LIMIT_MAX_REQUESTS:
        _rate_limit_history[key] = history
        return False
    history.append(now)
    _rate_limit_history[key] = history

    if len(_rate_limit_history) > 500:
        stale_keys = [k for k, v in _rate_limit_history.items() if not v or v[-1] <= window_start]
        for sk in stale_keys:
            _rate_limit_history.pop(sk, None)

    return True


def clear_rate_limits():
    """Helper for testing to reset rate limit states."""
    _rate_limit_history.clear()


def extract_client_ip(request: Request) -> str:
    """Extracts client IP, supporting reverse proxy headers (X-Forwarded-For, X-Real-IP)."""
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


_extract_client_ip = extract_client_ip


def mask_phone(phone: Optional[str]) -> str:
    """Masks phone number in logs to prevent PII leaks (e.g. +7 913 *** ** 01)."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 11:
        return f"+7 {digits[1:4]} *** ** {digits[-2:]}"
    elif len(digits) == 10:
        return f"+7 {digits[:3]} *** ** {digits[-2:]}"
    elif len(digits) >= 4:
        return f"{phone[:2]}***{phone[-2:]}"
    return "***"


def normalize_phone_number(phone_raw: str) -> str:
    """Normalizes Russian phone number to standard E.164 (+7XXXXXXXXXX)."""
    if not phone_raw:
        return ""
    clean = re.sub(r"[^\d+]", "", str(phone_raw).strip())
    if not clean.startswith("+") and len(clean) == 11 and clean.startswith("8"):
        clean = "+7" + clean[1:]
    elif not clean.startswith("+") and len(clean) == 11 and clean.startswith("7"):
        clean = "+" + clean
    elif not clean.startswith("+") and len(clean) == 10 and clean.startswith("9"):
        clean = "+7" + clean
    return clean


def extract_phone_and_name_from_vcard(vcf: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts phone number and full name from vCard formatted string."""
    phone = None
    name = None

    tel_match = re.search(r"TEL[^\r\n:]*:([^\r\n]+)", vcf, re.IGNORECASE)
    if tel_match:
        phone = normalize_phone_number(tel_match.group(1))
    else:
        any_phone = re.search(r"(\+?[78][0-9\s\-\(\)]{9,15}[0-9])", vcf)
        if any_phone:
            phone = normalize_phone_number(any_phone.group(1))

    fn_match = re.search(r"FN[^\r\n:]*:([^\r\n]+)", vcf, re.IGNORECASE)
    if fn_match:
        name = fn_match.group(1).strip()

    return phone, name


def extract_contact_from_webhook(raw_body: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Exhaustively searches for phone number and contact user_id across all MAX / TamTam / Telegram payload conventions.
    Returns (phone, contact_user_id).
    """
    if not isinstance(raw_body, dict):
        return None, None

    if raw_body.get("phone"):
        return normalize_phone_number(str(raw_body["phone"])), None
    if raw_body.get("phone_number"):
        return normalize_phone_number(str(raw_body["phone_number"])), None

    # Check contact objects
    for c_obj in [
        raw_body.get("contact"),
        raw_body.get("message", {}).get("contact") if isinstance(raw_body.get("message"), dict) else None,
        raw_body.get("message", {}).get("body", {}).get("contact") if isinstance(raw_body.get("message"), dict) and isinstance(raw_body["message"].get("body"), dict) else None,
    ]:
        if isinstance(c_obj, dict):
            c_uid = str(c_obj.get("user_id") or c_obj.get("userId") or c_obj.get("id") or "").strip() or None
            if c_obj.get("phone_number"):
                return normalize_phone_number(str(c_obj["phone_number"])), c_uid
            if c_obj.get("phone"):
                return normalize_phone_number(str(c_obj["phone"])), c_uid
            if c_obj.get("vcf_info"):
                p, _ = extract_phone_and_name_from_vcard(str(c_obj["vcf_info"]))
                if p:
                    return p, c_uid

    # Gather attachments
    attachments_list = []
    if isinstance(raw_body.get("message"), dict):
        msg = raw_body["message"]
        if isinstance(msg.get("body"), dict) and isinstance(msg["body"].get("attachments"), list):
            attachments_list.extend(msg["body"]["attachments"])
        if isinstance(msg.get("attachments"), list):
            attachments_list.extend(msg["attachments"])

    if isinstance(raw_body.get("attachments"), list):
        attachments_list.extend(raw_body["attachments"])

    if isinstance(raw_body.get("body"), dict) and isinstance(raw_body["body"].get("attachments"), list):
        attachments_list.extend(raw_body["body"]["attachments"])

    for att in attachments_list:
        if not isinstance(att, dict):
            continue
        att_type = (att.get("type") or "").lower()
        if att_type in ("contact", "vcard", "phone"):
            att_uid = str(att.get("user_id") or att.get("userId") or "").strip() or None
            payload_att = att.get("payload")
            if isinstance(payload_att, dict):
                p_uid = str(payload_att.get("user_id") or payload_att.get("userId") or payload_att.get("id") or "").strip() or None
                if isinstance(payload_att.get("tam_info"), dict):
                    tam = payload_att["tam_info"]
                    tam_uid = str(tam.get("user_id") or tam.get("userId") or tam.get("id") or "").strip() or None
                    if tam.get("phone") or tam.get("phone_number"):
                        return normalize_phone_number(str(tam.get("phone") or tam.get("phone_number"))), tam_uid or p_uid or att_uid
                if payload_att.get("phone"):
                    return normalize_phone_number(str(payload_att["phone"])), p_uid or att_uid
                if payload_att.get("phone_number"):
                    return normalize_phone_number(str(payload_att["phone_number"])), p_uid or att_uid
                vcf = payload_att.get("vcf_info") or payload_att.get("vcfInfo") or payload_att.get("vcard")
                if isinstance(vcf, str):
                    p, _ = extract_phone_and_name_from_vcard(vcf)
                    if p:
                        return p, p_uid or att_uid
            elif isinstance(payload_att, str):
                if "VCARD" in payload_att:
                    p, _ = extract_phone_and_name_from_vcard(payload_att)
                    if p:
                        return p, att_uid
                else:
                    try:
                        p_json = json.loads(payload_att)
                        if isinstance(p_json, dict):
                            p_uid = str(p_json.get("user_id") or p_json.get("userId") or p_json.get("id") or "").strip() or None
                            if p_json.get("phone") or p_json.get("phone_number"):
                                return normalize_phone_number(str(p_json.get("phone") or p_json.get("phone_number"))), p_uid or att_uid
                            vcf = p_json.get("vcf_info") or p_json.get("vcfInfo")
                            if isinstance(vcf, str):
                                p, _ = extract_phone_and_name_from_vcard(vcf)
                                if p:
                                    return p, p_uid or att_uid
                    except Exception:
                        pass

            if att.get("vcf_info"):
                p, _ = extract_phone_and_name_from_vcard(str(att["vcf_info"]))
                if p:
                    return p, att_uid
            if att.get("phone"):
                return normalize_phone_number(str(att["phone"])), att_uid

    return None, None


def extract_phone_from_webhook(raw_body: dict) -> Optional[str]:
    phone, _ = extract_contact_from_webhook(raw_body)
    return phone


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
    if not messages:
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if employee:
            first_name = IntakeAgent._extract_first_name(employee.full_name)
            expected_days = employee.total_vacation_days or 36
            draft = db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == employee.id).first()
            current_slots = (draft.slots or []) if (draft and draft.status != "COMMITTED") else []
            welcome_text = (
                f"Здравствуйте, {first_name}! 👋\n\n"
                f"Я ассистент по планированию отпусков фабрики.\n"
                f"📊 Ваша норма: **{expected_days} дн.** ({employee.role}, {employee.shift}).\n"
                f"• Минимум один неделимый блок — от 14 дней.\n\n"
                f"💡 Напишите желаемые даты (можно частями), например:\n"
                f"• *«с 1 по 14 июля 2026»*\n"
                f"• *«с 1 по 22 сентября 2026»*"
            )
            agent = IntakeAgent(db)
            agent._reply(employee.id, welcome_text, {"action": "GREETING", "draft_slots": current_slots})
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
    draft = db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == employee_id).first()
    if draft:
        draft.slots = []
        draft.status = "DRAFTING"
    db.commit()
    return {"message": "История диалога и черновик очищены"}



def extract_chat_id_from_webhook(raw_body: dict) -> Optional[str]:
    """Exhaustively extracts chat_id across TamTam / MAX messenger payload variations."""
    if not isinstance(raw_body, dict):
        return None

    def _clean(cid: Any) -> Optional[str]:
        if cid is None:
            return None
        s = str(cid).strip()
        if not s or s == "0":
            return None
        return s

    # 1. message.recipient.chat_id
    if isinstance(raw_body.get("message"), dict):
        msg = raw_body["message"]
        rec = msg.get("recipient")
        if isinstance(rec, dict):
            c = _clean(rec.get("chat_id")) or _clean(rec.get("chatId"))
            if c:
                return c
        c = _clean(msg.get("chat_id")) or _clean(msg.get("chatId"))
        if c:
            return c

    # 2. callback.message.recipient.chat_id
    if isinstance(raw_body.get("callback"), dict):
        cb = raw_body["callback"]
        if isinstance(cb.get("message"), dict):
            rec = cb["message"].get("recipient")
            if isinstance(rec, dict):
                c = _clean(rec.get("chat_id")) or _clean(rec.get("chatId"))
                if c:
                    return c
            c = _clean(cb["message"].get("chat_id")) or _clean(cb["message"].get("chatId"))
            if c:
                return c
        c = _clean(cb.get("chat_id")) or _clean(cb.get("chatId"))
        if c:
            return c

    # 3. root recipient.chat_id
    if isinstance(raw_body.get("recipient"), dict):
        c = _clean(raw_body["recipient"].get("chat_id")) or _clean(raw_body["recipient"].get("chatId"))
        if c:
            return c

    # 4. root chat_id / chatId
    c = _clean(raw_body.get("chat_id")) or _clean(raw_body.get("chatId"))
    if c:
        return c

    # 5. chat.chat_id / chat.id
    if isinstance(raw_body.get("chat"), dict):
        c = _clean(raw_body["chat"].get("chat_id")) or _clean(raw_body["chat"].get("chatId")) or _clean(raw_body["chat"].get("id"))
        if c:
            return c

    return None


def extract_user_id_from_webhook(raw_body: dict, bot_user_id: Optional[str] = None) -> str:
    """
    Extracts the human user's user_id from incoming webhook payload.
    Filters out the bot's own user_id to prevent loopbacks and self-messaging errors.
    """
    if not isinstance(raw_body, dict):
        return ""

    def _is_valid(uid: Any) -> bool:
        if uid is None:
            return False
        s = str(uid).strip()
        if not s or s == "0":
            return False
        if bot_user_id and s == str(bot_user_id):
            return False
        return True

    # 1. callback.user (button click)
    if isinstance(raw_body.get("callback"), dict):
        cb = raw_body["callback"]
        cb_user = cb.get("user")
        if isinstance(cb_user, dict):
            for k in ("user_id", "userId", "id"):
                if _is_valid(cb_user.get(k)):
                    return str(cb_user[k])
        elif _is_valid(cb_user):
            return str(cb_user)

    # 2. message.sender (message sent by human)
    if isinstance(raw_body.get("message"), dict):
        msg = raw_body["message"]
        sender = msg.get("sender")
        if isinstance(sender, dict):
            if not sender.get("is_bot"):
                for k in ("user_id", "userId", "id", "sender_id"):
                    if _is_valid(sender.get(k)):
                        return str(sender[k])
        elif _is_valid(sender):
            return str(sender)

        # Contact attachment tam_info
        body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        atts = (body.get("attachments") if isinstance(body.get("attachments"), list) else []) + \
               (msg.get("attachments") if isinstance(msg.get("attachments"), list) else [])
        for att in atts:
            if isinstance(att, dict):
                p_att = att.get("payload")
                if isinstance(p_att, dict):
                    tam = p_att.get("tam_info")
                    if isinstance(tam, dict):
                        for k in ("user_id", "userId", "id"):
                            if _is_valid(tam.get(k)):
                                return str(tam[k])

    # 3. root sender
    if isinstance(raw_body.get("sender"), dict):
        s = raw_body["sender"]
        if not s.get("is_bot"):
            for k in ("user_id", "userId", "id"):
                if _is_valid(s.get(k)):
                    return str(s[k])
    elif _is_valid(raw_body.get("sender")):
        return str(raw_body["sender"])

    # 4. root user (e.g. bot_started)
    if isinstance(raw_body.get("user"), dict):
        u = raw_body["user"]
        if not u.get("is_bot"):
            for k in ("user_id", "userId", "id"):
                if _is_valid(u.get(k)):
                    return str(u[k])
    elif _is_valid(raw_body.get("user")):
        return str(raw_body["user"])

    # 5. Direct root user_id only if not bot_user_id
    for k in ("user_id", "userId"):
        if _is_valid(raw_body.get(k)):
            return str(raw_body[k])

    return ""


@router.post("/webhook")
@router.post("/webhook/max")
@router.get("/webhook")
@router.get("/webhook/max")
async def max_messenger_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook endpoint for corporate MAX messenger bot integration.
    Receives incoming message or callback button click from MAX.
    Enforces administrator confirmation of employee phone numbers.
    Supports both flat JSON and nested messenger payloads.
    """
    # 1. WEBHOOK_SECRET Verification
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if webhook_secret:
        token = request.headers.get("X-Max-Bot-Token") or request.query_params.get("token") or ""
        if not token or not secrets.compare_digest(token.encode("utf-8"), webhook_secret.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        raw_body = await request.json()
    except Exception:
        raw_body = {}

    update_type = raw_body.get("update_type") or raw_body.get("event") or ""
    is_test = "testclient" in request.headers.get("user-agent", "").lower()

    bot_id = max_bot_client.get_bot_user_id()
    user_id = extract_user_id_from_webhook(raw_body, bot_user_id=bot_id)
    chat_id = extract_chat_id_from_webhook(raw_body)

    # 2. In-Memory Sliding Window Rate Limiter with Reverse Proxy IP Extraction
    client_ip = _extract_client_ip(request)
    rate_limit_key = user_id if user_id else client_ip
    if not check_rate_limit(rate_limit_key):
        raise HTTPException(
            status_code=429,
            detail="Слишком много запросов. Пожалуйста, подождите минуту."
        )

    callback_id = None
    callback_data = None
    if isinstance(raw_body.get("callback"), dict):
        cb = raw_body["callback"]
        callback_id = cb.get("callback_id")
        callback_data = cb.get("payload")

    text = ""
    if not callback_data:
        if isinstance(raw_body.get("message"), dict):
            body = raw_body["message"].get("body")
            if isinstance(body, dict):
                text = body.get("text") or ""
            elif isinstance(body, str):
                text = body
            if not text:
                text = raw_body["message"].get("text") or ""
        if not text:
            text = raw_body.get("text") or ""
    else:
        text = str(callback_data)

    if not callback_data:
        callback_data = raw_body.get("callback_data") or raw_body.get("payload")

    if callback_id:
        max_bot_client.answer_callback(callback_id)

    phone, contact_user_id = extract_contact_from_webhook(raw_body)

    payload = MaxWebhookPayload(
        user_id=user_id,
        phone=phone,
        text=text,
        callback_data=callback_data,
        chat_id=chat_id,
    )

    logger.info(
        f"[MAX WEBHOOK] update_type={update_type}, user_id={user_id}, "
        f"chat_id={chat_id}, phone={mask_phone(phone)}"
    )

    agent = IntakeAgent(db)

    # 3. Check if user is sending phone contact / auth
    if payload.phone:
        # Positive verification: Contact is verified if and only if native contact
        # attachment provided contact_user_id matching the sender payload.user_id.
        is_verified_contact = bool(
            contact_user_id
            and payload.user_id
            and str(contact_user_id).strip() == str(payload.user_id).strip()
        )

        # Native contact attachment spoofing detection:
        # If contact_user_id is present but differs from sender, reject immediately.
        if contact_user_id and payload.user_id and str(contact_user_id).strip() != str(payload.user_id).strip():
            logger.warning(
                f"[SECURITY] Contact spoofing rejected: sender user_id={payload.user_id} "
                f"attempted to submit contact belonging to user_id={contact_user_id} (phone: {mask_phone(payload.phone)})"
            )
            reply_text = "❌ Ошибка безопасности: передача чужого контакта не допускается. Отправьте ваш контакт через кнопку в приложении MAX."
            max_bot_client.send_contact_request(payload.user_id, reply_text, chat_id=chat_id)
            if not is_test:
                return {"status": "ok"}
            return {
                "status": "error",
                "detail": "Contact spoofing rejected",
                "recipient_user_id": payload.user_id,
                "text": reply_text,
                "request_contact_button": True,
            }

        phone_clean = normalize_phone_number(payload.phone)
        phone_raw = payload.phone.strip()

        # Link matching employee in database ONLY if contact is positively verified
        emp = db.query(Employee).filter(
            (Employee.phone == phone_clean) | (Employee.phone == phone_raw) | (Employee.phone.like(f"%{phone_clean[-10:]}"))
        ).first()
        if emp and is_verified_contact:
            if payload.user_id:
                db.query(Employee).filter(
                    Employee.max_user_id == payload.user_id,
                    Employee.id != emp.id,
                ).update({"max_user_id": None})
                emp.max_user_id = payload.user_id
            if chat_id:
                emp.max_chat_id = chat_id
            db.commit()

        # Check if phone belongs to a Bot Administrator (bind ONLY if contact is positively verified)
        admin = db.query(BotAdmin).filter(
            (BotAdmin.phone == phone_clean) | (BotAdmin.phone == phone_raw) | (BotAdmin.phone.like(f"%{phone_clean[-10:]}"))
        ).first()
        if admin:
            if is_verified_contact:
                if payload.user_id:
                    db.query(BotAdmin).filter(
                        BotAdmin.max_user_id == payload.user_id,
                        BotAdmin.id != admin.id,
                    ).update({"max_user_id": None})
                    admin.max_user_id = payload.user_id
                if chat_id:
                    admin.max_chat_id = chat_id
                db.commit()
            else:
                logger.warning(
                    f"[SECURITY] Unverified contact for BotAdmin {admin.full_name} ({mask_phone(payload.phone)}) "
                    f"from user_id={payload.user_id} rejected from binding admin account."
                )
            reply_text = (
                f"👑 Здравствуйте, {admin.full_name}!\n"
                f"Вы авторизованы как администратор бота ({admin.role_title}).\n\n"
                f"Команды:\n"
                f"• Напишите «/admin» для просмотра списка сотрудников.\n"
                f"• Или напишите даты отпуска для планирования графика (например: «с 1 по 14 июля 2026»)."
            )
            max_bot_client.send_message(payload.user_id, reply_text, chat_id=chat_id)
            if not is_test:
                return {"status": "ok"}
            return {"status": "ok", "recipient_user_id": payload.user_id, "text": reply_text}

        # Check employee in database (pass max_user_id ONLY if verified to prevent intake_agent from overwriting)
        verified_uid_for_agent = payload.user_id if is_verified_contact else None
        auth_res = agent.verify_employee_by_phone(phone=payload.phone, max_user_id=verified_uid_for_agent)
        if not auth_res["authenticated"]:
            msg = auth_res["message"]
            max_bot_client.send_message(payload.user_id, msg, chat_id=chat_id)
            if not is_test:
                return {"status": "ok"}
            return {"status": "ok", "recipient_user_id": payload.user_id, "text": msg}

        reply_text = auth_res["message"] + f"\n\nВаш доступный баланс: {auth_res['total_days']} дней.\nНапишите желаемые даты отпуска."
        max_bot_client.send_message(payload.user_id, reply_text, chat_id=chat_id)
        if not is_test:
            return {"status": "ok"}
        return {"status": "ok", "recipient_user_id": payload.user_id, "text": reply_text}

    # 4. Lookup if sender is a Bot Administrator (by user_id or chat_id)
    admin = None
    if payload.user_id:
        admin = db.query(BotAdmin).filter(BotAdmin.max_user_id == payload.user_id).first()
    if not admin and chat_id:
        admin = db.query(BotAdmin).filter(BotAdmin.max_chat_id == chat_id).first()

    if admin:
        text_clean = (payload.text or "").strip().lower()
        if text_clean in ["/admin", "админ", "/админ"]:
            total_emps = db.query(Employee).count()
            pending_emps = db.query(Employee).filter(Employee.bot_access == "PENDING").all()
            p_text = f"• Ожидают подтверждения номера: {len(pending_emps)}\n"
            if pending_emps:
                p_text += "\n".join(f"  - {e.full_name} ({e.phone})" for e in pending_emps[:5])
            reply = f"👑 **Панель администратора MAX:**\nВсего сотрудников в базе: {total_emps}\n{p_text}\n\nВы можете подтверждать номера в веб-дашборде фабрики."
            max_bot_client.send_message(payload.user_id, reply, chat_id=chat_id)
            if not is_test:
                return {"status": "ok"}
            return {"status": "ok", "recipient_user_id": payload.user_id, "text": reply}

    # 5. Lookup employee (by user_id or chat_id)
    employee = None
    if payload.user_id:
        employee = db.query(Employee).filter(Employee.max_user_id == payload.user_id).first()
    if not employee and chat_id:
        employee = db.query(Employee).filter(Employee.max_chat_id == chat_id).first()

    # Keep chat_id up to date if known
    if chat_id:
        if employee and employee.max_chat_id != chat_id:
            employee.max_chat_id = chat_id
            db.commit()
        if admin and admin.max_chat_id != chat_id:
            admin.max_chat_id = chat_id
            db.commit()
    elif not chat_id:
        if employee and employee.max_chat_id:
            chat_id = employee.max_chat_id
        elif admin and admin.max_chat_id:
            chat_id = admin.max_chat_id

    if not employee:
        if admin:
            reply = (
                f"👑 Здравствуйте, {admin.full_name}!\n"
                f"Вы авторизованы как администратор бота ({admin.role_title}).\n\n"
                f"Команды:\n"
                f"• Напишите «/admin» для просмотра списка сотрудников.\n"
                f"(Для планирования личного отпуска добавьте себя в список сотрудников в панели управления)."
            )
            max_bot_client.send_message(payload.user_id, reply, chat_id=chat_id)
            if not is_test:
                return {"status": "ok"}
            return {"status": "ok", "recipient_user_id": payload.user_id, "text": reply}

        reply_text = "Для авторизации, пожалуйста, отправьте ваш контакт через кнопку в приложении MAX."
        max_bot_client.send_contact_request(payload.user_id, reply_text, chat_id=chat_id)
        if not is_test:
            return {"status": "ok"}
        return {
            "status": "ok",
            "recipient_user_id": payload.user_id,
            "text": reply_text,
            "request_contact_button": True,
        }

    # 6. Enforce administrator confirmation
    bot_access = getattr(employee, "bot_access", "APPROVED") or "APPROVED"
    if bot_access == "PENDING":
        reply = f"⏳ {employee.full_name}, ваш номер телефона ожидает подтверждения администратором бота. Пожалуйста, обратитесь к руководству цеха."
        max_bot_client.send_message(payload.user_id, reply, chat_id=chat_id)
        if not is_test:
            return {"status": "ok"}
        return {"status": "ok", "recipient_user_id": payload.user_id, "text": reply}
    elif bot_access == "BLOCKED":
        reply = f"🚫 Доступ к боту для номера {mask_phone(employee.phone)} заблокирован администратором."
        max_bot_client.send_message(payload.user_id, reply, chat_id=chat_id)
        if not is_test:
            return {"status": "ok"}
        return {"status": "ok", "recipient_user_id": payload.user_id, "text": reply}

    # 7. Process message text or callback via threadpool
    text_to_process = payload.callback_data if payload.callback_data else (payload.text or "")
    if not text_to_process or update_type == "bot_started":
        text_to_process = "/start"

    response = await run_in_threadpool(
        agent.process_message,
        employee.id,
        text_to_process,
        payload.user_id or employee.max_user_id,
    )

    # Format reply buttons for MAX
    inline_buttons = []
    p = response.get("payload", {}) or {}
    if p.get("action") == "CONSENT_REQUEST":
        inline_buttons.append({"text": "✅ Согласна", "callback_data": "✅ Согласна"})
        inline_buttons.append({"text": "❌ Отказаться", "callback_data": "❌ Отказаться"})
    elif p.get("action") == "OFFER_ALTERNATIVES":
        alts = p.get("suggested_alternatives", [])
        for a in alts:
            inline_buttons.append({
                "text": f"Выбрать Вариант {a['option']}",
                "callback_data": f"вариант {a['option']}",
            })
    elif p.get("show_confirm_buttons"):
        inline_buttons.append({"text": "✅ Подтвердить отправку", "callback_data": "подтверждаю"})
        inline_buttons.append({"text": "🔄 Сброс", "callback_data": "сброс"})

    reply_text = response["text"]
    if admin and p.get("action") == "GREETING" and "👑" not in reply_text:
        reply_text += f"\n\n👑 *Вы авторизованы как администратор ({admin.role_title}).*\nКоманда «/admin» — просмотр сотрудников и статуса."

    max_bot_client.send_message(payload.user_id, reply_text, inline_buttons if inline_buttons else None, chat_id=chat_id)

    if not is_test:
        return {"status": "ok"}

    return {
        "status": "ok",
        "recipient_user_id": payload.user_id,
        "text": reply_text,
        "inline_keyboard": inline_buttons if inline_buttons else None,
    }
