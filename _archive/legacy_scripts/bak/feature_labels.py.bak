# 모델 피처 원본 코드 -> 한글 설명 매핑.
# JEMU_* 부분은 eda_pipeline/step4_borrower_sheet.py의 JEMU_COL_MAP과 동일.
# 그 외는 docs/데이터명세서.md 및 eda_pipeline 주석에서 확인 가능한 범위까지 매핑.
# 매핑이 없는 피처는 원본 코드명을 그대로 노출한다 (임의로 지어내지 않음).
FEATURE_LABELS: dict[str, str] = {
    # JEMU_* 재무 계정 (eda_pipeline/step4_borrower_sheet.py JEMU_COL_MAP)
    "JEMU_112000": "유동자산",
    "JEMU_114000": "비유동자산",
    "JEMU_115000": "자산총계",
    "JEMU_116000": "유동부채",
    "JEMU_117000": "비유동부채",
    "JEMU_118000": "부채총계",
    "JEMU_118100": "유동부채(재)",
    "JEMU_118900": "비유동부채(재)",
    "JEMU_121000": "자본총계",
    "JEMU_123000": "자본금",
    "JEMU_125000": "매출액",
    "JEMU_125100": "제품매출",
    "JEMU_126000": "영업이익",
    "JEMU_128000": "당기순이익",
    "JEMU_129000": "EBITDA",
    "JEMU_191104": "유동비율",
    "JEMU_191105": "부채비율",
    "JEMU_191108": "자기자본비율",
    "JEMU_191110": "영업이익률",
    "JEMU_191204": "ROE",
    "JEMU_191207": "총자산회전율",
    "JEMU_191208": "매출채권회전율",
    "JEMU_191210": "재고자산회전율",
    "JEMU_191310": "이자보상배율",
    "JEMU_191502": "매출액증가율",
    "JEMU_191503": "영업이익증가율",
    "JEMU_191505": "자산증가율",
    "JEMU_191506": "자본증가율",

    # 기업 기본 정보 / 신용평가사 지표 (데이터명세서.md)
    "COPR_OPNP_C": "기업공개구분",
    "STD_INDS_CFC": "표준산업분류코드(업종)",
    "BUSINESS_AGE": "업력",
    "CG01_KIS_SCORE": "나이스(KIS) 신용평점",
    "C302_CRI_ORD": "나이스 CRI 신용등급",
    "AA10_PERS_CNT": "종업원 수",
    "AA17_TOT_SEL_AM": "총판매(매출) 금액",
    "AA17_LA_XPO_AM": "외화 익스포저 금액",
    "AA17_DME_AM": "국내 매출 금액",
    "AA17_EXT_PROD_RECORD_YN": "수출 실적 여부",

    # 관찰/여신 등급 (OBV)
    "OBV_ELYWRN_OBV_GRD_DSC": "조기경보 관찰 등급",
    "OBV_LN_LMT_AM": "여신 한도 금액",
    "OBV_LN_BAC": "여신 잔액",
    "OBV_LN_LMT_BAC": "여신 한도 잔액",
    "OBV_BZL_RZVL_ASP_ELGD": "사업자 회수예상 적격등급",
    "OBV_LD_AM": "대출 금액",
    "OBV_XPC_LSS_AM": "예상 손실 금액",

    # 신용조회기관(CRIF) 연체/신용불량 이력
    "CRIF_CRDBD_RSNC": "신용불량 사유 코드",
    "CRIF_SUM(CRDBD_RSN_AM)": "신용불량 발생 금액 합계",
    "CRIF_SUM(CRDBD_OVD_AM)": "연체 금액 합계",
    "CRIF_MAX(CRDBD_RLS_RSNC)": "신용불량 해제 사유(최근)",

    # 외화 익스포저(AC12)
    "AC12_US_FC_AM": "달러화 외화표시 익스포저",
    "AC12_US_KRW_AM": "달러화 원화환산 익스포저",
    "AC12_JP_FC_AM": "엔화 외화표시 익스포저",
    "AC12_JP_KRW_AM": "엔화 원화환산 익스포저",
    "AC12_CN_FC_AM": "위안화 외화표시 익스포저",
    "AC12_CN_KRW_AM": "위안화 원화환산 익스포저",
    "AC12_EU_FC_AM": "유로화 외화표시 익스포저",
    "AC12_EU_KRW_AM": "유로화 원화환산 익스포저",
    "AC12_TOTAL_KRW_AM": "외화 익스포저 총액(원화환산)",
    "AC12_EXT_OTHER_KRW_AM": "기타 외화 익스포저(원화환산)",

    # 거시경제 지표 (금리/환율/물가/유가/증시/경기)
    "base_rate_diff12": "기준금리 12개월 변동",
    "call_rate_overnight_diff12": "콜금리 12개월 변동",
    "KORIBOR_12m_diff12": "코리보(12M) 변동",
    "KORIBOR_6m_diff12": "코리보(6M) 변동",
    "KORIBOR_3m_diff12": "코리보(3M) 변동",
    "corporate_bond_3y_AA_diff12": "회사채(3년 AA) 금리 변동",
    "treasury_bond_10y_diff12": "국고채 10년물 금리 변동",
    "treasury_bond_1y_diff12": "국고채 1년물 금리 변동",
    "US_2Y_treasury_diff12": "미국채 2년물 금리 변동",
    "US_10Y_treasury_diff12": "미국채 10년물 금리 변동",
    "USD_KRW_log_ret": "원/달러 환율 변동률",
    "EUR_KRW_vol_m": "원/유로 환율 변동성",
    "JPY_KRW_vol_m": "원/엔 환율 변동성",
    "DXY_dollar_index_log_ret": "달러인덱스 변동률",
    "CPI_core_yoy": "근원 소비자물가 상승률",
    "CPI_core_excl_food_energy_yoy": "식품·에너지 제외 근원물가 상승률",
    "CPI_food_nonalcohol_yoy": "식품물가 상승률",
    "brent_crude_oil_log_ret": "브렌트유 가격 변동률",
    "WTI_crude_oil_log_ret": "WTI유 가격 변동률",
    "KOSPI_log_ret": "코스피 수익률",
    "KOSDAQ_log_ret_ma3m": "코스닥 수익률(3개월 평균)",
    "VIX_vol_m": "VIX 변동성 지수",
    "BSI_mfg_export_yoy": "제조업 수출 기업경기실사지수",
    "BSI_mfg_domestic_yoy": "제조업 내수 기업경기실사지수",
    "import_index_yoy": "수입물가지수 증가율",
}


def get_feature_label(code: str) -> str:
    return FEATURE_LABELS.get(code, code)
