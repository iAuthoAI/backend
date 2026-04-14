from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import time

from common.config import settings

# Import Sub-apps
from login.login_main import app as login_app
from pa.pa_main import app as pa_app
from patient.patient_main import app as patient_app
from patient.schedule_main import app as schedule_app
from payer.payer_main import app as payer_app
from payer.payer_portal_main import app as payer_portal_app
from codes.codes_main import app as codes_app
from notifications.notifications_main import app as notifications_app
from common.fhir_main import app as fhir_app

app = FastAPI(
    title="OneClick",
    description="AI-Powered Prior Authorization Platform (Microservices)",
    version="2.0.0",
    docs_url="/api/docs",
)

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

# Timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Mount Services
app.mount("/LG", login_app)
app.mount("/PA", pa_app)
app.mount("/PT/schedule", schedule_app)
app.mount("/PT", patient_app)
app.mount("/PY/portal", payer_portal_app)
app.mount("/PY", payer_app)
app.mount("/CD", codes_app)
app.mount("/NT", notifications_app)
app.mount("/FHIR", fhir_app)

# Root/Health
@app.get("/")
async def root():
    return {"app": "OneClick", "status": "operational", "architecture": "Modular Microservices"}

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
