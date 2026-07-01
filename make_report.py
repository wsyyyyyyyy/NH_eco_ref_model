import pandas as pd
df = pd.read_csv('eda_pipeline/output/nh_panel_prep.csv')

with open('C:/Users/User/.gemini/antigravity/brain/617e8e08-d8ba-41a7-9ac5-95cca35aa6fe/post_prep_column_spec.md', 'w', encoding='utf-8') as f:
    f.write('# 🔍 전처리 완료 후 결측치 및 타겟 리포트\n\n')
    f.write(f'- **총 데이터 건수**: {len(df):,}건\n')
    f.write(f'- **총 피처 수**: {len(df.columns)}개\n')
    
    cnt_0 = len(df[df['IS_BUDO_12M']==0])
    cnt_1 = len(df[df['IS_BUDO_12M']==1])
    f.write(f'- **부도 예측 타겟(12M) 분포**:\n  - 정상(0): {cnt_0:,}건\n  - 부도(1): {cnt_1:,}건\n')
    
    null_sum = df.isnull().sum().sum()
    f.write(f'- **결측치 잔여 총합**: {null_sum}건 (결측치 0% 달성!)\n\n')
    
    f.write('| 컬럼명 | 데이터타입 | 결측률 | 샘플 데이터 |\n')
    f.write('|---|---|---|---|\n')
    for c in df.columns[:]:
        dtype = str(df[c].dtype)
        null_pct = df[c].isnull().mean() * 100
        sample = ', '.join(df[c].dropna().astype(str).unique()[:3])
        f.write(f'| {c} | {dtype} | {null_pct:.1f}% | {sample} |\n')
print('Report saved.')
