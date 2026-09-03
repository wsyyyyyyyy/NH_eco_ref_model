"""[Validation 2/5] Is the current SHAP top-feature ranking stable enough, or does it need
"sharpening" (de-duplicating redundant top variables)?

Two checks:
  1. Stability -- recompute SHAP mean(|value|) rankings on 3 bootstrap resamples of a Valid
     pool and on a Train sample, then measure overlap (Jaccard@30/@50) and rank correlation
     (Spearman) against a reference ranking computed on the full sampled pool. A stable
     ranking should show high overlap regardless of which rows happened to be sampled.
  2. Redundancy -- pairwise correlation among the current top-30 features (by SHAP) on a
     larger Train sample; pairs with |corr| > 0.85 are candidates for "sharpening". Cross-
     referenced against the existing VIF-diet survivors (lgbm_12m_lean_model.txt, 80 features)
     to see how much of that redundancy the VIF step already resolved.
"""
import json
import logging

import numpy as np
import pandas as pd
import shap
from scipy.stats import spearmanr

from validation_common import FULL_MODEL_PATH, OUTPUT_DIR, full_feature_list, lean_feature_list
import duckdb
import lightgbm as lgb

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

DB_PATH = 'C:/Users/User/model_kbm/database/portal.duckdb'
POOL_SIZE = 100_000
BOOT_SIZE = 40_000
TRAIN_SAMPLE_SIZE = 40_000
TOP_N_STABILITY = 50
TOP_N_CORR = 30


def sample_split(features, split, n, seed=42):
    con = duckdb.connect(DB_PATH, read_only=True)
    select_parts = []
    for c in features:
        if c == 'OBV_ELYWRN_OBV_GRD_DSC':
            select_parts.append(f'"{c}"')
        else:
            select_parts.append(f'CAST("{c}" AS FLOAT) AS "{c}"')
    sql = f"""
        SELECT {', '.join(select_parts)}
        FROM corporate_panel
        WHERE SPLIT = '{split}'
        USING SAMPLE {n} (reservoir, {seed})
    """
    df = con.execute(sql).fetchdf()
    con.close()
    df['OBV_ELYWRN_OBV_GRD_DSC'] = df['OBV_ELYWRN_OBV_GRD_DSC'].astype('category')
    return df


def shap_importance(model, X, sample_size, seed):
    X_s = X.sample(n=min(sample_size, len(X)), random_state=seed)
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_s)
    if isinstance(shap_values, list):
        shap_values = shap_values[1]
    mean_abs = np.abs(shap_values).mean(axis=0)
    return pd.Series(mean_abs, index=X_s.columns).sort_values(ascending=False)


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b)


