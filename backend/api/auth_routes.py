from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas import VerifyPhoneRequest, VerifyPhoneResponse
from backend.agents.intake_agent import IntakeAgent

router = APIRouter(prefix="/api/auth", tags=["Authentication & Verification"])


@router.post("/verify_phone", response_model=VerifyPhoneResponse)
def verify_phone(req: VerifyPhoneRequest, db: Session = Depends(get_db)):
    """
    Tool 1: verify_employee_by_phone
    Verifies employee by phone number and binds MAX messenger session.
    """
    agent = IntakeAgent(db)
    result = agent.verify_employee_by_phone(phone=req.phone, max_user_id=req.max_user_id)
    return VerifyPhoneResponse(**result)
