from typing import List, Optional, Any, Dict
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


# --- Department Schemas ---
class DepartmentBase(BaseModel):
    name: str
    code: Optional[str] = None
    manager_name: Optional[str] = None
    description: Optional[str] = None


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    manager_name: Optional[str] = None
    description: Optional[str] = None


class DepartmentOut(DepartmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_count: Optional[int] = 0


# --- JobRole Schemas ---
class JobRoleBase(BaseModel):
    name: str
    department_id: Optional[int] = None
    description: Optional[str] = None
    default_quota: int = 1
    is_critical: bool = True


class JobRoleCreate(JobRoleBase):
    pass


class JobRoleUpdate(BaseModel):
    name: Optional[str] = None
    department_id: Optional[int] = None
    description: Optional[str] = None
    default_quota: Optional[int] = None
    is_critical: Optional[bool] = None


class JobRoleOut(JobRoleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    department_name: Optional[str] = None


# --- WorkShift Schemas ---
class WorkShiftBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    default_quota: int = 2
    is_active: bool = True


class WorkShiftCreate(WorkShiftBase):
    pass


class WorkShiftUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    default_quota: Optional[int] = None
    is_active: Optional[bool] = None


class WorkShiftOut(WorkShiftBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- Incompatible Employee Group Schemas ---
class IncompatibleGroupCreate(BaseModel):
    name: str
    employee_ids: List[int]
    max_concurrent: int = 1
    reason: Optional[str] = "Взаимозаменяемые сотрудники"


class IncompatibleGroupOut(BaseModel):
    id: str
    name: str
    employee_ids: List[int]
    employee_names: List[str] = []
    max_concurrent: int = 1
    reason: Optional[str] = None



# --- Employee Schemas ---
class EmployeeBase(BaseModel):
    phone: str
    max_user_id: Optional[str] = None
    full_name: str
    role: str
    department_id: int
    shift: str = "Смена 1 (дневная 07:00-15:30)"
    region: str = "Республика Хакасия"
    total_vacation_days: int = 36
    seniority_years: int = 1
    social_priority: str = "NONE"
    bot_access: str = "APPROVED"  # 'APPROVED', 'PENDING', 'BLOCKED'
    is_active: bool = True


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    phone: Optional[str] = None
    max_user_id: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    shift: Optional[str] = None
    region: Optional[str] = None
    total_vacation_days: Optional[int] = None
    seniority_years: Optional[int] = None
    social_priority: Optional[str] = None
    bot_access: Optional[str] = None
    is_active: Optional[bool] = None


class EmployeeOut(EmployeeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    department_name: Optional[str] = None
    scheduled_days: int = 0
    remaining_days: int = 36
    status_summary: str = "NOT_SUBMITTED"  # 'NOT_SUBMITTED', 'PENDING', 'APPROVED', 'CONFLICT'


# --- Bot Admin Schemas ---
class BotAdminBase(BaseModel):
    phone: str
    full_name: str
    role_title: str = "Администратор"
    max_user_id: Optional[str] = None
    is_active: bool = True
    notify_on_new_request: bool = True


class BotAdminCreate(BotAdminBase):
    pass


class BotAdminUpdate(BaseModel):
    phone: Optional[str] = None
    full_name: Optional[str] = None
    role_title: Optional[str] = None
    max_user_id: Optional[str] = None
    is_active: Optional[bool] = None
    notify_on_new_request: Optional[bool] = None


class BotAdminOut(BotAdminBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# --- Vacation Slot Schemas ---
class DateSlot(BaseModel):
    start: date
    end: date


class VacationSlotBase(BaseModel):
    employee_id: int
    start_date: date
    end_date: date
    days_count: int
    is_primary_block: bool = False
    status: str = "REQUESTED"
    conflict_reason: Optional[str] = None


class VacationSlotCreate(BaseModel):
    employee_id: int
    start_date: date
    end_date: date


class VacationSlotOut(VacationSlotBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    employee_name: Optional[str] = None
    employee_role: Optional[str] = None
    employee_shift: Optional[str] = None
    department_name: Optional[str] = None


# --- Rule Schemas ---
class ScheduleRuleBase(BaseModel):
    rule_key: str
    rule_type: str  # 'HARD' | 'SOFT'
    parameters: Dict[str, Any]
    description: Optional[str] = None
    is_active: bool = True


class ScheduleRuleCreate(ScheduleRuleBase):
    pass


class ScheduleRuleUpdate(BaseModel):
    rule_type: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ScheduleRuleOut(ScheduleRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: datetime


# --- Tool 1: verify_employee_by_phone ---
class VerifyPhoneRequest(BaseModel):
    phone: str
    max_user_id: Optional[str] = None


class VerifyPhoneResponse(BaseModel):
    authenticated: bool
    employee_id: Optional[int] = None
    name: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    shift: Optional[str] = None
    region: Optional[str] = None
    total_days: int = 36
    planned_days: int = 0
    remaining_days: int = 36
    slots: List[Dict[str, Any]] = []
    draft_slots: List[Dict[str, Any]] = []
    message: str = ""


# --- Tool 2: run_vacation_optimizer ---
class AlternativeOption(BaseModel):
    option: int
    slots: List[Dict[str, str]]
    total_days: int
    reason: str
    score: float = 0.0


class OptimizeVacationRequest(BaseModel):
    employee_id: int
    requested_slots: List[DateSlot]
    window_search_days: int = 45


class OptimizeVacationResponse(BaseModel):
    status: str  # 'VALID' | 'CONFLICT' | 'INVALID_TK'
    message: str
    conflicting_with_roles: List[str] = []
    violations: List[str] = []
    suggested_alternatives: List[AlternativeOption] = []
    total_requested_days: int = 0
    has_primary_block_14: bool = False


# --- Tool 3: update_rules_and_roster ---
class UpdateRulesAndRosterRequest(BaseModel):
    action: str
    payload: Dict[str, Any]


class UpdateRulesAndRosterResponse(BaseModel):
    success: bool
    affected_rows: int = 1
    message: str
    data: Optional[Any] = None


# --- Chat & Messenger Webhook Schemas ---
class ChatMessageIn(BaseModel):
    employee_id: int
    message: str
    max_user_id: Optional[str] = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    sender: str
    text: str
    payload: Optional[Dict[str, Any]] = None
    timestamp: datetime


class MaxWebhookPayload(BaseModel):
    update_id: Optional[str] = None
    user_id: str
    phone: Optional[str] = None
    text: Optional[str] = None
    callback_data: Optional[str] = None