def main():
    features = full_feature_list()
    model = lgb.Booster(model_file=FULL_MODEL_PATH)

    logging.info(f"Pulling Valid pool ({POOL_SIZE} rows) and Train sample ({TRAIN_SAMPLE_SIZE} rows)...")
    valid_pool = sample_split(features, 'VALID', POOL_SIZE, seed=1)
    train_sample = sample_split(features, 'TRAIN', TRAIN_SAMPLE_SIZE, seed=2)

    logging.info("Reference SHAP ranking on full Valid pool...")
    ref_rank = shap_importance(model, valid_pool, POOL_SIZE, seed=0)

    logging.info("Bootstrap resamples of the Valid pool (x3)...")
    boot_ranks = []
    for i in range(3):
        boot_df = valid_pool.sample(n=BOOT_SIZE, replace=True, random_state=100 + i)
        rank_i = shap_importance(model, boot_df, BOOT_SIZE, seed=100 + i)
        boot_ranks.append(rank_i)

    logging.info("SHAP ranking on Train sample (for Train vs Valid comparison)...")
    train_rank = shap_importance(model, train_sample, TRAIN_SAMPLE_SIZE, seed=3)

    stability_rows = []
    for i, br in enumerate(boot_ranks):
        common_idx = ref_rank.index.intersection(br.index)
        rho, _ = spearmanr(ref_rank[common_idx], br[common_idx])
        stability_rows.append({
            'comparison': f'valid_bootstrap_{i+1}_vs_reference',
            f'jaccard_top{TOP_N_STABILITY}': jaccard(ref_rank.head(TOP_N_STABILITY).index, br.head(TOP_N_STABILITY).index),
            'jaccard_top30': jaccard(ref_rank.head(30).index, br.head(30).index),
            'spearman_rho_all_features': rho,
        })
    common_idx = ref_rank.index.intersection(train_rank.index)
    rho_tv, _ = spearmanr(ref_rank[common_idx], train_rank[common_idx])
    stability_rows.append({
        'comparison': 'train_sample_vs_valid_reference',
        f'jaccard_top{TOP_N_STABILITY}': jaccard(ref_rank.head(TOP_N_STABILITY).index, train_rank.head(TOP_N_STABILITY).index),
        'jaccard_top30': jaccard(ref_rank.head(30).index, train_rank.head(30).index),
        'spearman_rho_all_features': rho_tv,
    })
    stability_df = pd.DataFrame(stability_rows)
    stability_csv = f'{OUTPUT_DIR}/step15_shap_stability.csv'
    stability_df.to_csv(stability_csv, index=False, encoding='utf-8-sig')
    logging.info(f"\n{stability_df.to_string(index=False)}")
    logging.info(f"Saved: {stability_csv}")

    # --- Redundancy check among top-30 (by the full-pool reference ranking) ---
    top30 = ref_rank.head(TOP_N_CORR).index.tolist()
    corr_df = train_sample[top30].copy()
    if 'OBV_ELYWRN_OBV_GRD_DSC' in corr_df.columns:
        corr_df['OBV_ELYWRN_OBV_GRD_DSC'] = (corr_df['OBV_ELYWRN_OBV_GRD_DSC'] == 'B').astype(float)
    corr_matrix = corr_df.corr()

    lean_set = set(lean_feature_list())
    pairs = []
    for i, f1 in enumerate(top30):
        for f2 in top30[i + 1:]:
            c = corr_matrix.loc[f1, f2]
            if abs(c) > 0.85:
                pairs.append({
                    'feature_1': f1, 'feature_1_survived_vif_diet': f1 in lean_set,
                    'feature_2': f2, 'feature_2_survived_vif_diet': f2 in lean_set,
                    'correlation': round(float(c), 3),
                })
    pairs_df = pd.DataFrame(pairs).sort_values('correlation', key=abs, ascending=False) if pairs else pd.DataFrame(
        columns=['feature_1', 'feature_1_survived_vif_diet', 'feature_2', 'feature_2_survived_vif_diet', 'correlation'])
    pairs_csv = f'{OUTPUT_DIR}/step15_top30_redundant_pairs.csv'
    pairs_df.to_csv(pairs_csv, index=False, encoding='utf-8-sig')
    logging.info(f"\nHigh-correlation pairs among top-{TOP_N_CORR} SHAP features (|corr|>0.85):\n{pairs_df.to_string(index=False)}")
    logging.info(f"Saved: {pairs_csv}")

    ref_rank.head(50).to_csv(f'{OUTPUT_DIR}/step15_reference_shap_ranking_top50.csv', header=['mean_abs_shap'], encoding='utf-8-sig')

    summary = {
        'n_high_corr_pairs_in_top30': int(len(pairs_df)),
        'both_survived_vif_diet_count': int(sum(
            1 for p in pairs if p['feature_1_survived_vif_diet'] and p['feature_2_survived_vif_diet']
        )),
        'min_jaccard_top50_across_bootstraps': float(stability_df[f'jaccard_top{TOP_N_STABILITY}'].min()),
    }
    with open(f'{OUTPUT_DIR}/step15_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logging.info(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
