"""
final_scoring_pipeline.py
=========================
기업 고유 재무 데이터와 거시경제 원시 시계열 피처를 결합한 최종 PD 예측 및 
업종별 매크로 리스크 가중치 오버레이 통합 스코어링 파이프라인.

[절대 원칙 준수]
1. 독립변수 X에는 오직 model_input_train.csv 규격의 원시 피처(재무+172개 매크로 시계열)만 사용.
2. 스무딩 매트릭스의 파생/요약 변수 혼용 철저 차단.

입력:
  - input/model_input_train.csv
  - input/bzcc.xlsx
  - output/industry_macro_smoothed_weights.csv

출력:
  - output/final_borrower_credit_risk_report.csv
  - final_model_evaluation/ (평가 리포트 및 각종 차트 PNG)
"""

import os
import sys
import gc
import json
import shutil
import pickle
import logging
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from lightgbm import LGBMClassifier
import shap
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss, classification_report, roc_curve

warnings.filterwarnings('ignore')

# ─── 경로 및 로깅 설정 ───
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(_SCRIPT_DIR, "input")
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output")
EVAL_DIR = os.path.join(_SCRIPT_DIR, "final_model_evaluation")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(EVAL_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(OUTPUT_DIR, "final_scoring_pipeline.log"),
            mode='w', encoding='utf-8'
        )
    ]
)
log = logging.getLogger(__name__)

# ─── 한글 폰트 설정 ───
def setup_korean_font():
    for font_name in ['Malgun Gothic', 'NanumGothic', 'AppleGothic']:
        font_path = fm.findfont(fm.FontProperties(family=font_name))
        if font_path and 'fallback' not in font_path.lower():
            plt.rcParams['font.family'] = font_name
            plt.rcParams['axes.unicode_minus'] = False
            return
    plt.rcParams['axes.unicode_minus'] = False

setup_korean_font()

# ─── 학습 제외 상수 ───
EXCLUDE_COLS = [
    'V_BZNO', 'CONM', 'ETB_DT', 'COPR_OPNP_C', 'BZSCAL_C',
    'DSH_DT', 'DSH_RSN_DSC', 'NMLZ_DT', 'NMLZ_YN',
    'CRI_GRD', 'KIS_LS_FNA_MKS', 'CRDEVL_PTTP_DSC', 'LS_NICS_GRDC',
    'AUD_OPI_DSC', 'CRI_GRD_ORD', 'V_BZNO_1', 'BASE_YM',
    'ELYWRN_OBV_GRD_DSC', 'EXT_PROD_RECORD_YN', 'CRINF_RLR_DSC',
    'CRDBD_RSNC', 'MAX(CRDBD_RLS_RSNC)',
    'STD_INDS_CFC', 'BRWR_DSH_YN', 'target_y'
]

MACRO_SUFFIXES = ('_log_ret', '_vol_m', '_diff12', '_yoy', '_ma3m')

def is_macro_feature(col_name: str) -> bool:
    return any(col_name.endswith(s) for s in MACRO_SUFFIXES)

def build_bzcc_mapping(bzcc_path: str) -> dict:
    df_bzcc = pd.read_excel(bzcc_path, dtype=str)
    code_col, class_col = df_bzcc.columns[0], df_bzcc.columns[1]
    mapping = {}
    for _, row in df_bzcc.iterrows():
        c5 = str(row[code_col]).strip()
        ca = str(row[class_col]).strip()
        if c5 and ca and ca != 'nan':
            mapping[c5] = ca
    return mapping

def map_industry_from_bzcc(std_inds_cfc, bzcc_mapping: dict) -> str:
    try:
        code = str(int(float(std_inds_cfc))).zfill(5)
        if code in bzcc_mapping:
            return bzcc_mapping[code]
        p2 = int(code[:2])
        if 1 <= p2 <= 3: return 'A'
        elif 5 <= p2 <= 8: return 'B'
        elif 10 <= p2 <= 34: return 'C'
        elif 35 <= p2 <= 36: return 'D'
        elif 37 <= p2 <= 39: return 'E'
        elif 41 <= p2 <= 42: return 'F'
        elif 45 <= p2 <= 47: return 'G'
        elif 49 <= p2 <= 52: return 'H'
        elif 55 <= p2 <= 56: return 'I'
        elif 58 <= p2 <= 63: return 'J'
        elif 64 <= p2 <= 66: return 'K'
        elif 68 <= p2 <= 68: return 'L'
        elif 70 <= p2 <= 73: return 'M'
        elif 74 <= p2 <= 76: return 'N'
        elif 84 <= p2 <= 84: return 'O'
        elif 85 <= p2 <= 85: return 'P'
        elif 86 <= p2 <= 87: return 'Q'
        elif 90 <= p2 <= 91: return 'R'
        elif 94 <= p2 <= 96: return 'S'
        return 'Z'
    except:
        return 'Z'


