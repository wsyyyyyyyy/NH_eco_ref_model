import pandas as pd
import numpy as np
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def assign_virtual_branch(ind_code):
    """
    산업분류코드(STD_INDS_CFC)에 따라 5개의 가상 지점 코드를 할당합니다.
    (모든 데이터는 BZSCAL_C == 4.0 인 중소기업으로 전제합니다)
    """
    if pd.isna(ind_code):
        return 'VB005', 'IT/부동산/기타 중소기업 전담 지점'
    
    try:
        ind = int(ind_code)
    except ValueError:
        return 'VB005', 'IT/부동산/기타 중소기업 전담 지점'
        
    if 10000 <= ind < 34000:
        return 'VB001', '제조 중소기업 전담 지점'
    elif 41000 <= ind < 43000:
        return 'VB002', '건설 중소기업 전담 지점'
    elif 45000 <= ind < 48000:
        return 'VB003', '도소매 중소기업 전담 지점'
    elif (55000 <= ind < 57000) or (85000 <= ind < 97000):
        return 'VB004', '서비스 중소기업 전담 지점'
    else:
        return 'VB005', 'IT/부동산/기타 중소기업 전담 지점'

def main():
    input_path = '../eda_pipeline/output/nh_panel_prep.csv'
    output_dir = 'output'
    output_path = os.path.join(output_dir, 'nh_panel_with_branch.csv')
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    logging.info(f"Loading data from {input_path}...")
    try:
        df = pd.read_csv(input_path, dtype={'BASE_YM': str, 'V_BZNO': str})
    except FileNotFoundError:
        logging.error(f"File not found: {input_path}")
        return
        
    logging.info(f"Data loaded. Shape: {df.shape}")
    
    # 가상 지점 할당
    logging.info("Assigning virtual branches based on STD_INDS_CFC...")
    branch_info = df['STD_INDS_CFC'].apply(assign_virtual_branch)
    
    df['VIRTUAL_BRANCH_CD'] = [b[0] for b in branch_info]
    df['VIRTUAL_BRANCH_NM'] = [b[1] for b in branch_info]
    
    # 검증 출력
    logging.info("=== Virtual Branch Distribution ===")
    dist = df['VIRTUAL_BRANCH_NM'].value_counts()
    for name, count in dist.items():
        logging.info(f"{name}: {count:,}건")
        
    # 저장
    logging.info(f"Saving enriched data to {output_path}...")
    df.to_csv(output_path, index=False)
    logging.info("Virtual branch assignment completed successfully!")

if __name__ == '__main__':
    # 스크립트가 실행되는 위치에 상관없이 상대경로를 맞추기 위한 처리
    # (이 스크립트는 api_data_processing 폴더 안에서 실행될 것으로 가정)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)
    main()
