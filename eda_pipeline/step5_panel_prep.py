import pandas as pd
import numpy as np
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def calculate_business_age(base_ym, etb_dt):
    try:
        base = pd.to_datetime(base_ym.astype(str), format='%Y%m', errors='coerce')
        etb_str = etb_dt.astype(str).str.replace('.0', '', regex=False)
        etb = pd.to_datetime(etb_str, format='%Y%m%d', errors='coerce')
        
        age_years = (base - etb).dt.days / 365.25
        return age_years.clip(lower=0)
    except Exception as e:
        logging.error(f"Error calculating business age: {e}")
        return np.nan

def generate_12m_target(df):
    logging.info("Generating IS_BUDO_12M target...")
    default_records = df[df['IS_BUDO_YN'] == 1][['V_BZNO', 'BASE_YM']].copy()
    default_records = default_records.rename(columns={'BASE_YM': 'DEFAULT_YM'})
    
    df = df.merge(default_records, on='V_BZNO', how='left')
    
    df['BASE_DT'] = pd.to_datetime(df['BASE_YM'].astype(str), format='%Y%m')
    df['DEF_DT'] = pd.to_datetime(df['DEFAULT_YM'].astype(str).str.replace('\.0', '', regex=True), format='%Y%m', errors='coerce')
    
    df['MONTHS_TO_DEFAULT'] = (df['DEF_DT'].dt.year - df['BASE_DT'].dt.year) * 12 + (df['DEF_DT'].dt.month - df['BASE_DT'].dt.month)
    
    df['IS_BUDO_12M'] = ((df['MONTHS_TO_DEFAULT'] > 0) & (df['MONTHS_TO_DEFAULT'] <= 12)).astype(int)
    
    df = df.drop(columns=['DEFAULT_YM', 'BASE_DT', 'DEF_DT', 'MONTHS_TO_DEFAULT'])
    return df

def process_missing_values(df):
    logging.info("Step 1: Forward-Fill by V_BZNO for time-series data")
    df = df.sort_values(['V_BZNO', 'BASE_YM'])
    cols_to_ffill = [c for c in df.columns if c not in ['V_BZNO', 'BASE_YM']]
    df[cols_to_ffill] = df.groupby('V_BZNO')[cols_to_ffill].ffill()
    
    logging.info("Step 2: Custom Fill for remaining missing values")
    
    cat_cols = ['STD_INDS_CFC', 'COPR_OPNP_C', 'OBV_ELYWRN_OBV_GRD_DSC']
    for c in cat_cols:
        if c in df.columns:
            df[c] = df[c].fillna('-1')
            
    if 'CRIF_CRDBD_RSNC' in df.columns:
        df['CRIF_CRDBD_RSNC'] = df['CRIF_CRDBD_RSNC'].fillna(-1)
        
    if 'AA17_EXT_PROD_RECORD_YN' in df.columns:
        df['AA17_EXT_PROD_RECORD_YN'] = df['AA17_EXT_PROD_RECORD_YN'].fillna(0)
        
    if 'C302_CRI_ORD' in df.columns:
        median_ord = df['C302_CRI_ORD'].median()
        df['C302_CRI_ORD'] = df['C302_CRI_ORD'].fillna(median_ord)
        
    if 'CG01_KIS_SCORE' in df.columns:
        median_score = df['CG01_KIS_SCORE'].median()
        df['CG01_KIS_SCORE'] = df['CG01_KIS_SCORE'].fillna(median_score)
        
    if 'CRIF_MAX(CRDBD_RLS_RSNC)' in df.columns:
        df['CRIF_MAX(CRDBD_RLS_RSNC)'] = df['CRIF_MAX(CRDBD_RLS_RSNC)'].fillna(-1)
        
    if 'AA10_PERS_CNT' in df.columns:
        df['AA10_PERS_CNT'] = df['AA10_PERS_CNT'].fillna(1).astype(int)
        
    amount_keywords = ['_AM', '_BAC', '_POD', '_ELGD', 'JEMU_', 'AA17_']
    amount_cols = [c for c in df.columns if any(k in c for k in amount_keywords) and c not in cat_cols]
    
    for c in amount_cols:
        df[c] = df[c].fillna(0.0)
        
    if 'BUSINESS_AGE' in df.columns:
        df['BUSINESS_AGE'] = df['BUSINESS_AGE'].fillna(df['BUSINESS_AGE'].median())
        
    return df

def main():
    input_path = 'eda_pipeline/output/nh_panel_full.csv'
    output_path = 'eda_pipeline/output/nh_panel_prep.csv'
    
    logging.info(f"Loading data from {input_path}")
    df = pd.read_csv(input_path, dtype={'ETB_DT': str, 'BASE_YM': str})
    
    logging.info(f"Initial shape: {df.shape}")
    
    df = df[df['BZSCAL_C'] == 4.0].copy()
    logging.info(f"After BZSCAL_C == 4.0 filter shape: {df.shape}")
    
    df = generate_12m_target(df)
    budo_cnt = df['IS_BUDO_12M'].sum()
    logging.info(f"Target IS_BUDO_12M == 1 count: {budo_cnt} ({(budo_cnt/len(df)*100):.2f}%)")
    
    if 'ETB_DT' in df.columns:
        logging.info("Calculating Business Age...")
        df['BUSINESS_AGE'] = calculate_business_age(df['BASE_YM'], df['ETB_DT'])
        
    drop_cols = [
        'CONM', 'BZSCAL_C', 'ETB_DT', 'EMPCN',
        'GRD_LS_NICS_GRDC', 'GRD_CRDEVL_PTTP_DSC', 'OBV_RZVL_POD',
        'C302_CRI_GRD', 'CRIF_MAX(CRDBD_RLS_OCU_DT)', 'AA17_TOT_SEL_AM', 'IS_BUDO_YN'
    ]
    
    actual_drops = [c for c in drop_cols if c in df.columns]
    logging.info(f"Dropping columns: {actual_drops}")
    df = df.drop(columns=actual_drops)
    
    df = process_missing_values(df)
    
    null_counts = df.isnull().sum()
    remaining_nulls = null_counts[null_counts > 0]
    if len(remaining_nulls) > 0:
        logging.warning(f"Remaining nulls after imputation:\\n{remaining_nulls}")
    else:
        logging.info("All missing values successfully imputed.")
        
    df.to_csv(output_path, index=False)
    logging.info(f"Preprocessing completed. Saved to {output_path}. Final shape: {df.shape}")

if __name__ == '__main__':
    main()
