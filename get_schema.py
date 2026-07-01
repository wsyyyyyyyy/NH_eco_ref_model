import duckdb
import pandas as pd

pd.set_option('display.max_rows', None)

con = duckdb.connect('database/nh_credit_risk.db', read_only=True)
df = con.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='main' ORDER BY table_name, ordinal_position").df()
print(df.to_string())
con.close()
