from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel

app = FastAPI(title="ERM Web Service API", description="ECO Ref Model 기반 부도 예측 API", version="1.0.0")

# CORS 설정 (프론트엔드 연동을 위해 모든 출처 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mock Data Models
class CompanySummary(BaseModel):
    bzno: str
    name: str
    industry: str
    virtual_branch: str
    risk_grade: str
    z_score: float
    probability: float

class CompanyDetail(CompanySummary):
    total_assets: int
    total_liabilities: int
    business_age: int
    is_budo_predicted: bool

# Mock Data
MOCK_COMPANIES = [
    {
        "bzno": "123-45-67890",
        "name": "(주)테스트기업A",
        "industry": "제조업",
        "virtual_branch": "VB001",
        "risk_grade": "G5",
        "z_score": 2.5,
        "probability": 0.85,
    },
    {
        "bzno": "234-56-78901",
        "name": "(주)건설테스트B",
        "industry": "건설업",
        "virtual_branch": "VB002",
        "risk_grade": "G4",
        "z_score": 1.2,
        "probability": 0.45,
    },
    {
        "bzno": "345-67-89012",
        "name": "(주)IT서비스C",
        "industry": "IT서비스",
        "virtual_branch": "VB005",
        "risk_grade": "G1",
        "z_score": -1.5,
        "probability": 0.01,
    }
]

@app.get("/")
def read_root():
    return {"message": "Welcome to ERM Web Service API"}

@app.get("/api/companies", response_model=List[CompanySummary])
def get_companies(grade: Optional[str] = None):
    if grade:
        return [c for c in MOCK_COMPANIES if c["risk_grade"] == grade.upper()]
    return MOCK_COMPANIES

@app.get("/api/company/{bzno}", response_model=CompanyDetail)
def get_company(bzno: str):
    company = next((c for c in MOCK_COMPANIES if c["bzno"] == bzno), None)
    if company:
        # 상세 데이터 Mocking
        detail = dict(company)
        detail.update({
            "total_assets": 1000000000,
            "total_liabilities": 500000000,
            "business_age": 5,
            "is_budo_predicted": company["risk_grade"] in ["G4", "G5"]
        })
        return detail
    return {"error": "Company not found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
