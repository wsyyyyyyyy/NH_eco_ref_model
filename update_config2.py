import pandas as pd

# Add to indicator_names.csv
names_file = "config/indicator_names.csv"
with open(names_file, "a", encoding="utf-8") as f:
    f.write("electricity_usage,전력사용량,Electricity Usage,실물위험,Real Risk,PUBLIC,M,kWh\n")

# Add to indicators.csv
ind_file = "config/indicators.csv"
with open(ind_file, "a", encoding="utf-8") as f:
    f.write("PUBLIC,electricity_usage,Y,M,,,,,,,\n")

print("Added electricity_usage to config.")
