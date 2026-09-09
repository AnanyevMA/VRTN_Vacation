import io
import csv
from datetime import datetime
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
import pandas as pd

from backend.database import get_db
from backend.models import Employee, VacationSlot, Department
from backend.agents.manager_agent import ManagerAgent

router = APIRouter(prefix="/api/export", tags=["Exports & Dashboard Analytics"])


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    agent = ManagerAgent(db)
    return agent.get_dashboard_summary()


@router.get("/csv")
def export_csv_schedule(db: Session = Depends(get_db)):
    slots = (
        db.query(VacationSlot)
        .join(Employee)
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
        writer.writerow([
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
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vacation_schedule_2026.csv"},
    )


@router.get("/excel")
def export_excel_t7(db: Session = Depends(get_db)):
    slots = (
        db.query(VacationSlot)
        .join(Employee)
        .order_by(Employee.department_id, Employee.full_name, VacationSlot.start_date)
        .all()
    )

    rows = []
    for idx, s in enumerate(slots, 1):
        emp = s.employee
        dept_name = emp.department.name if emp.department else ""
        rows.append({
            "№ п/п": idx,
            "Структурное подразделение": dept_name,
            "Должность (специальность)": emp.role,
            "ФИО сотрудника": emp.full_name,
            "Табельный номер / ID": emp.id,
            "Кол-во дней": s.days_count,
            "Запланированная дата начала": s.start_date.strftime("%d.%m.%Y"),
            "Запланированная дата окончания": s.end_date.strftime("%d.%m.%Y"),
            "Статус согласования": "Утвержден" if s.status == "APPROVED" else ("На рассмотрении" if s.status == "REQUESTED" else "Требует внимания"),
            "Примечание / Регион": f"{emp.region} ({emp.total_vacation_days} дн.)",
        })

    df = pd.DataFrame(rows)
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="График отпусков Т-7 (2026)", index=False)

    excel_data = excel_buffer.getvalue()
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=form_t7_vacation_schedule_2026.xlsx"},
    )
