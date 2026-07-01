"""
train_and_analyze.py
====================
신용평가 모형 구축 및 업종별 매크로 리스크 가중치 매트릭스 도출 통합 파이프라인

[1단계] 데이터 전처리 및 타깃 변수 정의
[2단계] LightGBM 모형 학습 (scale_pos_weight)
[3단계] SHAP Value 추출 → 업종별 매크로 리스크 가중치 매트릭스 산출

입력:
  - model_building/input/model_input_train.csv
  - model_building/input/bzcc.xlsx

출력:
  - output/lgbm_credit_model.pkl            (학습된 모델)
  - output/lgbm_credit_model.txt            (모델 텍스트 덤프)
  - output/industry_macro_shap_weights.csv  (업종별 매크로 가중치 매트릭스)
  - output/feature_importance.png           (피처 중요도 시각화)
  - output/shap_summary_dot.png             (SHAP beeswarm plot)
  - output/industry_macro_heatmap.png       (업종별 히트맵)
  - output/model_evaluation.txt             (모델 평가 결과 텍스트)
"""

import os
import sys
import pickle
import logging
import warnings
import gc

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # GUI 팝업 방지
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

import lightgbm as lgb
import shap
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, classification_report, roc_curve
from sklearn.preprocessing import MinMaxScaler

warnings.filterwarnings('ignore')

# ─── 경로 및 로깅 설정 ───
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
INPUT_DIR = os.path.join(_SCRIPT_DIR, "input")
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(OUTPUT_DIR, "train_and_analyze.log"),
            mode='w', encoding='utf-8'
        )
    ]
)
log = logging.getLogger(__name__)

# ─── 한글 폰트 설정 (Windows) ───
def setup_korean_font():
    """matplotlib 한글 깨짐 방지를 위한 폰트 설정"""
    font_candidates = ['Malgun Gothic', 'NanumGothic', 'AppleGothic']
    for font_name in font_candidates:
        font_path = fm.findfont(fm.FontProperties(family=font_name))
        if font_path and 'fallback' not in font_path.lower():
            plt.rcParams['font.family'] = font_name
            plt.rcParams['axes.unicode_minus'] = False
            return
    # fallback: 기본 설정 유지
    plt.rcParams['axes.unicode_minus'] = False

setup_korean_font()


# ═══════════════════════════════════════════════════════════════════════════════
#  상수 정의
# ═══════════════════════════════════════════════════════════════════════════════

# 학습에서 제외할 컬럼 (식별자, 문자열, 외부등급 등)
EXCLUDE_COLS = [
    'V_BZNO', 'CONM', 'ETB_DT', 'COPR_OPNP_C', 'BZSCAL_C',
    'DSH_DT', 'DSH_RSN_DSC', 'NMLZ_DT', 'NMLZ_YN',
    'CRI_GRD', 'KIS_LS_FNA_MKS', 'CRDEVL_PTTP_DSC', 'LS_NICS_GRDC',
    'AUD_OPI_DSC', 'CRI_GRD_ORD', 'V_BZNO_1', 'BASE_YM',
    'ELYWRN_OBV_GRD_DSC', 'EXT_PROD_RECORD_YN', 'CRINF_RLR_DSC',
    'CRDBD_RSNC', 'MAX(CRDBD_RLS_RSNC)',
    'STD_INDS_CFC',   # 업종코드 - 별도 백업 후 제외
    'BRWR_DSH_YN',    # 타깃 변수 원본
]

# 거시경제 피처 식별 접미사 패턴
MACRO_SUFFIXES = ('_log_ret', '_vol_m', '_diff12', '_yoy', '_ma3m')


def is_macro_feature(col_name: str) -> bool:
    """컬럼명이 거시경제 피처인지 판별"""
    return any(col_name.endswith(suffix) for suffix in MACRO_SUFFIXES)


