from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

from app.core.config import settings
from app.api.endpoints import auth, patients, schedule, pa_requests, codes, payer_portal, payers, notifications, fhir

from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="OneClick",
    description="AI-Powered Prior Authorization Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version,
                         description=app.description, routes=app.routes)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["HTTPBearer"] = {
        "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
        "description": "Paste your access_token from POST /api/auth/login here."
    }
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi

# CORS
_cors_origins = settings.allowed_origins_list + [
    "http://localhost:3001", "http://localhost:3002",
    "http://127.0.0.1:3000", "http://127.0.0.1:3001",
    "http://localhost:5173", "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Routes
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(patients.router, prefix="/api/patients", tags=["Patients"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["Schedule"])
app.include_router(pa_requests.router, prefix="/api/pa-requests", tags=["Prior Authorization"])
app.include_router(codes.router, prefix="/api/codes", tags=["Medical Codes"])
app.include_router(payer_portal.router, prefix="/api/payer", tags=["Payer Portal"])
app.include_router(payers.router, prefix="/api/payers", tags=["Payers"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(fhir.router, prefix="/api/fhir", tags=["FHIR / SMART Health IT"])


@app.get("/", tags=["Health"])
async def root():
    return {
        "app": "OneClick",
        "version": "1.0.0",
        "status": "operational",
        "message": "AI-Powered Prior Authorization Platform",
    }


@app.get("/api/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
