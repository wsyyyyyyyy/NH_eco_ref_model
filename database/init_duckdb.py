import os
import duckdb
import pandas as pd
import numpy as np
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

def main():
    os.makedirs('database', exist_ok=True)
    db_path = 'database/portal.duckdb'
    if os.path.exists(db_path):
        os.remove(db_path)
        
    conn = duckdb.connect(db_path)
    
    # 1. Load CSV into DuckDB
    print("1. Loading CSV into DuckDB (This may take a few minutes for 6.7GB)...")
    # Using ignore_errors=true in case of any malformed lines, though data should be clean.
    conn.execute("""
        CREATE TABLE corporate_panel AS 
        SELECT * FROM read_csv_auto('eda_pipeline/output/nh_panel_macro_12m.csv', sample_size=-1, ignore_errors=true)
    """)
    
    total_rows = conn.execute("SELECT COUNT(*) FROM corporate_panel").fetchone()[0]
    print(f"Successfully loaded {total_rows} rows.")
    
    # 2. Assign Virtual Branches (VB001 ~ VB005)
    print("2. Assigning Virtual Branches...")
    conn.execute("ALTER TABLE corporate_panel ADD COLUMN V_BRANCH_CODE VARCHAR")
    # Using hash of V_BZNO to assign deterministically
    conn.execute("UPDATE corporate_panel SET V_BRANCH_CODE = 'VB00' || ((hash(V_BZNO::VARCHAR) % 5) + 1)::VARCHAR")
    
    # 3. Add Columns for Model Predictions
    print("3. Adding Model Score Columns...")
    conn.execute("ALTER TABLE corporate_panel ADD COLUMN PROB_FULL DOUBLE")
    conn.execute("ALTER TABLE corporate_panel ADD COLUMN Z_SCORE DOUBLE")
    conn.execute("ALTER TABLE corporate_panel ADD COLUMN Z_GRADE VARCHAR")
    
    # 4. Load Model
    print("4. Loading LightGBM Model for Inference...")
    model_full = lgb.Booster(model_file='eda_pipeline/output/lgbm_12m_model.txt')
    features_full = model_full.feature_name()
    
    # Find categorical columns based on a small sample
    sample_df = conn.execute("SELECT * FROM corporate_panel LIMIT 10").df()
    cat_cols = [c for c in sample_df.select_dtypes(include=['object', 'string']).columns if c in features_full]
    
    print(f"Categorical columns for model: {cat_cols}")
    
    # 5. Process in Chunks
    chunk_size = 100000
    
    # Global mean and std for Z-Score (approximated from previous validation run)
    mu, std = -4.22, 1.85 
    
    for offset in range(0, total_rows, chunk_size):
        print(f"  -> Predicting chunk {offset} to {min(offset+chunk_size, total_rows)}...")
        
        # Read chunk features. DuckDB's rowid is a hidden column.
        chunk_df = conn.execute(f"""
            SELECT rowid, {','.join([f'"{c}"' for c in features_full])} 
            FROM corporate_panel 
            ORDER BY rowid
            LIMIT {chunk_size} OFFSET {offset}
        """).df()
        
        if chunk_df.empty:
            break
            
        X = chunk_df[features_full].copy()
        
        # Ensure categorical types
        for c in cat_cols:
            X[c] = X[c].astype('category')
            
        # Inference
        prob = model_full.predict(X)
        
        # Calculate Z-Score and Grade
        eps = 1e-15
        log_odds = np.log(prob / (1 - prob + eps))
        z_score = (log_odds - mu) / std
        
        def map_grade(z):
            if z <= -1: return 'G1'
            elif z <= 0: return 'G2'
            elif z <= 1: return 'G3'
            elif z <= 2: return 'G4'
            else: return 'G5'
            
        z_grade = [map_grade(z) for z in z_score]
        
        # Create a temp DataFrame for batch update
        temp_df = pd.DataFrame({
            'rowid_idx': chunk_df['rowid'],
            'PROB_FULL': prob,
            'Z_SCORE': z_score,
            'Z_GRADE': z_grade
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
        
    # 6. Create Indexes
    print("6. Creating Database Indexes for Fast Dashboarding...")
    conn.execute("CREATE INDEX idx_branch ON corporate_panel(V_BRANCH_CODE)")
    conn.execute("CREATE INDEX idx_budo ON corporate_panel(IS_BUDO_12M)")
    conn.execute("CREATE INDEX idx_grade ON corporate_panel(Z_GRADE)")
    conn.execute("CREATE INDEX idx_bzno ON corporate_panel(V_BZNO)")
    
    print("DB Initialization Complete! Saved to database/portal.duckdb")

if __name__ == "__main__":
    main()