def build_bzcc_mapping(bzcc_path: str) -> dict:
    """
    bzcc.xlsx에서 표준산업분류코드 → 대분류(알파벳 코드 + 명칭) 매핑 딕셔너리 생성
    첫 번째 컬럼: 5자리 세분류 코드
    두 번째 컬럼: 대분류 알파벳 (A, B, C, ...)
    세 번째 컬럼: 대분류 명칭
    """
    df_bzcc = pd.read_excel(bzcc_path, dtype=str)
    # 컬럼명이 한글 인코딩 문제가 있을 수 있으므로 위치 기반으로 접근
    code_col = df_bzcc.columns[0]  # 5자리 세분류 코드
    class_col = df_bzcc.columns[1]  # 대분류 알파벳
    name_col = df_bzcc.columns[2]   # 대분류 명칭

    mapping = {}
    for _, row in df_bzcc.iterrows():
        code_5digit = str(row[code_col]).strip()
        class_alpha = str(row[class_col]).strip()
        class_name = str(row[name_col]).strip()
        if code_5digit and class_alpha:
            mapping[code_5digit] = f"{class_alpha}"

    # 대분류 알파벳 → 명칭 매핑도 별도 구축
    alpha_to_name = {}
    for _, row in df_bzcc.iterrows():
        a = str(row[class_col]).strip()
        n = str(row[name_col]).strip()
        if a and a != 'nan':
            alpha_to_name[a] = n

    log.info(f"   - BZCC 매핑 구축 완료: {len(mapping):,}개 세분류 → {len(alpha_to_name)}개 대분류")
    return mapping, alpha_to_name


def map_industry_from_bzcc(std_inds_cfc, bzcc_mapping: dict) -> str:
    """STD_INDS_CFC 값을 bzcc 매핑을 통해 대분류 코드로 변환"""
    try:
        code = str(int(float(std_inds_cfc))).zfill(5)
        if code in bzcc_mapping:
            return bzcc_mapping[code]
        # 5자리 정확 매칭이 안 되면 앞 2자리로 대분류 범위 추론
        prefix2 = int(code[:2])
        if 1 <= prefix2 <= 3:
            return 'A'
        elif 5 <= prefix2 <= 8:
            return 'B'
        elif 10 <= prefix2 <= 34:
            return 'C'
        elif 35 <= prefix2 <= 36:
            return 'D'
        elif 37 <= prefix2 <= 39:
            return 'E'
        elif 41 <= prefix2 <= 42:
            return 'F'
        elif 45 <= prefix2 <= 47:
            return 'G'
        elif 49 <= prefix2 <= 52:
            return 'H'
        elif 55 <= prefix2 <= 56:
            return 'I'
        elif 58 <= prefix2 <= 63:
            return 'J'
        elif 64 <= prefix2 <= 66:
            return 'K'
        elif 68 <= prefix2 <= 68:
            return 'L'
        elif 70 <= prefix2 <= 73:
            return 'M'
        elif 74 <= prefix2 <= 76:
            return 'N'
        elif 84 <= prefix2 <= 84:
            return 'O'
        elif 85 <= prefix2 <= 85:
            return 'P'
        elif 86 <= prefix2 <= 87:
            return 'Q'
        elif 90 <= prefix2 <= 91:
            return 'R'
        elif 94 <= prefix2 <= 96:
            return 'S'
        else:
            return 'Z'
    except (ValueError, TypeError):
        return 'Z'


