"""모델 검증 스위트(docs/step28) 공통 로더/지표 유틸.

패널은 6.76GB 원본 CSV 대신 DuckDB 의 corporate_panel 테이블에서 읽는다.
필요한 컬럼만 push-down projection + FLOAT 캐스트로 당겨오므로 메모리가 견딘다.

DB 는 두 개가 병존한다.
  legacy(portal.duckdb)    구 스키마. lgbm_12m_model.txt 를 만든 모집단 그대로.
                           S0(기존 파이프라인 재현) 평가에만 쓴다. 읽기 전용.
  v2(portal_v2.duckdb)     신 스키마. STAGE 5 까지의 패널 정정이 반영된 기본 DB.
                           S1~S9 가 여기를 본다.
어느 쪽도 이 모듈에서 쓰지 않는다. 연결은 예외 없이 read_only=True 다.
경로는 전부 eda_pipeline/config.py 를 경유한다.
"""
import gc
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import lightgbm as lgb
import numpy as np
from scipy.stats import ks_2samp
from sklearn.metrics import roc_auc_score

from eda_pipeline import config

# 경로는 전부 config 경유다. 하드코딩 절대경로를 두지 않는다
# (예전 값은 C:/Users/User/model_kbm/... 로, 이 계정에서는 열리지 않았다).
#
# DB 는 구/신 스키마가 병존한다. 기본값은 신 스키마(portal_v2.duckdb)이고,
# S0(기존 파이프라인 재현)만 which='legacy' 로 구 스키마를 본다.
# 없는 파일로 조용히 폴백하지 않는다 — config.require_db 가 예외를 던진다.
DB_PATH = config.DB_PATH                      # = config.DB_PATH_V2
DB_PATH_LEGACY = config.DB_PATH_LEGACY
DB_PATH_V2 = config.DB_PATH_V2

# legacy 2건은 읽기 전용 보호 대상이다 (config.PROTECTED_MODELS).
FULL_MODEL_PATH = config.MODEL_PATH_LEGACY_FULL
LEAN_MODEL_PATH = config.MODEL_PATH_LEGACY_LEAN

OUTPUT_DIR = str(config.VALIDATION_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Only OBV_ELYWRN_OBV_GRD_DSC is a true categorical feature in the production model (A/B).
# STD_INDS_CFC is stored numerically in corporate_panel (industry code as DOUBLE), matching
# the production model's feature_infos (bracketed numeric range, not a category-code list).
CATEGORICAL_COLS = ['OBV_ELYWRN_OBV_GRD_DSC']

# The production training script (step7_modeling_shap.py) early-stops directly against the
# same VALID split it later reports as the final metric. To get an unbiased read, we carve a
# Dev slice out of the tail of TRAIN for early stopping and keep VALID untouched until the
# very last, single evaluation call.
# 경계는 eda_pipeline/split_spec.py 한 곳에만 둔다 (step7 / Ablation 러너와 공유).
from eda_pipeline.split_spec import (DEV_START_INT as DEV_START,
                                     DEV_END_INT as DEV_END,
                                     TRAIN_END_INT as TRAIN_END,
                                     VALID_START_INT as VALID_START)


def full_feature_list():
    return lgb.Booster(model_file=str(FULL_MODEL_PATH)).feature_name()


def lean_feature_list():
    return lgb.Booster(model_file=str(LEAN_MODEL_PATH)).feature_name()


def load_panel(feature_cols, base_ym_min=None, base_ym_max=None, which='v2'):
    """Pull V_BZNO/BASE_YM/SPLIT/IS_BUDO_12M + feature_cols from corporate_panel.

    which: 'v2'(신 스키마, S1~S9 기본) | 'legacy'(구 스키마, S0 전용).

    Numeric feature columns are cast to FLOAT (4-byte) in SQL so the pandas frame that comes
    back is roughly half the size of the DOUBLE-precision source columns.
    """
    con = config.connect_db(which)          # read_only=True. 예외 없다.
    select_parts = ['V_BZNO', 'BASE_YM', 'SPLIT', 'IS_BUDO_12M']
    for c in feature_cols:
        if c in CATEGORICAL_COLS:
            select_parts.append(f'"{c}"')
        else:
            select_parts.append(f'CAST("{c}" AS FLOAT) AS "{c}"')
    where = []
    if base_ym_min is not None:
        where.append(f'BASE_YM >= {base_ym_min}')
    if base_ym_max is not None:
        where.append(f'BASE_YM <= {base_ym_max}')
    where_sql = f"WHERE {' AND '.join(where)}" if where else ''
    sql = f'SELECT {", ".join(select_parts)} FROM {config.PANEL_TABLE} {where_sql}'
    df = con.execute(sql).fetchdf()
    con.close()
    for c in CATEGORICAL_COLS:
        if c in df.columns:
            df[c] = df[c].astype('category')
    df['IS_BUDO_12M'] = df['IS_BUDO_12M'].astype('int8')
    return df


def three_way_split(df, dev_start=DEV_START, dev_end=DEV_END, valid_start=VALID_START):
    """Train(<dev_start) / Dev(dev_start..dev_end, early-stopping only) / Valid(>=valid_start, true holdout)."""
    train_mask = df['BASE_YM'] < dev_start
    dev_mask = (df['BASE_YM'] >= dev_start) & (df['BASE_YM'] <= dev_end)
    valid_mask = df['BASE_YM'] >= valid_start
    return df[train_mask].copy(), df[dev_mask].copy(), df[valid_mask].copy()


def calculate_ks(y_true, y_prob):
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    prob_bad = y_prob[y_true == 1]
    prob_good = y_prob[y_true == 0]
    return float(ks_2samp(prob_good, prob_bad).statistic)


def calculate_psi(expected, actual, bins=10):
    expected = np.asarray(expected)
    actual = np.asarray(actual)
    bin_edges = np.quantile(expected, np.linspace(0, 1, bins + 1))
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf
    eps = 1e-4
    expected_pct = np.empty(bins)
    actual_pct = np.empty(bins)
    for i in range(bins):
        expected_pct[i] = max(np.mean((expected >= bin_edges[i]) & (expected < bin_edges[i + 1])), eps)
        actual_pct[i] = max(np.mean((actual >= bin_edges[i]) & (actual < bin_edges[i + 1])), eps)
    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))


def evaluate(y_true, y_prob):
    auc = roc_auc_score(y_true, y_prob)
    return {
        'auc': auc,
        'gini': 2 * auc - 1,
        'ks': calculate_ks(y_true, y_prob),
    }


def make_dataset(df, feature_cols, reference=None):
    X = df[feature_cols]
    y = df['IS_BUDO_12M']
    return lgb.Dataset(X, label=y, categorical_feature=[c for c in CATEGORICAL_COLS if c in feature_cols],
                        reference=reference, free_raw_data=True)


def free(*objs):
    for o in objs:
        del o
    gc.collect()
