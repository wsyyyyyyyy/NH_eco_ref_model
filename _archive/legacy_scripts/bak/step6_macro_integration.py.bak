import pandas as pd
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def apply_macro_lag(macro_df):
    """
    미래 참조 오류(Look-ahead bias)를 방지하기 위해 거시경제 지표에 1개월 시차(Lag)를 적용합니다.
    """
    macro_df = macro_df.sort_values('BASE_YM')
    
    features = [c for c in macro_df.columns if c != 'BASE_YM']
    
    macro_df[features] = macro_df[features].shift(1)
    macro_df = macro_df.bfill()
    
    return macro_df

def main():
    panel_path = 'eda_pipeline/output/nh_panel_prep.csv'
    macro_path = 'api_data_processing/output/model_input/model_input_monthly_cleaned.csv'
    out_path = 'eda_pipeline/output/nh_panel_macro_12m.csv'
    
    logging.info(f"패널 데이터 로딩: {panel_path}")
    panel = pd.read_csv(panel_path, dtype={'BASE_YM': str})
    
    logging.info(f"외부 거시경제 데이터 로딩: {macro_path}")
    macro = pd.read_csv(macro_path)
    
    logging.info("거시경제 지표에 1개월 Lag(시차) 적용 중... (미래 참조 오류 방지)")
    macro_lagged = apply_macro_lag(macro)
    
    logging.info("패널 데이터에 외부 거시경제 지표 결합 중 (Left Join)...")
    panel['BASE_YM'] = panel['BASE_YM'].astype(str).str.replace(r'\.0$', '', regex=True)
    macro_lagged['BASE_YM'] = macro_lagged['BASE_YM'].astype(str)
    
    merged = panel.merge(macro_lagged, on='BASE_YM', how='left')
    
    macro_features = [c for c in macro_lagged.columns if c != 'BASE_YM']
    missing_after_join = merged[macro_features].isnull().sum().sum()
    if missing_after_join > 0:
        logging.warning(f"거시경제 데이터 결합 후 {missing_after_join}개의 결측치 발생. (ffill/bfill 적용)")
        merged = merged.sort_values(['V_BZNO', 'BASE_YM'])
        merged[macro_features] = merged[macro_features].ffill().bfill()
        
    logging.info(f"결합 완료. 최종 데이터 형태: {merged.shape}")
    
    merged.to_csv(out_path, index=False)
    logging.info(f"최종 모델링용 데이터셋 저장 완료: {out_path}")

if __name__ == '__main__':
    main()
