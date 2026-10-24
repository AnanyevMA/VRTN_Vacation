import io
import csv
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session, joinedload
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

from backend.database import get_db
from backend.models import Employee, VacationSlot
from backend.agents.manager_agent import ManagerAgent
from backend.auth import require_admin


def sanitize_formula_injection(val):
    """
    Sanitize string cells starting with '=', '+', '-', '@' by prepending "'"
    to prevent CSV / Excel formula injection (CWE-1236).
    """
    if isinstance(val, str):
        stripped = val.lstrip()
        if stripped and stripped[0] in ("=", "+", "-", "@"):
            return f"'{val}"
    return val


def sanitize_row(row):
    return [sanitize_formula_injection(cell) for cell in row]


router = APIRouter(prefix="/api/export", tags=["Exports & Dashboard Analytics"])


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    agent = ManagerAgent(db)
    return agent.get_dashboard_summary()


@router.get("/csv", dependencies=[Depends(require_admin)])
def export_csv_schedule(db: Session = Depends(get_db)):
    slots = (
        db.query(VacationSlot)
        .join(Employee)
        .options(joinedload(VacationSlot.employee).joinedload(Employee.department))
        .order_by(Employee.department_id, Employee.full_name, VacationSlot.start_date)
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "ID",
        "ФИО Сотрудника",
        "Должность",
        "Отдел",
        "Регион",
        "Дата начала",
        "Дата окончания",
        "Кол-во дней",
        "Основной блок (>=14)",
        "Статус",
    ])

    for s in slots:
        emp = s.employee
        dept_name = emp.department.name if emp.department else ""
        writer.writerow(sanitize_row([
            s.id,
            emp.full_name,
            emp.role,
            dept_name,
            emp.region,
            s.start_date.strftime("%d.%m.%Y"),
            s.end_date.strftime("%d.%m.%Y"),
            s.days_count,
            "Да" if s.is_primary_block else "Нет",
            s.status,
        ]))

    csv_data = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vacation_schedule_2026.csv"},
    )


@router.get("/excel", dependencies=[Depends(require_admin)])
def export_excel_t7(db: Session = Depends(get_db)):
    slots = (
        db.query(VacationSlot)
        .join(Employee)
        .options(joinedload(VacationSlot.employee).joinedload(Employee.department))
        .order_by(Employee.department_id, Employee.full_name, VacationSlot.start_date)
        .all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "График отпусков Т-7 (2026)"

    headers = [
        "№ п/п",
        "Структурное подразделение",
        "Должность (специальность)",
        "ФИО сотрудника",
        "Табельный номер / ID",
        "Кол-во дней",
        "Запланированная дата начала",
        "Запланированная дата окончания",
        "Статус согласования",
        "Примечание / Регион",
    ]
    ws.append(headers)
    bold_font = Font(bold=True)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = bold_font
        cell.alignment = Alignment(horizontal="center")

    for idx, s in enumerate(slots, 1):
        emp = s.employee
        dept_name = emp.department.name if emp.department else ""
        status_label = (
            "Утвержден"
            if s.status == "APPROVED"
            else ("На рассмотрении" if s.status == "REQUESTED" else "Требует внимания")
        )
        ws.append(sanitize_row([
            idx,
            dept_name,
            emp.role,
            emp.full_name,
            emp.id,
            s.days_count,
            s.start_date.strftime("%d.%m.%Y"),
            s.end_date.strftime("%d.%m.%Y"),
            status_label,
            f"{emp.region} ({emp.total_vacation_days} дн.)",
        ]))

    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_data = excel_buffer.getvalue()
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=form_t7_vacation_schedule_2026.xlsx"},
    )

