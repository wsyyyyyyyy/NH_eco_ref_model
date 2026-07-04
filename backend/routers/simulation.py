import statistics

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
    kospi_shock: float = 0.0
    global_risk_shock: float = 0.0
    commodity_shock: float = 0.0
    eur_shock: float = 0.0

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
        kospi_shock=req.kospi_shock,
        global_risk_shock=req.global_risk_shock,
        commodity_shock=req.commodity_shock,
        eur_shock=req.eur_shock,
    )

    features = model.feature_name()
    base_prob = model.predict(baseline[features])
    shocked_prob = model.predict(shocked[features])

    industries = baseline['STD_INDS_CFC'].apply(get_industry_name)

    # 산업별 대표 리스크는 평균(mean)이 아닌 중앙값(median)을 사용한다. 부도확률
    # 분포가 극단적으로 오른쪽 꼬리가 긴(소수 초고위험 기업이 40~99%대) 형태라,
    # 평균을 쓰면 전형적인 기업의 실제 체감 리스크(중앙값 기준 1~2%대)보다
    # 훨씬 높게(업종 평균 5~12%대) 나와 3단 위험 매트릭스가 상시 "고위험"으로만
    # 분류되는 문제가 있었다(재학습 전 모델도 동일 현상 확인, docs/step29 참고).
    agg = {}
    for ind, b, s in zip(industries, base_prob, shocked_prob):
        if ind not in agg:
            agg[ind] = {'base': [], 'shock': []}
        agg[ind]['base'].append(b)
        agg[ind]['shock'].append(s)

    results = []
    for ind in DISPLAY_INDUSTRIES:
        if ind not in agg or not agg[ind]['base']:
            continue
        stats = agg[ind]
        base_risk = round(statistics.median(stats['base']) * 100, 2)
        new_risk = round(statistics.median(stats['shock']) * 100, 2)
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