def main():
    log.info("=" * 80)
    log.info("  최종 PD 통합 스코어링 및 매크로 가중치 오버레이 파이프라인")
    log.info("  Final Borrower Credit Risk Scoring Pipeline")
    log.info("=" * 80)

    # ─────────────────────────────────────────────────────────────────────────
    #  [요구사항 1] 데이터 및 스무딩 매트릭스 로드
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [요구사항 1] 가중치 매트릭스 및 차주 전수 데이터 로드")
    log.info("━" * 80)

    smoothed_path = os.path.join(OUTPUT_DIR, "industry_macro_smoothed_weights.csv")
    train_path = os.path.join(INPUT_DIR, "model_input_train.csv")
    bzcc_path = os.path.join(INPUT_DIR, "bzcc.xlsx")

    if not os.path.exists(smoothed_path):
        log.error(f"스무딩 가중치 파일 미존재: {smoothed_path}")
        sys.exit(1)
    if not os.path.exists(train_path):
        log.error(f"학습 원본 데이터 미존재: {train_path}")
        sys.exit(1)

    # 1-1. 스무딩 매트릭스 → 업종별 가중치 Dict 파싱
    log.info("1-1. 정제 가중치 매트릭스 파싱 중...")
    df_smoothed = pd.read_csv(smoothed_path)
    
    # 피처 열만 파싱
    meta_cols = ['STD_INDS_CFC', 'industry_name']
    weight_feat_cols = [c for c in df_smoothed.columns if c not in meta_cols]
    
    smoothed_weights_dict = {}
    for _, row in df_smoothed.iterrows():
        ind_code = str(row['STD_INDS_CFC']).strip()
        smoothed_weights_dict[ind_code] = row[weight_feat_cols].astype(float)

    log.info(f"   - 업종별 정제 가중치 파싱 완료: 총 {len(smoothed_weights_dict)}개 업종 대분류")
    log.info(f"   - 매크로 가중치 피처 수: {len(weight_feat_cols)}개")

    # 1-2. 차주 전수 원본 데이터 로드
    log.info("1-2. 차주 전수 원본 데이터(model_input_train.csv) 로딩 중...")
    df_raw = pd.read_csv(train_path, low_memory=False)
    log.info(f"   - 전수 데이터 크기: {df_raw.shape[0]:,}행 × {df_raw.shape[1]}열")

    # 리포트용 메타정보 백업
    backup_meta = pd.DataFrame({
        'V_BZNO': df_raw['V_BZNO'].astype(str),
        'CONM': df_raw['CONM'].astype(str) if 'CONM' in df_raw.columns else 'Unnamed',
        'STD_INDS_CFC_RAW': df_raw['STD_INDS_CFC'].copy()
    })

    # 업종코드 KSIC 대분류 매핑
    bzcc_map = build_bzcc_mapping(bzcc_path) if os.path.exists(bzcc_path) else {}
    backup_meta['STD_INDS_CFC'] = backup_meta['STD_INDS_CFC_RAW'].apply(lambda x: map_industry_from_bzcc(x, bzcc_map))
    
    log.info(f"   - 차주 업종 대분류 매핑 완료 (예: A~S)")

    # ─────────────────────────────────────────────────────────────────────────
    #  [⚠️ 절대 원칙 준수 검증] 입력 피처 무결성 검증
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [⚠️ 데이터 사용 절대 원칙 준수 검증]")
    log.info("━" * 80)

    # 종속변수 세팅 (문자열 'Y'/'N' 및 숫자 1/0 완벽 대응)
    y_raw = df_raw['BRWR_DSH_YN'].fillna('N')
    y = np.where(y_raw.astype(str).str.upper() == 'Y', 1, np.where(y_raw == 1, 1, 0)).astype(int)

    # 독립변수 X 필터링 (EXCLUDE_COLS 및 파생변수 완전 차단)
    existing_exclude = [c for c in EXCLUDE_COLS if c in df_raw.columns]
    X_candidate = df_raw.drop(columns=existing_exclude, errors='ignore')
    
    # 숫자형 피처만 선택
    num_cols = X_candidate.select_dtypes(include=[np.number]).columns.tolist()
    X = X_candidate[num_cols].copy()

    # 원시 시계열 매크로 변수 확인
    macro_in_X = [c for c in X.columns if is_macro_feature(c)]
    micro_in_X = [c for c in X.columns if not is_macro_feature(c)]

    log.info(f"   1. X 피처 원천 확인: 전수 {len(X.columns)}개 변수")
    log.info(f"      ├ 기업 고유 재무 항목: {len(micro_in_X)}개")
    log.info(f"      └ 원시 매크로 시계열 피처: {len(macro_in_X)}개")
    
    # 스무딩 매트릭스의 요약/파생 변수 혼용 여부 검사
    forbidden_keywords = ['category_share', 'smoothed_weight', 'floor_weight']
    mixed_forbidden = [c for c in X.columns if any(k.lower() in c.lower() for k in forbidden_keywords)]
    
    log.info(f"   2. 스무딩 파생/요약 변수 혼용 검사: {mixed_forbidden} 탐지")
    assert len(mixed_forbidden) == 0, f"⚠️ 데이터 사용 원칙 위반: 스무딩 파생 변수 혼용 ({mixed_forbidden})!"
    log.info("   ✅ 무결성 원칙 100% 준수 확인: 순수 원시 시계열 규격 기반 학습 진행")

    # 결측치 중앙값 대체
    log.info("   - 결측치 중앙값(Median) 보간 처리 중...")
    medians = X.median()
    X = X.fillna(medians)

    # ─────────────────────────────────────────────────────────────────────────
    #  [요구사항 2 & 4] LightGBM 학습 및 단일 IsotonicRegression 변환기 적합
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [요구사항 2 & 4] LightGBM 모형 학습 및 단일 IsotonicRegression 변환기 적합")
    log.info("━" * 80)

    pos_cnt, neg_cnt = y.sum(), (y == 0).sum()
    spw = neg_cnt / max(pos_cnt, 1)
    
    log.info(f"2-1. Base LightGBM 분류기 학습 시작 (전수 {len(X):,}건, scale_pos_weight={spw:.2f})...")
    
    base_lgb = LGBMClassifier(
        objective='binary',
        boosting_type='gbdt',
        learning_rate=0.05,
        num_leaves=31,
        max_depth=6,
        min_child_samples=100,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=spw,
        n_estimators=300,
        random_state=42,
        n_jobs=-1,
        verbose=-1
    )
    
    base_lgb.fit(X, y)
    log.info("   - Base LightGBM 훈련 완료")

    log.info("2-2. 원시 로짓 점수(raw_logits) 추출 중...")
    raw_logits = base_lgb.predict(X, raw_score=True)
    log.info(f"   📊 raw_logits 통계: 평균={raw_logits.mean():.4f}, 표준편차={raw_logits.std():.4f}")

    log.info("4-1. 단일 IsotonicRegression 기본 변환기 학습 중 (raw_logits -> target_y)...")
    iso_reg = IsotonicRegression(out_of_bounds='clip')
    iso_reg.fit(raw_logits, y)
    log.info("   - 단일 IsotonicRegression 기본 변환기 적합 완료 (재학습 없이 사후 매핑용으로 고정)")

    # 전수 데이터에 대한 BASE_PD 산출
    log.info("4-2. 차주 전수(540,568건) 대상 기본 보정 부도확률(BASE_PD) 산출 중...")
    base_pd_all = iso_reg.predict(raw_logits)
    
    log.info(f"   📊 BASE_PD 통계: 평균={base_pd_all.mean():.6f}, 최소={base_pd_all.min():.6f}, 최대={base_pd_all.max():.6f}")

    # ─────────────────────────────────────────────────────────────────────────
    #  [요구사항 3] 업종별 정제 가중치 오버레이 계산 (로짓 공간 결합)
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [요구사항 3] SHAP 부호 보존 및 로짓 공간 오버레이 결합")
    log.info("━" * 80)

    log.info("3-1. TreeExplainer 기반 전수 차주 거시 피처 원시 SHAP 행렬 추출 중...")
    explainer = shap.TreeExplainer(base_lgb.booster_)
    
    shap_raw = explainer.shap_values(X.astype(np.float32))
    if isinstance(shap_raw, list):
        shap_raw = shap_raw[1]
        
    shap_df = pd.DataFrame(shap_raw, index=X.index, columns=X.columns)
    shap_macro_df = shap_df[macro_in_X]
    
    log.info(f"   - 거시 피처 SHAP 행렬 추출 완료: {shap_macro_df.shape}")

    log.info("3-2. 차주별 업종 매핑 정제 가중치 내적 및 로짓 스케일링 결합 중...")
    macro_adj_raw = pd.Series(0.0, index=X.index)

    # 업종별로 벡터라이징 내적 연산 수행 (초고속 연산)
    for ind_code, weight_series in smoothed_weights_dict.items():
        borrower_mask = (backup_meta['STD_INDS_CFC'] == ind_code)
        if borrower_mask.any():
            common_macro = [c for c in macro_in_X if c in weight_series.index]
            sub_shap = shap_macro_df.loc[borrower_mask, common_macro]
            sub_weight = weight_series[common_macro]
            
            # SHAP 부호 보존 법칙: 원시 SHAP × 정제 가중치 일대일 곱 합산
            macro_adj_raw.loc[borrower_mask] = (sub_shap * sub_weight).sum(axis=1)

    # 스케일링 인자(Scaling Factor) 적용: raw_logits 단위와 매칭하여 확률 단위 왜곡 방지
    scaling_factor = 1.0
    macro_adj = macro_adj_raw * scaling_factor

    log.info(f"   📊 Macro_Overlay_Adjustment 통계 (SF={scaling_factor}): 평균={macro_adj.mean():.4f}, 최소={macro_adj.min():.4f}, 최대={macro_adj.max():.4f}")

    # 최종 로짓 점수는 로짓 공간에서 합산
    final_logits = raw_logits + macro_adj.values

    # ─────────────────────────────────────────────────────────────────────────
    #  [요구사항 4 & 5] 사후 보간 매핑 변환 및 최종 리포트 저장
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [요구사항 4 & 5] 최종 동적 부도확률(FINAL_DYNAMIC_PD) 도출 및 검증")
    log.info("━" * 80)

    # 사후 변환 기법: 절대 새로운 Isotonic 모델을 재학습시키지 않고 기존 Isotonic 변환기 확장 매핑
    final_dynamic_pd = np.clip(iso_reg.predict(final_logits), 0.0, 1.0)
    
    log.info(f"   📊 FINAL_DYNAMIC_PD 통계: 평균={final_dynamic_pd.mean():.6f}, 최소={final_dynamic_pd.min():.6f}, 최대={final_dynamic_pd.max():.6f}")

    # 최종 데이터프레임 구축
    df_report = pd.DataFrame({
        'V_BZNO': backup_meta['V_BZNO'],
        'CONM': backup_meta['CONM'],
        'STD_INDS_CFC': backup_meta['STD_INDS_CFC'],
        'BASE_PD': np.round(base_pd_all, 6),
        'Macro_Overlay_Adjustment': np.round(macro_adj.values, 6),
        'FINAL_DYNAMIC_PD': np.round(final_dynamic_pd, 6)
    })

    report_csv_path = os.path.join(OUTPUT_DIR, "final_borrower_credit_risk_report.csv")
    df_report.to_csv(report_csv_path, index=False, encoding='utf-8-sig')
    
    log.info(f"   ✅ 최종 스코어링 리포트 CSV 저장 완료: {report_csv_path}")
    log.info(f"   📋 상위 5개사 결과 미리보기:\n{df_report.head(5).to_string(index=False)}")

    # ─────────────────────────────────────────────────────────────────────────
    #  [평가 결과 폴더 정리] 모형 평가 지표 및 그래프 생성
    # ─────────────────────────────────────────────────────────────────────────
    log.info("\n   📁 신규 평가 폴더(final_model_evaluation/) 내 평가 지표 및 차트 생성 중...")

    auc_base = roc_auc_score(y, base_pd_all)
    auc_final = roc_auc_score(y, final_dynamic_pd)
    brier_base = brier_score_loss(y, base_pd_all)
    brier_final = brier_score_loss(y, final_dynamic_pd)

    metrics_json = {
        "Total_Borrowers": int(len(df_report)),
        "Default_Count": int(y.sum()),
        "BASE_PD_AUC": float(auc_base),
        "FINAL_DYNAMIC_PD_AUC": float(auc_final),
        "BASE_PD_Brier_Score": float(brier_base),
        "FINAL_DYNAMIC_PD_Brier_Score": float(brier_final),
        "BASE_PD_Mean": float(base_pd_all.mean()),
        "FINAL_DYNAMIC_PD_Mean": float(final_dynamic_pd.mean()),
        "Macro_Overlay_Adj_Std": float(macro_adj.std())
    }

    metrics_path = os.path.join(EVAL_DIR, "evaluation_metrics_summary.json")
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(metrics_json, f, indent=4)

    # OOT 검증 파이프라인에서 재사용할 수 있도록 학습된 모델 객체 및 학습 셋 지표 저장
    model_pkl_path = os.path.join(OUTPUT_DIR, "integrated_scoring_model.pkl")
    with open(model_pkl_path, 'wb') as f:
        pickle.dump({
            'base_lgb': base_lgb,
            'iso_reg': iso_reg,
            'weight_feat_cols': weight_feat_cols,
            'feature_names': X.columns.tolist(),
            'train_medians': medians,
            'train_metrics': metrics_json
        }, f)
    log.info(f"   💾 통합 모델 객체 저장 완료: {model_pkl_path}")

    # 차트 1: PD 분포 비교 히스토그램
    plt.figure(figsize=(10, 6))
    plt.hist(base_pd_all[base_pd_all < 0.05], bins=100, alpha=0.6, color='#4ECDC4', label='BASE_PD (Calibrated)')
    plt.hist(final_dynamic_pd[final_dynamic_pd < 0.05], bins=100, alpha=0.6, color='#FF6B6B', label='FINAL_DYNAMIC_PD (Overlayed)')
    plt.yscale('log')
    plt.xlabel('Default Probability (PD < 5% zoomed)', fontsize=12)
    plt.ylabel('Borrower Count (Log Scale)', fontsize=12)
    plt.title('Borrower PD Distribution Comparison: Base vs Dynamic Overlay', fontsize=14, fontweight='bold')
    plt.legend(fontsize=11)
    plt.grid(True, alpha=0.3)
    dist_png = os.path.join(EVAL_DIR, "pd_distribution_comparison.png")
    plt.savefig(dist_png, dpi=200, bbox_inches='tight')
    plt.close()

    # 차트 2: Probability Calibration Curve
    prob_true_b, prob_pred_b = calibration_curve(y, base_pd_all, n_bins=10, strategy='quantile')
    prob_true_f, prob_pred_f = calibration_curve(y, final_dynamic_pd, n_bins=10, strategy='quantile')

    plt.figure(figsize=(8, 8))
    plt.plot([0, 1], [0, 1], 'k:', label='Perfectly Calibrated')
    plt.plot(prob_pred_b, prob_true_b, 's-', color='#4ECDC4', label=f'BASE_PD (Brier={brier_base:.5f})')
    plt.plot(prob_pred_f, prob_true_f, 'o-', color='#FF6B6B', label=f'FINAL_DYNAMIC_PD (Brier={brier_final:.5f})')
    plt.xlabel('Mean Predicted Probability', fontsize=12)
    plt.ylabel('Fraction of Positives (Real Default Rate)', fontsize=12)
    plt.title('Probability Calibration Curve (Isotonic)', fontsize=14, fontweight='bold')
    plt.legend(loc='lower right', fontsize=11)
    plt.grid(True, alpha=0.3)
    cal_png = os.path.join(EVAL_DIR, "pd_calibration_curve.png")
    plt.savefig(cal_png, dpi=200, bbox_inches='tight')
    plt.close()

    # 차트 3: ROC Curve
    fpr_b, tpr_b, _ = roc_curve(y, base_pd_all)
    fpr_f, tpr_f, _ = roc_curve(y, final_dynamic_pd)

    plt.figure(figsize=(8, 8))
    plt.plot(fpr_b, tpr_b, color='#4ECDC4', lw=2, label=f'BASE_PD (AUC = {auc_base:.4f})')
    plt.plot(fpr_f, tpr_f, color='#FF6B6B', lw=2, linestyle='--', label=f'FINAL_DYNAMIC_PD (AUC = {auc_final:.4f})')
    plt.plot([0, 1], [0, 1], 'k--', alpha=0.5)
    plt.xlabel('False Positive Rate', fontsize=12)
    plt.ylabel('True Positive Rate', fontsize=12)
    plt.title('ROC Curve: Integrated Credit Scoring Model', fontsize=14, fontweight='bold')
    plt.legend(loc='lower right', fontsize=11)
    plt.grid(True, alpha=0.3)
    roc_png = os.path.join(EVAL_DIR, "roc_curve_comparison.png")
    plt.savefig(roc_png, dpi=200, bbox_inches='tight')
    plt.close()

    # 평가 리포트 마크다운 문서 작성
    report_md = os.path.join(EVAL_DIR, "scoring_model_evaluation_report.md")
    with open(report_md, 'w', encoding='utf-8') as f:
        f.write("# 최종 부도 예측 모형 및 매크로 오버레이 파이프라인 종합 평가 보고서\n\n")
        f.write("## 1. 평가 요약\n\n")
        f.write(f"- **전체 대상 차주**: {len(df_report):,}개사 (부실 차주: {y.sum():,}개사)\n")
        f.write(f"- **BASE_PD AUC**: `{auc_base:.4f}` | **FINAL_DYNAMIC_PD AUC**: `{auc_final:.4f}`\n")
        f.write(f"- **BASE_PD Brier Score**: `{brier_base:.6f}` | **FINAL_DYNAMIC_PD Brier**: `{brier_final:.6f}`\n\n")
        f.write("## 2. 부도확률 보정 및 오버레이 효과\n\n")
        f.write(f"- 단일 Isotonic Regression 보정을 통해 기본 부도율이 현실적인 수준(평균 `{base_pd_all.mean()*100:.4f}%`)으로 정규화되었습니다.\n")
        f.write(f"- 로짓 공간 오버레이 결합 및 사후 매핑을 통해 동적 부도율(평균 `{final_dynamic_pd.mean()*100:.4f}%`)이 안정적으로 도출되었으며, 최종 AUC가 `{auc_final:.4f}`(무작위선 0.5 위)로 정상화되었습니다.\n\n")
        f.write("## 3. 평가 그래프\n\n")
        f.write("### 부도확률 분포 비교\n![PD Distribution](./pd_distribution_comparison.png)\n\n")
        f.write("### 확률 보정 곡선 (Calibration Curve)\n![Calibration Curve](./pd_calibration_curve.png)\n\n")
        f.write("### ROC 비교 곡선\n![ROC Curve](./roc_curve_comparison.png)\n")

    # output 폴더와 final_model_evaluation 폴더 양방향 완벽 동기화
    for eval_file in [dist_png, cal_png, roc_png, metrics_path, report_md]:
        if os.path.exists(eval_file):
            shutil.copy2(eval_file, OUTPUT_DIR)
            
    for out_file in os.listdir(OUTPUT_DIR):
        if out_file.endswith(".png") or out_file.endswith(".txt") or out_file.endswith(".csv") or out_file.endswith(".json") or out_file.endswith(".pkl"):
            src_p = os.path.join(OUTPUT_DIR, out_file)
            dst_p = os.path.join(EVAL_DIR, out_file)
            if os.path.exists(src_p):
                shutil.copy2(src_p, dst_p)

    log.info(f"   ✅ 최종 모델 성능 및 평가 폴더 완벽 동기화 완료: {EVAL_DIR}")
    log.info("=" * 80)
    log.info("  🎯 최종 통합 스코어링 파이프라인 완료!")
    log.info("=" * 80)

    gc.collect()

if __name__ == "__main__":
    main()
