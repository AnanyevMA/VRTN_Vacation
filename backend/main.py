import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.database import engine, Base, migrate_db
from backend.seed_data import seed_database
from backend.api.auth_routes import router as auth_router
from backend.api.employee_routes import router as employee_router
from backend.api.department_routes import router as department_router
from backend.api.role_routes import router as role_router
from backend.api.shift_routes import router as shift_router
from backend.api.vacation_routes import router as vacation_router
from backend.api.rule_routes import router as rule_router
from backend.api.chat_routes import router as chat_router
from backend.api.export_routes import router as export_router
from backend.api.admin_routes import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_db()
    seed_database()
    yield


app = FastAPI(
    title="Garment Factory Vacation Scheduling Multi-Agent System (MAX + Dashboard)",
    description="Multi-Agent System for garment manufacturing plant with multi-year Gantt, shifts, departments, roles CRUD, and MAX accumulative draft.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include All Routers
app.include_router(auth_router)
app.include_router(department_router)
app.include_router(role_router)
app.include_router(shift_router)
app.include_router(employee_router)
app.include_router(vacation_router)
app.include_router(rule_router)
app.include_router(chat_router)
app.include_router(export_router)
app.include_router(admin_router)

# Mount frontend static files
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))
