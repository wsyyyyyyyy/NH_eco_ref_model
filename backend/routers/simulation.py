from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class SimulationRequest(BaseModel):
    interest_rate_change: float
    fx_rate_change: float
    cpi_change: float

@router.post("/")
def run_simulation(req: SimulationRequest):
    # This will be expanded later to run real-time inference on LightGBM.
    # For now, it returns a mock aggregated response.
    return {
        "status": "success",
        "message": f"Simulated with interest {req.interest_rate_change}%, FX {req.fx_rate_change}%",
        "impacted_industries": [
            {"industry": "건설업", "risk_increase": 5.2},
            {"industry": "제조업", "risk_increase": 2.1}
        ]
    }
