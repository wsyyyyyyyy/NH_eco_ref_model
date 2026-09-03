import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db, dedup_panel_sql
from backend.feature_labels import get_feature_label
from backend.grade_mapping import prob_to_grade
from backend.model_inference import get_feature_row, get_model, get_shap_explainer

router = APIRouter()

@router.get("/")
def get_borrowers(branch_code: str = "VB001", base_ym: str = "202402", page: int = 1, limit: int = 50, db=Depends(get_db)):
    offset = (page - 1) * limit
    query = """
        SELECT
            V_BZNO,
            ANY_VALUE(STD_INDS_CFC) as STD_INDS_CFC,
            MAX(PROB_FULL) as PROB_FULL,
            ANY_VALUE(Z_SCORE) as Z_SCORE,
            ANY_VALUE(Z_GRADE) as Z_GRADE,
            ANY_VALUE(OBV_ELYWRN_OBV_GRD_DSC) as OBV_ELYWRN_OBV_GRD_DSC,
            ROUND(MAX(PROB_FULL) * 0.15, 4) as OLD_PROB
        FROM corporate_panel
        WHERE V_BRANCH_CODE = ? AND CAST(BASE_YM AS VARCHAR) = ?
        GROUP BY V_BZNO
        ORDER BY PROB_FULL DESC
        LIMIT ? OFFSET ?
    """
    res = db.execute(query, [branch_code, str(base_ym), limit, offset]).df()
    records = res.to_dict(orient="records")
    for r in records:
        r["NICE_GRADE_PREV"] = prob_to_grade(r["OLD_PROB"])
        r["NICE_GRADE_CUR"] = prob_to_grade(r["PROB_FULL"])
        r["KIS_GRADE_PREV"] = prob_to_grade(r["OLD_PROB"])
        r["KIS_GRADE_CUR"] = prob_to_grade(r["PROB_FULL"])
    return records

@router.get("/{bzno}/financials")
def get_borrower_financials(bzno: str, base_ym: Optional[str] = None, years: int = 3, db=Depends(get_db)):
    """Last N distinct annual financial-statement vintages for a borrower.

    JEMU_* columns (자본총계/총자산/매출액/영업이익) come from yearly
    NOTE: 계정 코드는 input/가상사업자_JEMU_재무데이터v.txt 의 0행(한글 논리명)이
    정본이다. 과거 이 파일은 118100 부터 한 칸씩 밀린 매핑을 써서
    'capital' 에 매출액(121000)을, 'revenue' 에 영업이익(125000)을 넣고 있었다.
    아래 매핑이 원천 헤더 기준으로 정정된 것이다.
      118900 자본총계 / 115000 자산총계 / 121000 매출액 / 125000 영업이익(손실)
    financial statements re-joined onto the monthly panel, so the same value
    repeats for ~12 months until the next fiscal year's statement lands
    (verified directly against the DB). Each vintage is labeled by the year
    it FIRST took effect (MIN(BASE_YM) of the run) rather than whatever
    month happens to be queried - otherwise the same FY2023 statement would
    be mislabeled "2024" or "2025" depending purely on which month the user
    is currently viewing, instead of the fiscal year it actually reports.

    Some borrowers have a second vintage starting mid-year (e.g. a "no data
    yet" placeholder for Jan-Jun, then the real first filing from Jul) which
    would otherwise produce two columns both labeled with the same year; we
    keep only the latest-starting vintage per calendar year.
    """
    panel = dedup_panel_sql("WHERE V_BZNO = ?")
    params = [bzno]
    cutoff = ""
    if base_ym:
        cutoff = "AND CAST(BASE_YM AS VARCHAR) <= ?"
        params.append(str(base_ym))
    params.append(years)

    query = f"""
        WITH vintages AS (
            SELECT
                MIN(BASE_YM) AS vintage_start,
                arg_max(PROB_FULL, BASE_YM) AS PROB_FULL,
                arg_max(CG01_KIS_SCORE, BASE_YM) AS CG01_KIS_SCORE,
                JEMU_118900, JEMU_115000, JEMU_121000, JEMU_125000
            FROM {panel}
            WHERE 1=1 {cutoff}
            GROUP BY JEMU_118900, JEMU_115000, JEMU_121000, JEMU_125000
        ),
        yearly AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY SUBSTRING(CAST(vintage_start AS VARCHAR), 1, 4)
                    ORDER BY vintage_start DESC
                ) AS _yr_rn
            FROM vintages
        )
        SELECT * FROM yearly WHERE _yr_rn = 1
        ORDER BY vintage_start DESC
        LIMIT ?
    """
    res = db.execute(query, params).df()
    if res.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    records = []
    for _, row in res.iloc[::-1].iterrows():  # oldest -> newest for a trend
        vintage_start_str = str(int(row['vintage_start']))
        records.append({
            'year': vintage_start_str[:4],
            'base_ym': vintage_start_str,
            'capital': row['JEMU_118900'],          # 자본총계
            'total_assets': row['JEMU_115000'],     # 자산총계
            'revenue': row['JEMU_121000'],          # 매출액
            'operating_profit': row['JEMU_125000'], # 영업이익(손실)
            'kis_score': row['CG01_KIS_SCORE'],
            'nice_grade': prob_to_grade(row['PROB_FULL']),
        })
    return records


