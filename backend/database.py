import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./vacations.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15} if "sqlite" in DATABASE_URL else {},
)

if "sqlite" in DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA temp_store=MEMORY;")
        cursor.execute("PRAGMA cache_size=-4000;")
        cursor.close()

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

            # 3. Employees max_chat_id
            if col_names and "max_chat_id" not in col_names:
                conn.execute(text("ALTER TABLE employees ADD COLUMN max_chat_id VARCHAR(64)"))
                conn.commit()

            # 4. BotAdmins max_chat_id
            res_admins = conn.execute(text("PRAGMA table_info(bot_admins)")).fetchall()
            admin_cols = [r[1] for r in res_admins]
            if admin_cols and "max_chat_id" not in admin_cols:
                conn.execute(text("ALTER TABLE bot_admins ADD COLUMN max_chat_id VARCHAR(64)"))
                conn.commit()

            # 5. Employees consent_152fz
            if col_names and "consent_152fz" not in col_names:
                conn.execute(text("ALTER TABLE employees ADD COLUMN consent_152fz BOOLEAN DEFAULT 0"))
                conn.commit()
    except Exception as e:
        print(f"Migration error: {e}")

