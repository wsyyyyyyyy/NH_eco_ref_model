"""[Follow-up] Full multicollinearity (VIF) check of the CURRENT production model.

step9_vif_zscore_tuning.py (the script that produced lgbm_12m_lean_model.txt) only ever ran
the VIF diet on the Top-100-by-gain subset of the 230 features, not the full feature set --
so ~130 lower-importance features in the Full(230) model were *never actually checked* for
multicollinearity. This script closes that gap with two checks:

  A) VIF among the 80 features currently deployed in the Lean model, computed on their own
     (do they still hold up as a mutually low-VIF set today?).
  B) A from-scratch VIF diet over *all* 228 numeric features of the Full(230) model (the 2
     categorical features, OBV_ELYWRN_OBV_GRD_DSC and STD_INDS_CFC, are excluded from VIF by
     construction, same as step9) -- revealing how much multicollinearity actually exists
     across the full feature set, independent of any prior importance-based pre-filtering.
"""
import json
import logging

import numpy as np
import pandas as pd

from validation_common import OUTPUT_DIR, full_feature_list, lean_feature_list, load_panel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

SAMPLE_SIZE = 100_000
MAX_VIF = 10.0
CATEGORICAL_EXCLUDE = {'OBV_ELYWRN_OBV_GRD_DSC', 'STD_INDS_CFC'}


def vif_diet(X, max_vif=MAX_VIF):
    """Iteratively drop the feature with the highest VIF until all remaining are <= max_vif.
    Returns (surviving_features, drop_log) where drop_log records each removal + its VIF.
    """
    X = X.copy().fillna(0)
    variances = X.var()
    zero_var = variances[variances == 0].index.tolist()
    if zero_var:
        logging.info(f"Dropping {len(zero_var)} zero-variance columns: {zero_var}")
        X = X.drop(columns=zero_var)

    remaining = list(X.columns)
    drop_log = []
    while len(remaining) > 1:
        corr_matrix = np.corrcoef(X[remaining].values, rowvar=False)
        try:
            inv_corr = np.linalg.inv(corr_matrix)
            vif_values = np.diag(inv_corr)
        except np.linalg.LinAlgError:
            logging.warning("Singular correlation matrix -- dropping the most correlated pair directly (|corr|>0.9)")
            corr = X[remaining].corr().abs()
            upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
            worst_col = upper.max().idxmax()
            worst_val = upper.max().max()
            drop_log.append({'feature': worst_col, 'vif': None, 'reason': f'singular_matrix_fallback(corr={worst_val:.3f})'})
            remaining.remove(worst_col)
            continue

        vif_series = pd.Series(vif_values, index=remaining)
        worst = vif_series.idxmax()
        if vif_series[worst] > max_vif:
            drop_log.append({'feature': worst, 'vif': float(vif_series[worst]), 'reason': 'vif_diet'})
            remaining.remove(worst)
        else:
            break
    final_vif = pd.Series(np.diag(np.linalg.inv(np.corrcoef(X[remaining].values, rowvar=False))), index=remaining)
    return remaining, drop_log, final_vif


def main():
    full_features = full_feature_list()
    lean_features = lean_feature_list()
    numeric_full = [f for f in full_features if f not in CATEGORICAL_EXCLUDE]
    numeric_lean = [f for f in lean_features if f not in CATEGORICAL_EXCLUDE]
    logging.info(f"Full model: {len(full_features)} features ({len(numeric_full)} numeric, "
                 f"{len(full_features) - len(numeric_full)} categorical excluded from VIF)")
    logging.info(f"Lean model: {len(lean_features)} features ({len(numeric_lean)} numeric)")

    logging.info(f"Loading a {SAMPLE_SIZE}-row Train sample with all {len(full_features)} features...")
    df = load_panel(full_features, base_ym_max=202312)
    sample = df.sample(n=min(SAMPLE_SIZE, len(df)), random_state=42)
    del df

    # --- Check A: does the CURRENTLY DEPLOYED Lean(80) set hold up as low-VIF on its own? ---
    logging.info("--- Check A: VIF among the 80 features currently in lgbm_12m_lean_model.txt ---")
    survivors_a, drop_log_a, final_vif_a = vif_diet(sample[numeric_lean])
    logging.info(f"Lean(80) numeric features: {len(numeric_lean)} checked, {len(survivors_a)} still <= VIF {MAX_VIF}, "
                 f"{len(drop_log_a)} would now be dropped")
    if drop_log_a:
        logging.info(f"Would-be-dropped from current Lean set: {json.dumps(drop_log_a, ensure_ascii=False, indent=2)}")

    # --- Check B: from-scratch VIF diet over ALL 228 numeric features of the Full model ---
    logging.info("--- Check B: from-scratch VIF diet over all 228 numeric features (Full model) ---")
    survivors_b, drop_log_b, final_vif_b = vif_diet(sample[numeric_full])
    logging.info(f"Full(230) numeric features: {len(numeric_full)} checked, {len(survivors_b)} survive VIF<={MAX_VIF}, "
                 f"{len(drop_log_b)} dropped for multicollinearity")

    drop_df_b = pd.DataFrame(drop_log_b)
    drop_df_b.to_csv(f'{OUTPUT_DIR}/step21_full_vif_drop_log.csv', index=False, encoding='utf-8-sig')

    overlap_with_current_lean = set(survivors_b) & set(numeric_lean)
    only_in_current_lean_not_survivor_b = set(numeric_lean) - set(survivors_b)
    newly_surviving_not_in_current_lean = set(survivors_b) - set(numeric_lean)

    summary = {
        'full_model_numeric_features_checked': len(numeric_full),
        'full_model_vif_survivors_from_scratch': len(survivors_b),
        'full_model_dropped_for_multicollinearity': len(drop_log_b),
        'current_lean80_numeric_features_checked_standalone': len(numeric_lean),
        'current_lean80_would_still_all_survive_standalone': len(drop_log_a) == 0,
        'current_lean80_features_that_fail_standalone_vif': [d['feature'] for d in drop_log_a],
        'overlap_current_lean80_and_fromscratch_survivors': len(overlap_with_current_lean),
        'current_lean80_features_not_among_fromscratch_survivors': sorted(only_in_current_lean_not_survivor_b),
        'fromscratch_survivors_not_in_current_lean80': sorted(newly_surviving_not_in_current_lean),
    }
    logging.info(json.dumps(summary, ensure_ascii=False, indent=2))
    with open(f'{OUTPUT_DIR}/step21_multicollinearity_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logging.info(f"Saved: step21_full_vif_drop_log.csv, step21_multicollinearity_summary.json")


if __name__ == '__main__':
    main()