@router.get("/{bzno}/pd_history")
def get_borrower_pd_history(bzno: str, base_ym: Optional[str] = None, months: int = 6, db=Depends(get_db)):
    """Real recent monthly PROB_FULL trend for a borrower, up to base_ym."""
    panel = dedup_panel_sql("WHERE V_BZNO = ?")
    params = [bzno]
    cutoff = ""
    if base_ym:
        cutoff = "AND CAST(BASE_YM AS VARCHAR) <= ?"
        params.append(str(base_ym))
    params.append(months)

    query = f"""
        SELECT BASE_YM, PROB_FULL
        FROM {panel}
        WHERE 1=1 {cutoff}
        ORDER BY BASE_YM DESC
        LIMIT ?
    """
    res = db.execute(query, params).df()
    if res.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    records = []
    for _, row in res.iloc[::-1].iterrows():  # oldest -> newest for a trend
        ym = str(int(row['BASE_YM']))
        records.append({
            'month': f"{ym[2:4]}.{ym[4:6]}",
            'base_ym': ym,
            'pd': round(row['PROB_FULL'], 4),
        })
    return records


@router.get("/{bzno}/capability")
def get_borrower_capability(bzno: str, base_ym: Optional[str] = None, db=Depends(get_db)):
    """5-axis capability diagnostic (활동성/수익성/안정성/성장성/규모) for the
    borrower vs. its industry (KSIC division) peers in the same month.

    축 매핑은 input/가상사업자_JEMU_재무데이터v.txt 0행(한글 논리명)을 정본으로 정정했다.
    과거에는 118100 부터 한 칸 밀린 라벨을 보고 축을 짰기 때문에 11축 중 10축이
    의도한 지표와 다른 계정을 참조하고 있었다 (예: pr_roe 가 매출액영업이익율을 참조).

    정정 내역:
      pr_asset_turnover      191207 -> 191506_val  (총자본회전율 = 매출액/평균자산)
      pr_receivable_turnover 191208 -> 191502_val  (매출채권회전율)
      pr_inventory_turnover  191210 -> 191505_val  (재고자산회전율)
      pr_op_margin           191110 -> 191204_val  (매출액영업이익율)
      pr_roe                 191204 -> 191208_val  (자기자본순이익율)
      pr_interest_coverage   191310 -> 191207_val  (이자보상배율)
      pr_revenue_growth      191502 -> 191104_val  (매출액증가율)
      pr_debt_ratio_inv      191105 -> -JEMU_debt_ratio  (원계정 재계산, 아래 주석 참조)
      pr_current_ratio       (신규) -> JEMU_current_ratio (유동비율 = 유동자산/유동부채)
      pr_capital_growth      축 제거. 191506 은 자본증가율이 아니고, 원천에 자본증가율이
                             없다. 191105(순이익증가율)로 대체하면 sentinel 이 24.5%라
                             축의 1/4 이 비어 오히려 오해를 부른다.
      pr_assets              115000 유지 (원래 정상)

    _val 접미사는 jemu_sentinel 이 sentinel(10000~10003, ±9999.99)을 제거한 연속값이다.
    원본 컬럼을 그대로 PERCENT_RANK 하면 10001 이 최상위로 랭크된다.

    안정성 축에서 자기자본비율(118900/115000)은 제외했다. 부채비율 역수(118900/118000)와
    분자가 같아 정보가 거의 중복되고, 자본잠식이면 두 축이 단일 원인으로 동시에 최하위가
    되어 이중 감점이 발생하기 때문이다. 대신 유동비율(112000/116000)을 넣는다.
    분모가 자본총계와 무관해 자본잠식과 독립적이고(자본잠식 행에서도 99.70% 계산 가능),
    단기 지급능력이라는 다른 차원을 커버한다.
    세 번째 축인 이자보상배율(191207)도 자본총계와 무관하다(자본잠식 행 비결측 96.26%).

    자본잠식 자체는 모델에서 capital_impaired 플래그(부도 배수 2.55)로 이미 잡히므로
    차트에서 이중 강조할 필요가 없다. 차트에서는 별도 배지로 표시하는 것이 맞다(승인 대기).

    pr_debt_ratio_inv 는 1/debt_ratio 대신 -debt_ratio 로 정렬한다.
    PERCENT_RANK 는 순서만 보므로 debt_ratio > 0 구간에서 둘은 동일하고,
    부채 0(무차입) 인 경우 1/0 이 정의되지 않는 문제를 피할 수 있다.
    자본잠식(자본총계 <= 0, 2.55%)은 jemu_sentinel 이 debt_ratio 를 NULL 로 만든다.
    NULLS FIRST 로 최하위에 두어 "부채비율 0 인 우량기업"으로 보이지 않게 한다.
    (자본잠식은 부도 배수 2.55 의 최강 신호다.)

    Each axis is the average PERCENT_RANK() of the borrower's real JEMU_*
    financial ratios against every company in the same division/month
    (0~100, 50 = median). This replaces the previous fully hardcoded
    radarMockData with a real, population-relative score."""
    if not base_ym:
        panel_latest = dedup_panel_sql("WHERE V_BZNO = ?")
        row = db.execute(f"SELECT MAX(BASE_YM) FROM {panel_latest}", [bzno]).fetchone()
        if not row or row[0] is None:
            raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")
        base_ym = str(int(row[0]))

    division_expr = "CAST(SUBSTRING(LPAD(CAST(CAST(STD_INDS_CFC AS BIGINT) AS VARCHAR), 5, '0'), 1, 2) AS INT)"
    panel = dedup_panel_sql("WHERE CAST(BASE_YM AS VARCHAR) = ?")

    query = f"""
        WITH ranked AS (
            SELECT
                V_BZNO,
                {division_expr} AS division,
                PERCENT_RANK() OVER (ORDER BY JEMU_191506_val) AS pr_asset_turnover,
                PERCENT_RANK() OVER (ORDER BY JEMU_191502_val) AS pr_receivable_turnover,
                PERCENT_RANK() OVER (ORDER BY JEMU_191505_val) AS pr_inventory_turnover,
                PERCENT_RANK() OVER (ORDER BY JEMU_191204_val) AS pr_op_margin,
                PERCENT_RANK() OVER (ORDER BY JEMU_191208_val) AS pr_roe,
                PERCENT_RANK() OVER (
                    ORDER BY -JEMU_debt_ratio NULLS FIRST) AS pr_debt_ratio_inv,
                PERCENT_RANK() OVER (
                    ORDER BY JEMU_current_ratio NULLS FIRST) AS pr_current_ratio,
                PERCENT_RANK() OVER (ORDER BY JEMU_191207_val) AS pr_interest_coverage,
                PERCENT_RANK() OVER (ORDER BY JEMU_191104_val) AS pr_revenue_growth,
                PERCENT_RANK() OVER (ORDER BY JEMU_115000) AS pr_assets
            FROM {panel}
        ),
        scored AS (
            SELECT
                V_BZNO, division,
                (pr_asset_turnover + pr_receivable_turnover + pr_inventory_turnover) / 3.0 * 100 AS activity,
                (pr_op_margin + pr_roe) / 2.0 * 100 AS profitability,
                (pr_debt_ratio_inv + pr_current_ratio + pr_interest_coverage) / 3.0 * 100 AS stability,
                pr_revenue_growth * 100 AS growth,   -- pr_capital_growth 축 제거
                pr_assets * 100 AS scale
            FROM ranked
        )
        SELECT * FROM scored
        WHERE division = (SELECT division FROM scored WHERE V_BZNO = ?)
    """
    df = db.execute(query, [str(base_ym), bzno]).df()
    # ★ [2026-09-03] V_BZNO 는 새 패널에서 **VARCHAR** 다. int 로 캐스팅해 비교하면
    #   항상 False 가 되어 이 엔드포인트가 늘 404 를 냈다 (구 portal.duckdb 는
    #   정수형이었다). 문자열로 맞춘다 — 사업자번호는 선행 0 이 의미를 가지므로
    #   문자열 비교가 애초에 맞다.
    _key = df['V_BZNO'].astype(str)
    if df.empty or not (_key == str(bzno)).any():
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    target = df[_key == str(bzno)].iloc[0]
    industry_avg = df[['activity', 'profitability', 'stability', 'growth', 'scale']].mean()

    axes = {
        '활동성': ('activity', target['activity']),
        '수익성': ('profitability', target['profitability']),
        '안정성': ('stability', target['stability']),
        '성장성': ('growth', target['growth']),
        '규모': ('scale', target['scale']),
    }
    return {
        'target': {label: round(float(val), 1) for label, (_, val) in axes.items()},
        'industry_avg': {label: round(float(industry_avg[col]), 1) for label, (col, _) in axes.items()},
        'peer_count': int(len(df)),
    }


