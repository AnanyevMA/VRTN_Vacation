from datetime import datetime, date, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, ForeignKey, JSON, Text
)
from sqlalchemy.orm import relationship
from backend.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    code = Column(String(50), nullable=True)
    manager_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    employees = relationship("Employee", back_populates="department")
    job_roles = relationship("JobRole", back_populates="department", cascade="all, delete-orphan")


class JobRole(Base):
    __tablename__ = "job_roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    description = Column(Text, nullable=True)
    default_quota = Column(Integer, default=1)  # Макс. одновременных отсутствий
    is_critical = Column(Boolean, default=True)

    department = relationship("Department", back_populates="job_roles")


class WorkShift(Base):
    __tablename__ = "work_shifts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    default_quota = Column(Integer, default=2)  # Макс. одновременных отпусков в одной смене
    is_active = Column(Boolean, default=True)


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    max_user_id = Column(String(64), unique=True, nullable=True, index=True)
    full_name = Column(String(255), nullable=False)
    role = Column(String(100), nullable=False)  # e.g. "Швея", "Закройщик", "Технолог"
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    shift = Column(String(50), default="Смена 1 (дневная)")  # e.g. "Смена 1 (дневная)", "Смена 2 (вечерняя)", "2/2", "5/2"
    region = Column(String(100), default="Республика Хакасия")
    total_vacation_days = Column(Integer, default=36)  # 36 дней для Хакасии (28 + 8 доп. дней)
    seniority_years = Column(Integer, default=1)
    social_priority = Column(String(50), default="NONE")  # 'NONE', 'LARGE_FAMILY', 'VETERAN', 'SOLO_PARENT'
    bot_access = Column(String(30), default="APPROVED")  # 'APPROVED', 'PENDING', 'BLOCKED'
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)

    department = relationship("Department", back_populates="employees")
    vacation_slots = relationship("VacationSlot", back_populates="employee", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="employee", cascade="all, delete-orphan")
    draft = relationship("EmployeeDraft", back_populates="employee", uselist=False, cascade="all, delete-orphan")


class BotAdmin(Base):
    """Administrators who manage bot access, approve phone numbers, and supervise vacation intake."""
    __tablename__ = "bot_admins"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    role_title = Column(String(100), default="Администратор")  # e.g. "Директор", "Начальник цеха", "Кадровик"
    max_user_id = Column(String(64), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    notify_on_new_request = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class EmployeeDraft(Base):
    """Stores accumulative draft vacation periods before formal submission to manager."""
    __tablename__ = "employee_drafts"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), unique=True, nullable=False)
    target_year = Column(Integer, default=2026)
    slots = Column(JSON, default=list)  # [{"start": "2027-07-01", "end": "2027-07-14", "days": 14}]
    status = Column(String(50), default="DRAFTING")  # 'DRAFTING', 'AWAITING_CONFIRMATION', 'COMMITTED'
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    employee = relationship("Employee", back_populates="draft")


class ScheduleRule(Base):
    __tablename__ = "schedule_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_key = Column(String(50), unique=True, nullable=False)
    rule_type = Column(String(20), nullable=False)  # 'HARD' | 'SOFT'
    parameters = Column(JSON, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class VacationSlot(Base):
    __tablename__ = "vacation_slots"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    days_count = Column(Integer, nullable=False)
    is_primary_block = Column(Boolean, default=False)  # Блок >= 14 дней
    status = Column(String(30), default="REQUESTED")  # 'REQUESTED', 'APPROVED', 'CONFLICT', 'REVISED', 'REJECTED'
    conflict_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    employee = relationship("Employee", back_populates="vacation_slots")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    sender = Column(String(20), nullable=False)  # 'USER', 'AGENT', 'SYSTEM'
    text = Column(Text, nullable=False)
    payload = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=utc_now)

    employee = relationship("Employee", back_populates="chat_messages")
