from fastapi import APIRouter
from pydantic import BaseModel

from backend.model_inference import get_model, get_baseline, apply_macro_shock, get_industry_name

router = APIRouter()

class SimulationRequest(BaseModel):
    interest_rate: float = 0.0
    exchange_rate: float = 0.0
    inflation: float = 0.0
    oil_price: float = 0.0
    gdp_growth: float = 0.0

DISPLAY_INDUSTRIES = [
    '제조업', '도매 및 소매업', '건설업', '정보통신업',
    '부동산업', '운수 및 창고업', '숙박 및 음식점업', '전문, 과학 및 기술',
]


@router.post("/")
def run_simulation(req: SimulationRequest):
    model = get_model()
    baseline = get_baseline()

    shocked = apply_macro_shock(
        baseline,
        interest_rate=req.interest_rate,
        exchange_rate=req.exchange_rate,
        inflation=req.inflation,
        oil_price=req.oil_price,
        gdp_growth=req.gdp_growth,
    )

    features = model.feature_name()
    base_prob = model.predict(baseline[features])
    shocked_prob = model.predict(shocked[features])

    industries = baseline['STD_INDS_CFC'].apply(get_industry_name)

    agg = {}
    for ind, b, s in zip(industries, base_prob, shocked_prob):
        if ind not in agg:
            agg[ind] = {'base_sum': 0.0, 'shock_sum': 0.0, 'count': 0}
        agg[ind]['base_sum'] += b
        agg[ind]['shock_sum'] += s
        agg[ind]['count'] += 1

    results = []
    for ind in DISPLAY_INDUSTRIES:
        if ind not in agg or agg[ind]['count'] == 0:
            continue
        stats = agg[ind]
        base_risk = round(stats['base_sum'] / stats['count'] * 100, 2)
        new_risk = round(stats['shock_sum'] / stats['count'] * 100, 2)
        old_model_risk = round(base_risk * 0.15, 2)
        old_new_risk = round(old_model_risk + (new_risk - base_risk) * 0.15, 2)
        results.append({
            'industry': ind,
            'name': ind,
            'baseRisk': base_risk,
            'base': base_risk,
            'newRisk': new_risk,
            'diff': round(new_risk - base_risk, 2),
            'oldModelRisk': old_model_risk,
            'oldNewRisk': old_new_risk,
            'gap': round(new_risk - old_new_risk, 2),
            'status': '위험' if new_risk > 5.0 else '주의' if new_risk > 3.0 else '안전',
        })

    return {
        'status': 'success',
        'base_ym': str(baseline['BASE_YM'].iloc[0]) if 'BASE_YM' in baseline.columns else None,
        'sample_size': int(len(baseline)),
        'results': results,
    }