@router.get("/{bzno}/shap")
def get_borrower_shap(bzno: str, base_ym: Optional[str] = None, top_n: int = 8):
    """Real per-borrower SHAP feature attribution from the trained LightGBM
    model (TreeExplainer), instead of the previous static mock chart.

    SHAP values from a LightGBM binary classifier are additive in log-odds
    (margin) space, not probability space. A naive "SHAP * local sigmoid
    slope" conversion to %p looks tiny and misleading whenever the
    prediction is far from the population baseline (which is common here -
    e.g. base 1.3% vs. a G5 borrower's 93% both being routine), since the
    slope is evaluated near the baseline. Rather than fabricate a
    percentage-point number that doesn't hold up, we report:
    - base_pd / final_pd: real probabilities (population baseline vs. this
      borrower's actual predicted PD) - both unambiguous.
    - shap_raw: the true SHAP value in log-odds units (additive, correct).
    - impact_score: shap_raw normalized so the largest-magnitude feature
      among the top N is 100/-100, purely for bar-chart comparison.
    """
    row = get_feature_row(bzno, base_ym)
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    model = get_model()
    features = model.feature_name()
    explainer = get_shap_explainer()
    shap_values = explainer.shap_values(row[features])[0]
    base_value = explainer.expected_value
    if isinstance(base_value, (list, tuple)):
        base_value = base_value[0]

    def sigmoid(x):
        return 1 / (1 + math.exp(-x))

    base_prob = sigmoid(base_value)
    final_prob = sigmoid(base_value + sum(shap_values))

    contributions = sorted(
        zip(features, shap_values), key=lambda fv: abs(fv[1]), reverse=True
    )[:top_n]
    max_abs = max((abs(v) for _, v in contributions), default=1) or 1

    return {
        'base_pd': round(base_prob * 100, 2),
        'final_pd': round(final_prob * 100, 2),
        'features': [
            {
                'feature': f,
                'label': get_feature_label(f),
                'shap_raw': round(float(v), 5),
                'impact_score': round(float(v) / max_abs * 100, 1),
            }
            for f, v in contributions
        ],
    }


