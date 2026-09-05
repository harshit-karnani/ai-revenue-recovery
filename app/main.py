import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.health import router as health_router
from app.api.recovery import router as recovery_router
from app.api.dashboard import router as dashboard_router

app = FastAPI(
    title="Failure-Aware Revenue Recovery Engine",
    description="Razorpay AI Buildathon Backend",
    version="0.1.0"
)

# API Routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(recovery_router, prefix="/api/v1/recovery", tags=["Recovery"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["Dashboard"])

# Static UI Mounting
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
@app.get("/demo")
def serve_demo():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "RevGuard: Autonomous Recurring Payment Recovery"}

# Trigger reload for Gemini provider

