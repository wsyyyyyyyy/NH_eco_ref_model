"""Re-scores the entire corporate_panel table (1,944,418 rows) in portal.duckdb with the
retrained Full(230) model (eda_pipeline/step23_retrain_production_models.py), replacing
PROB_FULL/Z_SCORE/Z_GRADE in place.

Unlike database/init_duckdb.py (which rebuilds the whole DB from the 6.76GB source CSV --
not available in this checkout), this script re-scores the EXISTING table using the feature
columns it already has, so no source CSV is required. Same UPDATE...FROM chunking pattern as
init_duckdb.py's own scoring step.

Also recomputes:
  - The Z-Score normalization (mu, std of the new PROB_FULL's log-odds), replacing
    init_duckdb.py's hardcoded approximation (-4.22, 1.85) with the real value for the new
    model's actual output distribution. The G1-G5 bucket thresholds themselves (z<=-1/0/1/2)
    are kept unchanged since backend/routers/dashboard.py's SQL hardcodes the 'G4'/'G5' labels.
  - The 16-notch PROB_CUTOFFS used by backend/grade_mapping.py (printed at the end; must be
    applied to that file by hand as a separate, reviewable step).
"""
import logging
import math
import shutil
import time

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

DB_PATH = 'database/portal.duckdb'
BACKUP_PATH = 'database/portal.duckdb.bak_pre_retrain'
MODEL_PATH = 'eda_pipeline/output/lgbm_12m_model.txt'
CHUNK_SIZE = 100_000


def map_grade(z):
    if z <= -1:
        return 'G1'
    elif z <= 0:
        return 'G2'
    elif z <= 1:
        return 'G3'
    elif z <= 2:
        return 'G4'
    else:
        return 'G5'


def main():
    logging.info(f"Backing up {DB_PATH} -> {BACKUP_PATH} (pre-existing .bak from Step 24 is left untouched)")
    shutil.copy(DB_PATH, BACKUP_PATH)

    model = lgb.Booster(model_file=MODEL_PATH)
    features = model.feature_name()
    logging.info(f"Loaded model with {len(features)} features, {model.num_trees()} trees")

    conn = duckdb.connect(DB_PATH)
    total_rows = conn.execute("SELECT COUNT(*) FROM corporate_panel").fetchone()[0]
    logging.info(f"corporate_panel has {total_rows} rows")

    cat_col = 'OBV_ELYWRN_OBV_GRD_DSC'
    categories = model.pandas_categorical[0] if model.pandas_categorical else None

    all_rowids, all_probs = [], []
    t0 = time.time()
    for offset in range(0, total_rows, CHUNK_SIZE):
        chunk = conn.execute(f"""
            SELECT rowid, {', '.join(f'"{c}"' for c in features)}
            FROM corporate_panel
            ORDER BY rowid
            LIMIT {CHUNK_SIZE} OFFSET {offset}
        """).df()
        if chunk.empty:
            break
        X = chunk[features].copy()
        if cat_col in X.columns and categories is not None:
            X[cat_col] = pd.Categorical(X[cat_col].astype(str), categories=categories)
        prob = model.predict(X)
        all_rowids.append(chunk['rowid'].to_numpy())
        all_probs.append(prob)
        logging.info(f"  Predicted rows {offset}-{min(offset + CHUNK_SIZE, total_rows)} ({time.time()-t0:.1f}s elapsed)")

    rowids = np.concatenate(all_rowids)
    probs = np.concatenate(all_probs)
    logging.info(f"Prediction complete for {len(probs)} rows in {time.time()-t0:.1f}s")

    eps = 1e-15
    probs_clipped = np.clip(probs, eps, 1 - eps)
    log_odds = np.log(probs_clipped / (1 - probs_clipped))
    mu, std = float(np.mean(log_odds)), float(np.std(log_odds))
    logging.info(f"New Z-Score normalization: mu={mu:.4f}, std={std:.4f} (was hardcoded -4.22, 1.85)")

    z_scores = (log_odds - mu) / std
    z_grades = [map_grade(z) for z in z_scores]

    logging.info("Writing PROB_FULL/Z_SCORE/Z_GRADE back to corporate_panel...")
    for offset in range(0, len(rowids), CHUNK_SIZE):
        sl = slice(offset, offset + CHUNK_SIZE)
        temp_df = pd.DataFrame({
            'rowid_idx': rowids[sl], 'PROB_FULL': probs[sl],
            'Z_SCORE': z_scores[sl], 'Z_GRADE': np.array(z_grades)[sl],
        })
        conn.register('temp_updates', temp_df)
        conn.execute("""
            UPDATE corporate_panel
            SET PROB_FULL = temp_updates.PROB_FULL,
                Z_SCORE = temp_updates.Z_SCORE,
                Z_GRADE = temp_updates.Z_GRADE
            FROM temp_updates
            WHERE corporate_panel.rowid = temp_updates.rowid_idx
        """)
        conn.unregister('temp_updates')
        logging.info(f"  Updated rows {offset}-{min(offset + CHUNK_SIZE, len(rowids))}")

    logging.info("Re-score complete. Post-update sanity check:")
    dist = conn.execute("SELECT Z_GRADE, COUNT(*), MIN(PROB_FULL), MAX(PROB_FULL), AVG(PROB_FULL) FROM corporate_panel GROUP BY Z_GRADE ORDER BY Z_GRADE").fetchdf()
    logging.info(f"\n{dist.to_string(index=False)}")
    nan_check = conn.execute("SELECT COUNT(*) FILTER (WHERE PROB_FULL IS NULL) FROM corporate_panel").fetchone()[0]
    logging.info(f"NULL PROB_FULL rows after rescore: {nan_check}")

    n_cutoffs = 15
    percentiles = np.linspace(0.40, 0.999, n_cutoffs)
    cutoffs = np.quantile(probs, percentiles)
    logging.info(f"New 16-notch PROB_CUTOFFS (percentiles {percentiles.round(4).tolist()}):")
    logging.info(f"PROB_CUTOFFS = {[round(float(c), 5) for c in cutoffs]}")

    conn.close()


if __name__ == '__main__':
    main()
