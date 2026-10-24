from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import BotAdmin
from backend.schemas import BotAdminCreate, BotAdminUpdate, BotAdminOut
from backend.auth import require_admin

router = APIRouter(prefix="/api/bot-admins", tags=["MAX Bot Administrators"])


@router.get("", response_model=List[BotAdminOut])
def list_bot_admins(db: Session = Depends(get_db)):
    """Returns the list of administrators authorized to manage the MAX bot and approve phones."""
    return db.query(BotAdmin).order_by(BotAdmin.id.asc()).all()


@router.post("", response_model=BotAdminOut, dependencies=[Depends(require_admin)])
def create_bot_admin(admin_in: BotAdminCreate, db: Session = Depends(get_db)):
    """Registers a new administrator phone number in the system."""
    existing = db.query(BotAdmin).filter(BotAdmin.phone == admin_in.phone.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Администратор с таким номером телефона уже зарегистрирован")

    admin = BotAdmin(
        phone=admin_in.phone.strip(),
        full_name=admin_in.full_name.strip(),
        role_title=admin_in.role_title.strip() if admin_in.role_title else "Администратор",
        max_user_id=admin_in.max_user_id,
        is_active=admin_in.is_active,
        notify_on_new_request=admin_in.notify_on_new_request,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


@router.put("/{admin_id}", response_model=BotAdminOut, dependencies=[Depends(require_admin)])
def update_bot_admin(admin_id: int, admin_up: BotAdminUpdate, db: Session = Depends(get_db)):
    admin = db.query(BotAdmin).filter(BotAdmin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Администратор не найден")

    if admin_up.phone is not None:
        admin.phone = admin_up.phone.strip()
    if admin_up.full_name is not None:
        admin.full_name = admin_up.full_name.strip()
    if admin_up.role_title is not None:
        admin.role_title = admin_up.role_title.strip()
    if admin_up.max_user_id is not None:
        admin.max_user_id = admin_up.max_user_id
    if admin_up.is_active is not None:
        admin.is_active = admin_up.is_active
    if admin_up.notify_on_new_request is not None:
        admin.notify_on_new_request = admin_up.notify_on_new_request

    db.commit()
    db.refresh(admin)
    return admin


@router.delete("/{admin_id}", dependencies=[Depends(require_admin)])
def delete_bot_admin(admin_id: int, db: Session = Depends(get_db)):
    admin = db.query(BotAdmin).filter(BotAdmin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Администратор не найден")

    db.delete(admin)
    db.commit()
    return {"message": "Администратор успешно удален"}
