import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./vacations.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_db():
    """Ensure newly added columns and tables exist in SQLite without dropping data."""
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            # 1. Employees bot_access
            res = conn.execute(text("PRAGMA table_info(employees)")).fetchall()
            col_names = [r[1] for r in res]
            if col_names and "bot_access" not in col_names:
                conn.execute(text("ALTER TABLE employees ADD COLUMN bot_access VARCHAR(30) DEFAULT 'APPROVED'"))
                conn.commit()

            # 2. WorkShifts default_quota
            res_shifts = conn.execute(text("PRAGMA table_info(work_shifts)")).fetchall()
            shift_cols = [r[1] for r in res_shifts]
            if shift_cols and "default_quota" not in shift_cols:
                conn.execute(text("ALTER TABLE work_shifts ADD COLUMN default_quota INTEGER DEFAULT 2"))
                conn.commit()
    except Exception as e:
        print(f"Migration error: {e}")