# ═══════════════════════════════════════════════════════════════════════════════
#  메인 파이프라인
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    log.info("=" * 80)
    log.info("  신용평가 모형 구축 및 업종별 매크로 리스크 가중치 매트릭스 도출")
    log.info("  Credit Risk Model & Industry Macro Risk Weight Matrix Pipeline")
    log.info("=" * 80)

    # ─────────────────────────────────────────────────────────────────────────
    #  [1단계] 데이터 전처리 및 타깃 변수 정의
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [1단계] 데이터 전처리 및 타깃 변수 정의")
    log.info("━" * 80)

    # 1-1. 데이터 로드
    train_path = os.path.join(INPUT_DIR, "model_input_train.csv")
    bzcc_path = os.path.join(INPUT_DIR, "bzcc.xlsx")

    if not os.path.exists(train_path):
        log.error(f"학습 데이터 파일 미존재: {train_path}")
        sys.exit(1)

    log.info("1-1. 학습 데이터 로딩 중...")
    df = pd.read_csv(train_path, low_memory=False)
    log.info(f"   - 원본 데이터 크기: {df.shape[0]:,}행 × {df.shape[1]}열")

    # 1-2. 타깃 변수 정의: BRWR_DSH_YN → target_y
    log.info("1-2. 타깃 변수(target_y) 정의 중...")
    # BRWR_DSH_YN: 1.0 → 1 (부실), NaN → 0 (정상)
    df['target_y'] = df['BRWR_DSH_YN'].fillna(0).astype(int)
    pos_count = (df['target_y'] == 1).sum()
    neg_count = (df['target_y'] == 0).sum()
    log.info(f"   - 정상(0): {neg_count:,}건 | 부실(1): {pos_count:,}건 | 부실률: {pos_count/(pos_count+neg_count)*100:.4f}%")

    # 1-3. 업종코드 백업 (STD_INDS_CFC)
    log.info("1-3. 업종코드(STD_INDS_CFC) 백업 중...")
    X_industry = df['STD_INDS_CFC'].copy()
    log.info(f"   - 유효 업종코드 수: {X_industry.notna().sum():,}건")

    # 1-4. BZCC 매핑 구축
    log.info("1-4. BZCC 업종 대분류 매핑 구축 중...")
    if os.path.exists(bzcc_path):
        bzcc_mapping, alpha_to_name = build_bzcc_mapping(bzcc_path)
        X_industry_class = X_industry.apply(lambda x: map_industry_from_bzcc(x, bzcc_mapping))
        industry_dist = X_industry_class.value_counts()
        log.info(f"   - 업종 대분류 분포:")
        for cls, cnt in industry_dist.items():
            name = alpha_to_name.get(cls, '기타')
            log.info(f"     {cls} ({name}): {cnt:,}건")
    else:
        log.warning(f"   - bzcc.xlsx 미존재, 업종코드 원본(STD_INDS_CFC) 그대로 사용")
        X_industry_class = X_industry.astype(str)
        alpha_to_name = {}

    # 1-5. 피처(X) 분리
    log.info("1-5. 학습 피처(X) 분리 중...")

    # 제외할 컬럼 + target_y
    drop_cols = EXCLUDE_COLS + ['target_y']
    # 데이터에 실제 존재하는 제외 컬럼만 필터
    existing_drop = [c for c in drop_cols if c in df.columns]

    X = df.drop(columns=existing_drop, errors='ignore')

    # 숫자형 컬럼만 유지
    numeric_cols = X.select_dtypes(include=[np.number]).columns.tolist()
    X = X[numeric_cols].copy()

    # 거시경제 vs 재무 피처 분류
    macro_features = [c for c in X.columns if is_macro_feature(c)]
    micro_features = [c for c in X.columns if not is_macro_feature(c)]
    log.info(f"   - 전체 학습 피처: {len(X.columns)}개")
    log.info(f"     ├ 재무 피처: {len(micro_features)}개")
    log.info(f"     └ 거시경제 피처: {len(macro_features)}개")

    # 1-6. 결측치 처리 (중앙값)
    log.info("1-6. 결측치 중앙값(Median) 대체 중...")
    nan_before = X.isna().sum().sum()
    medians = X.median()
    X = X.fillna(medians)
    nan_after = X.isna().sum().sum()
    log.info(f"   - 결측치 처리: {nan_before:,}개 → {nan_after}개")

    y = df['target_y']

    log.info(f"   ✅ [1단계 완료] 최종 학습 데이터: X={X.shape}, y={y.shape}")

    # ─────────────────────────────────────────────────────────────────────────
    #  [2단계] LightGBM 모형 학습
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [2단계] LightGBM 모형 학습 (scale_pos_weight 적용)")
    log.info("━" * 80)

    # 2-1. Train/Test 분리
    log.info("2-1. Train/Test 데이터 분리 중 (80:20, stratified)...")
    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, X.index,
        test_size=0.2,
        random_state=42,
        stratify=y
    )
    log.info(f"   - Train: {X_train.shape[0]:,}건 (부실: {y_train.sum():,}건)")
    log.info(f"   - Test:  {X_test.shape[0]:,}건 (부실: {y_test.sum():,}건)")

    # 2-2. scale_pos_weight 산출
    spw = neg_count / max(pos_count, 1)
    log.info(f"2-2. scale_pos_weight = {spw:.2f} (정상 {neg_count:,} / 부실 {pos_count:,})")

    # 2-3. LightGBM 모델 생성 및 학습
    log.info("2-3. LightGBM 분류기 학습 시작...")

    lgb_params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'learning_rate': 0.05,
        'num_leaves': 31,
        'max_depth': 6,
        'min_data_in_leaf': 100,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 1,
        'scale_pos_weight': spw,
        'verbose': -1,
        'random_state': 42,
        'n_jobs': -1,
    }

    train_data = lgb.Dataset(X_train, label=y_train)
    test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    model = lgb.train(
        lgb_params,
        train_data,
        num_boost_round=1000,
        valid_sets=[train_data, test_data],
        valid_names=['train', 'test'],
        callbacks=[
            lgb.early_stopping(50, verbose=False),
            lgb.log_evaluation(100),
        ]
    )

    # 2-4. 모델 평가
    log.info("2-4. 모델 성능 평가 중...")
    y_pred_proba = model.predict(X_test)
    y_pred_train = model.predict(X_train)

    auc_test = roc_auc_score(y_test, y_pred_proba)
    auc_train = roc_auc_score(y_train, y_pred_train)

    log.info("─" * 60)
    log.info(f"  📊 Train AUC: {auc_train:.4f}")
    log.info(f"  📊 Test  AUC: {auc_test:.4f}")
    log.info("─" * 60)

    # Classification Report (threshold=0.5)
    y_pred_label = (y_pred_proba >= 0.5).astype(int)
    report = classification_report(y_test, y_pred_label, target_names=['정상(0)', '부실(1)'], zero_division=0)
    log.info(f"\n{report}")

    # 2-5. 모델 저장
    log.info("2-5. 학습된 모델 저장 중...")
    model_pkl_path = os.path.join(OUTPUT_DIR, "lgbm_credit_model.pkl")
    model_txt_path = os.path.join(OUTPUT_DIR, "lgbm_credit_model.txt")

    with open(model_pkl_path, 'wb') as f:
        pickle.dump(model, f)
    with open(model_txt_path, 'w', encoding='utf-8') as f:
        f.write(model.model_to_string())

    log.info(f"   - PKL 저장: {model_pkl_path}")
    log.info(f"   - TXT 저장: {model_txt_path}")

    # 2-6. Feature Importance 시각화
    log.info("2-6. Feature Importance 시각화 중...")
    importance = model.feature_importance(importance_type='gain')
    feat_imp = pd.DataFrame({
        'feature': X.columns,
        'importance': importance
    }).sort_values('importance', ascending=False)

    top_n = min(30, len(feat_imp))
    top_feat = feat_imp.head(top_n)

    fig, ax = plt.subplots(figsize=(12, 8))
    colors = ['#FF6B6B' if is_macro_feature(f) else '#4ECDC4' for f in top_feat['feature']]
    ax.barh(range(top_n), top_feat['importance'].values, color=colors)
    ax.set_yticks(range(top_n))
    ax.set_yticklabels(top_feat['feature'].values, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel('Feature Importance (Gain)', fontsize=12)
    ax.set_title(f'LightGBM Feature Importance - Top {top_n}\n(Red=Macro, Teal=Micro/Financial)', fontsize=14, fontweight='bold')
    ax.grid(True, axis='x', alpha=0.3)
    plt.tight_layout()

    fi_path = os.path.join(OUTPUT_DIR, "feature_importance.png")
    plt.savefig(fi_path, dpi=200)
    plt.close()
    log.info(f"   - 저장 완료: {fi_path}")

    # 2-7. 평가 결과 텍스트 파일 저장
    eval_path = os.path.join(OUTPUT_DIR, "model_evaluation.txt")
    with open(eval_path, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("  LightGBM Credit Risk Model Evaluation Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"1. Data Summary\n")
        f.write(f"   - Total samples: {len(df):,}\n")
        f.write(f"   - Features: {len(X.columns)} (Micro: {len(micro_features)}, Macro: {len(macro_features)})\n")
        f.write(f"   - Default rate: {pos_count/(pos_count+neg_count)*100:.4f}%\n")
        f.write(f"   - scale_pos_weight: {spw:.2f}\n\n")
        f.write(f"2. Performance Metrics\n")
        f.write(f"   - Train AUC: {auc_train:.4f}\n")
        f.write(f"   - Test  AUC: {auc_test:.4f}\n\n")
        f.write(f"3. Classification Report (threshold=0.5)\n")
        f.write(report + "\n\n")
        f.write(f"4. Top 15 Feature Importance (Gain)\n")
        f.write("-" * 50 + "\n")
        for _, row in feat_imp.head(15).iterrows():
            marker = "[MACRO]" if is_macro_feature(row['feature']) else "[MICRO]"
            f.write(f"   {marker:8s} {row['feature']:45s} {row['importance']:>15,.0f}\n")
    log.info(f"   - 평가 결과 저장: {eval_path}")

    log.info(f"   ✅ [2단계 완료] Test AUC = {auc_test:.4f}")

    # ─────────────────────────────────────────────────────────────────────────
    #  [3단계] SHAP Value 추출 및 업종별 매크로 가중치 매트릭스 산출
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [3단계] SHAP 기반 업종별 매크로 리스크 가중치 매트릭스 산출")
    log.info("━" * 80)

    # 3-1. SHAP 계산
    log.info("3-1. TreeExplainer SHAP Values 계산 중 (전수 데이터 대상)...")
    explainer = shap.TreeExplainer(model)

    # 메모리 효율을 위해 최대 50,000건 샘플링
    MAX_SHAP_SAMPLES = 50000
    if len(X) > MAX_SHAP_SAMPLES:
        np.random.seed(42)
        sample_idx = np.random.choice(X.index, size=MAX_SHAP_SAMPLES, replace=False)
        X_shap = X.loc[sample_idx]
        industry_shap = X_industry_class.loc[sample_idx]
        log.info(f"   - SHAP 샘플링: {len(X):,}건 → {MAX_SHAP_SAMPLES:,}건")
    else:
        X_shap = X
        industry_shap = X_industry_class
        log.info(f"   - SHAP 전수 데이터: {len(X):,}건")

    shap_values = explainer.shap_values(X_shap)

    # shap_values가 list인 경우 (binary classification) → 양성 클래스 선택
    if isinstance(shap_values, list):
        shap_values = shap_values[1]

    shap_df = pd.DataFrame(shap_values, columns=X.columns, index=X_shap.index)
    log.info(f"   - SHAP values 행렬 크기: {shap_df.shape}")

    # 3-2. 거시경제 피처 SHAP만 필터링
    log.info("3-2. 거시경제 피처 SHAP 필터링 중...")
    macro_shap_cols = [c for c in shap_df.columns if is_macro_feature(c)]
    shap_macro = shap_df[macro_shap_cols]
    log.info(f"   - 거시경제 피처 SHAP 컬럼 수: {len(macro_shap_cols)}개")

    # 3-3. 업종별 Mean Absolute SHAP 산출
    log.info("3-3. 업종코드별 Mean Absolute SHAP 산출 중...")
    shap_macro_abs = shap_macro.abs()
    shap_macro_abs['industry_class'] = industry_shap.values

    # 업종코드별 그룹 평균
    industry_mean_abs_shap = shap_macro_abs.groupby('industry_class')[macro_shap_cols].mean()

    # 'Z' (미분류) 행이 있으면 제거
    if 'Z' in industry_mean_abs_shap.index:
        z_count = (industry_shap == 'Z').sum()
        log.info(f"   - 미분류(Z) 업종 {z_count:,}건 제외")
        industry_mean_abs_shap = industry_mean_abs_shap.drop('Z', errors='ignore')

    log.info(f"   - 업종 그룹 수: {len(industry_mean_abs_shap)}개")
    log.info(f"   - 거시경제 피처 수: {len(macro_shap_cols)}개")

    # 3-4. Min-Max 스케일링 → 0~1 가중치
    log.info("3-4. Min-Max 스케일링으로 가중치 정규화 중...")
    scaler = MinMaxScaler()
    weights_scaled = pd.DataFrame(
        scaler.fit_transform(industry_mean_abs_shap),
        index=industry_mean_abs_shap.index,
        columns=industry_mean_abs_shap.columns
    )
    weights_scaled.index.name = 'STD_INDS_CFC'

    # 업종 대분류 명칭 추가
    if alpha_to_name:
        weights_scaled.insert(0, 'industry_name',
                              weights_scaled.index.map(lambda x: alpha_to_name.get(x, '기타')))

    # 3-5. CSV 저장
    csv_path = os.path.join(OUTPUT_DIR, "industry_macro_shap_weights.csv")
    weights_scaled.to_csv(csv_path, encoding='utf-8-sig')
    log.info(f"   - 업종별 매크로 가중치 매트릭스 저장: {csv_path}")

    # 가중치 상위 출력
    log.info("\n   📋 업종별 매크로 가중치 매트릭스 미리보기 (상위 5개 피처):")
    top5_macro = industry_mean_abs_shap.mean().nlargest(5).index.tolist()
    preview = weights_scaled[['industry_name'] + top5_macro] if 'industry_name' in weights_scaled.columns else weights_scaled[top5_macro]
    log.info(f"\n{preview.to_string()}")

    # 3-6. 히트맵 시각화
    log.info("\n3-6. 업종별 매크로 리스크 가중치 히트맵 생성 중...")

    # 상위 20개 거시경제 피처만 시각화
    top_macro_cols = industry_mean_abs_shap.mean().nlargest(20).index.tolist()
    heatmap_data = weights_scaled[top_macro_cols] if 'industry_name' not in weights_scaled.columns else weights_scaled[top_macro_cols]

    # 인덱스에 명칭 추가
    if alpha_to_name:
        heatmap_labels = [f"{idx} ({alpha_to_name.get(idx, '기타')})" for idx in heatmap_data.index]
    else:
        heatmap_labels = list(heatmap_data.index)

    fig, ax = plt.subplots(figsize=(18, max(8, len(heatmap_labels) * 0.6)))
    im = ax.imshow(heatmap_data.values, cmap='YlOrRd', aspect='auto', vmin=0, vmax=1)

    ax.set_xticks(range(len(top_macro_cols)))
    ax.set_xticklabels(top_macro_cols, rotation=55, ha='right', fontsize=8)
    ax.set_yticks(range(len(heatmap_labels)))
    ax.set_yticklabels(heatmap_labels, fontsize=10)

    # 셀 값 어노테이션
    for i in range(len(heatmap_labels)):
        for j in range(len(top_macro_cols)):
            val = heatmap_data.values[i, j]
            color = 'white' if val > 0.6 else 'black'
            ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                    color=color, fontsize=7, fontweight='bold')

    plt.colorbar(im, label='Macro Risk Weight (0-1, Min-Max Scaled)', shrink=0.8)
    ax.set_title('Industry-Specific Macro Risk Weight Matrix\n(Mean |SHAP| → Min-Max Scaled)',
                 fontsize=14, fontweight='bold', pad=15)
    plt.tight_layout()

    heatmap_path = os.path.join(OUTPUT_DIR, "industry_macro_heatmap.png")
    plt.savefig(heatmap_path, dpi=200)
    plt.close()
    log.info(f"   - 히트맵 저장 완료: {heatmap_path}")

    # 3-7. SHAP beeswarm summary plot
    log.info("3-7. SHAP beeswarm summary plot 생성 중...")

    # 상위 30개 피처만 시각화 (가독성)
    plt.figure(figsize=(12, 10))
    shap.summary_plot(shap_values, X_shap, max_display=30, show=False)
    plt.title('SHAP Summary (Beeswarm) - Credit Risk Model', fontsize=14, fontweight='bold', pad=15)
    plt.tight_layout()

    dot_path = os.path.join(OUTPUT_DIR, "shap_summary_dot.png")
    plt.savefig(dot_path, dpi=200)
    plt.close()
    log.info(f"   - SHAP beeswarm plot 저장: {dot_path}")

    log.info(f"   ✅ [3단계 완료] 업종별 매크로 가중치 매트릭스 도출 성공")

    # ─────────────────────────────────────────────────────────────────────────
    #  최종 요약
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("=" * 80)
    log.info("  🎯 전체 파이프라인 실행 완료!")
    log.info("=" * 80)
    log.info(f"  [모델]     {model_pkl_path}")
    log.info(f"  [AUC]      Train={auc_train:.4f} | Test={auc_test:.4f}")
    log.info(f"  [매트릭스] {csv_path}")
    log.info(f"  [히트맵]   {heatmap_path}")
    log.info(f"  [SHAP]     {dot_path}")
    log.info(f"  [피처중요도] {fi_path}")
    log.info(f"  [평가리포트] {eval_path}")
    log.info("=" * 80)

    gc.collect()


if __name__ == "__main__":
    main()
