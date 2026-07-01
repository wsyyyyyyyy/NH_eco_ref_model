import pandas as pd

df = pd.read_csv('analysis/news_overlay/output/news_overlay_index_daily.csv', encoding='utf-8-sig')
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(f"Date range: {df['date'].min()} ~ {df['date'].max()}")
print(f"Unique corps: {df['V_BZNO'].nunique()}")
print(f"\nScore stats:")
print(df['CORP_NEWS_RISK_INDEX'].describe())
print(f"\nSample (first 5 rows):")
print(df.head(5).to_string())
