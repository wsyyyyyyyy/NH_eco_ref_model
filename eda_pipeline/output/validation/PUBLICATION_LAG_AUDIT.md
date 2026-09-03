# 공표 지연 전수 재검사 — 측정일 2026-09-01

임계 `lag > shift` (조정 전 `lag > shift + 1`).
`lag` = 측정일과 실데이터 최종 수록월의 개월 차. `shift` = 시차 그룹의 개월 수 (A=0/B=1/C=2/D=3).

- 대상 65개 / 조회 실패 1개 / **걸림 0개**

| series_name | source | freq | 그룹 | shift | 최종 수록월 | 경과 | 판정 |
|---|---|---|---|---:|---|---:|---|
| `base_rate` | ECOS | M | C | 2 | 2026-08 | 0 | OK |
| `call_rate_overnight` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `call_rate_overnight_brokered` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `treasury_bond_1y` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `treasury_bond_3y` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `treasury_bond_5y` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `treasury_bond_10y` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `corporate_bond_3y_AA` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `KORIBOR_3m` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `KORIBOR_6m` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `KORIBOR_12m` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `CD_rate_91d` | ECOS | M | B | 1 | 2026-08 | 0 | OK |
| `treasury_bond_1y_monthly` | ECOS | M | B | 1 | 2026-08 | 0 | OK |
| `M2_broad_money` | ECOS | M | C | 2 | 2026-06 | 2 | OK |
| `M1_narrow_money` | ECOS | M | C | 2 | 2026-06 | 2 | OK |
| `Lf_liquidity` | ECOS | M | C | 2 | 2026-06 | 2 | OK |
| `monetary_base_sa` | ECOS | M | C | 2 | 2026-06 | 2 | OK |
| `PPI_total` | ECOS | M | B | 1 | 2026-07 | 1 | OK |
| `CPI_core` | ECOS | M | B | 1 | 2026-07 | 1 | OK |
| `CPI_core_excl_food_energy` | ECOS | M | B | 1 | 2026-07 | 1 | OK |
| `CPI_food_nonalcohol` | ECOS | M | B | 1 | 2026-07 | 1 | OK |
| `housing_price_index` | ECOS | M | B | 1 | 2026-08 | 0 | OK |
| `export_price_index_KOR` | ECOS | M | B | 1 | 2026-07 | 1 | OK |
| `current_account` | ECOS | M | C | 2 | 2026-06 | 2 | OK |
| `current_account_quarterly` | ECOS | Q | D | 3 | 2026-06 | 3 | OK |
| `goods_balance` | ECOS | M | C | 2 | 2026-06 | 2 | OK |
| `export_index` | ECOS | M | B | 1 | 2026-07 | 1 | OK |
| `import_index` | ECOS | M | B | 1 | 2026-07 | 1 | OK |
| `household_credit` | ECOS | Q | D | 3 | 2026-06 | 3 | OK |
| `household_loan` | ECOS | Q | D | 3 | 2026-06 | 3 | OK |
| `manufacturing_index` | ECOS | A | C | 2 | — | — | 조회 실패 (DROP_COLS) |
| `KOSPI` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `KOSDAQ` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `USD_KRW` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `JPY_KRW` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `EUR_KRW` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `CNY_KRW` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `WTI_crude_oil` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `brent_crude_oil` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `gold` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `silver` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `copper` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `US_10Y_treasury` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `US_3M_tbill` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `SP500` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `NASDAQ` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `DowJones` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `VIX` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `DXY_dollar_index` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `Nikkei225` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `Shanghai_Composite` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `natural_gas` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `soybean` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `corn` | YAHOO | D | A | 0 | 2026-09 | 0 | OK |
| `BSI_mfg_biz` | ECOS | M | C | 2 | 2026-08 | 0 | OK |
| `BSI_mfg_export` | ECOS | M | C | 2 | 2026-08 | 0 | OK |
| `BSI_mfg_domestic` | ECOS | M | C | 2 | 2026-08 | 0 | OK |
| `BSI_nonmfg_biz` | ECOS | M | C | 2 | 2026-08 | 0 | OK |
| `CSI_composite` | ECOS | M | C | 2 | 2026-08 | 0 | OK |
| `CSI_living_prospect` | ECOS | M | C | 2 | 2026-08 | 0 | OK |
| `CP_91d` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `MSB_91d` | ECOS | D | A | 0 | 2026-09 | 0 | OK |
| `unsold_housing` | PUBLIC | M | C | 2 | 2026-06 | 2 | OK |
| `unemployment_rate` | PUBLIC | M | C | 2 | 2026-07 | 1 | OK |
| `construction_cost_index` | PUBLIC | M | C | 2 | 2026-06 | 2 | OK |

## 측정 방법과 한계

- 각 지표를 `--end-date` 캡 없이 최근 구간만 조회해 **실데이터 최종 수록월**을 본다.
- `indicator_metadata.csv` 의 `data_end` 는 수집 요청 종료일(2026-05-31)에 묶여 있어 이 측정에 쓸 수 없다.
- 하루치 관측이다. 월간 통계는 보통 익월 중순 공표이므로 **월초에 재면 경과가 1개월 크게 잡힌다.**
  측정일이 월초일 때 Group B(+1) 월간 지표가 걸리는 것은 이 효과일 수 있다. 관측값만 기록하고 판단은 사람이 한다.
