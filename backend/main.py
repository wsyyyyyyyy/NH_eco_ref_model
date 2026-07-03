from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import dashboard, borrowers, ai, simulation, monitoring, auth

load_dotenv()

app = FastAPI(title="Virtual Branch Portal API", version="1.0.0")

# Setup CORS for Frontend React App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(borrowers.router, prefix="/api/borrowers", tags=["Borrowers"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI Tips"])
app.include_router(simulation.router, prefix="/api/simulation", tags=["Simulation"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["Monitoring"])

@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "Portal Backend is running"}
