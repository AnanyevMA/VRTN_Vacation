import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.database import engine, Base, migrate_db
from backend.seed_data import seed_database, ensure_minimal_rules_if_empty
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
from backend.api.miniapp_routes import router as miniapp_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_db()
    is_prod = os.getenv("ENVIRONMENT", "").strip().lower() == "production"
    auto_seed = os.getenv("AUTO_SEED_DEMO", "false" if is_prod else "true").strip().lower()
    if auto_seed in ("1", "true", "yes"):
        seed_database()
    else:
        ensure_minimal_rules_if_empty()
    yield


is_production = os.getenv("ENVIRONMENT", "").strip().lower() == "production"

app = FastAPI(
    title="Garment Factory Vacation Scheduling Multi-Agent System (MAX + Dashboard)",
    description="Multi-Agent System for garment manufacturing plant with multi-year Gantt, shifts, departments, roles CRUD, and MAX accumulative draft.",
    version="2.0.0",
    lifespan=lifespan,
    root_path=os.getenv("ROOT_PATH", ""),
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.endswith("/miniapp"):
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://*.max.ru https://max.ru https://*.oneme.ru"
    else:
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

raw_cors = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://46.149.79.201")
cors_origins = [o.strip() for o in raw_cors.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
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
app.include_router(miniapp_router)

# Mount frontend static files
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/miniapp")
    @app.get("/miniapp/")
    async def serve_miniapp():
        return FileResponse(os.path.join(frontend_dir, "miniapp.html"))
