"""Shared data-loading and metric utilities for the model validation suite (docs/step28).

All experiments here read from database/portal.duckdb's corporate_panel table instead of
the 6.76GB source CSV (eda_pipeline/output/nh_panel_macro_12m.csv is not present in this
checkout, and free RAM on this machine is too tight to load the raw CSV with pandas anyway).
corporate_panel contains the exact same 1,944,418-row population and TRAIN/VALID SPLIT
boundary that produced eda_pipeline/output/lgbm_12m_model.txt, so pulling only the needed
columns through DuckDB (push-down projection, FLOAT cast) reproduces the original pipeline
without the memory blowup of loading the full CSV.
"""
import gc
import os

import duckdb
import lightgbm as lgb
import numpy as np
from scipy.stats import ks_2samp
from sklearn.metrics import roc_auc_score

DB_PATH = 'C:/Users/User/model_kbm/database/portal.duckdb'
FULL_MODEL_PATH = 'C:/Users/User/model_kbm/eda_pipeline/output/lgbm_12m_model.txt'
LEAN_MODEL_PATH = 'C:/Users/User/model_kbm/eda_pipeline/output/lgbm_12m_lean_model.txt'
OUTPUT_DIR = 'C:/Users/User/model_kbm/eda_pipeline/output/validation'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Only OBV_ELYWRN_OBV_GRD_DSC is a true categorical feature in the production model (A/B).
# STD_INDS_CFC is stored numerically in corporate_panel (industry code as DOUBLE), matching
# the production model's feature_infos (bracketed numeric range, not a category-code list).
CATEGORICAL_COLS = ['OBV_ELYWRN_OBV_GRD_DSC']

# The production training script (step7_modeling_shap.py) early-stops directly against the
# same VALID split it later reports as the final metric. To get an unbiased read, we carve a
# Dev slice out of the tail of TRAIN for early stopping and keep VALID untouched until the
# very last, single evaluation call.
DEV_START, DEV_END = 202310, 202312   # last 3 months of TRAIN
TRAIN_END = 202312                     # inclusive, matches production TRAIN boundary
VALID_START = 202401                   # matches production VALID boundary (true holdout)


def full_feature_list():
    return lgb.Booster(model_file=FULL_MODEL_PATH).feature_name()


def lean_feature_list():
    return lgb.Booster(model_file=LEAN_MODEL_PATH).feature_name()


def load_panel(feature_cols, base_ym_min=None, base_ym_max=None):
    """Pull V_BZNO/BASE_YM/SPLIT/IS_BUDO_12M + feature_cols from corporate_panel.

    Numeric feature columns are cast to FLOAT (4-byte) in SQL so the pandas frame that comes
    back is roughly half the size of the DOUBLE-precision source columns.
    """
    con = duckdb.connect(DB_PATH, read_only=True)
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
    sql = f'SELECT {", ".join(select_parts)} FROM corporate_panel {where_sql}'
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