@router.get("/{bzno}")
def get_borrower_detail(bzno: str, base_ym: Optional[str] = None, db=Depends(get_db)):
    panel = dedup_panel_sql("WHERE V_BZNO = ?")
    if base_ym:
        query = f"SELECT * FROM {panel} WHERE CAST(BASE_YM AS VARCHAR) = ?"
        params = [bzno, str(base_ym)]
    else:
        # No month specified: fall back to the borrower's most recent record
        # rather than an arbitrary (effectively earliest) row.
        query = f"SELECT * FROM {panel} ORDER BY BASE_YM DESC LIMIT 1"
        params = [bzno]

    res = db.execute(query, params).df()
    if res.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    record = res.to_dict(orient="records")[0]
    record.pop("_rn", None)
    # pandas represents SQL NULL in numeric columns as float('nan'), which json.dumps
    # cannot serialize (raises ValueError) -- convert to None. Matters now that
    # RZVL_POD is mostly NULL (only populated for 2021.01~11).
    record = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in record.items()}
    old_prob = round(record["PROB_FULL"] * 0.15, 4)
    record["OLD_PROB"] = old_prob
    record["NICE_GRADE_PREV"] = prob_to_grade(old_prob)
    record["NICE_GRADE_CUR"] = prob_to_grade(record["PROB_FULL"])
    record["KIS_GRADE_PREV"] = prob_to_grade(old_prob)
    record["KIS_GRADE_CUR"] = prob_to_grade(record["PROB_FULL"])
    return record
