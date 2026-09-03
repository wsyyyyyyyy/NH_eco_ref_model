# 전 소스 매핑 감사 — ECOS / YAHOO / KOSIS

- 생성: 2026-09-01 22:15
- ECOS: `StatisticItemList` 전 페이지 라이브 조회
- YAHOO: `chart` API `meta.longName / shortName / instrumentType` 라이브 조회
- KOSIS: `statisticsParameterData.do` 라이브 조회 (2024년 구간, 필터 전/후 비교)
- 판정: `indicators.csv` 의 `expected_name_kr`(우리 의도) 대 실제 조회 명칭
- 조회 실패는 `미조회` 로 기록했고 추정으로 메우지 않았다.

**ECOS 44건** — 일치 40 / 불일치 4
**YAHOO 22건** — 일치 22
**KOSIS 3건** — 일치 3

## ECOS 통계표 조회 상태

| stat_code | 조회 결과 |
|---|---|
| `102Y004` | 캐시 6행 |
| `151Y001` | 캐시 40행 |
| `161Y001` | 캐시 12행 |
| `161Y005` | 캐시 32행 |
| `171Y003` | 캐시 10행 |
| `251Y003` | 캐시 28행 |
| `301Y013` | 캐시 861행 |
| `402Y014` | 캐시 725행 |
| `403Y001` | 캐시 716행 |
| `403Y003` | 캐시 828행 |
| `404Y014` | 캐시 1577행 |
| `501Y013` | 캐시 88행 |
| `511Y002` | 캐시 52행 |
| `512Y013` | 캐시 27행 |
| `721Y001` | 캐시 90행 |
| `722Y001` | 캐시 48행 |
| `731Y003` | 캐시 10행 |
| `817Y002` | 캐시 27행 |
| `901Y009` | 캐시 1743행 |
| `901Y010` | 캐시 104행 |
| `901Y062` | 캐시 6행 |

## ECOS 지표 대조

| series_name | en | stat_code | 통계표명(STAT_NAME) | item | **실제 ITEM_NAME** | expected_name_kr | 판정 | 값범위 |
|---|---|---|---|---|---|---|---|---|
| `base_rate` | Y | `722Y001` | 1.3.1. 한국은행 기준금리 및 여수신금리 | `0101000` | **한국은행 기준금리** | 한국은행 기준금리 | 일치 | 정상 |
| `call_rate_overnight` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010101000` | **콜금리(1일, 전체거래)** | 콜금리(1일|전체거래) | 일치 | 정상 |
| `call_rate_overnight_brokered` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010102000` | **콜금리(1일, 중개회사거래)** | 콜금리(1일|중개회사거래) | 일치 | 정상 |
| `treasury_bond_1y` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010190000` | **국고채(1년)** | 국고채(1년) | 일치 | 정상 |
| `treasury_bond_3y` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010200000` | **국고채(3년)** | 국고채(3년) | 일치 | 정상 |
| `treasury_bond_5y` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010200001` | **국고채(5년)** | 국고채(5년) | 일치 | 정상 |
| `treasury_bond_10y` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010210000` | **국고채(10년)** | 국고채(10년) | 일치 | 정상 |
| `corporate_bond_3y_AA` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010300000` | **회사채(3년, AA-)** | 회사채(3년, AA-) | 일치 | 정상 |
| `KORIBOR_3m` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010150000` | **KORIBOR(3개월)** | KORIBOR(3개월) | 일치 | 정상 |
| `KORIBOR_6m` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010151000` | **KORIBOR(6개월)** | KORIBOR(6개월) | 일치 | 정상 |
| `KORIBOR_12m` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010152000` | **KORIBOR(12개월)** | KORIBOR(12개월) | 일치 | 정상 |
| `CD_rate_91d` | Y | `721Y001` | 1.3.2.2. 시장금리(월,분기,년) | `2010000` | **CD(91일)** | CD(91일) | 일치 | 범위이상 |
| `treasury_bond_1y_monthly` | Y | `721Y001` | 1.3.2.2. 시장금리(월,분기,년) | `5030000` | **국고채(1년)** | 국고채(1년) | 일치 | 정상 |
| `M2_broad_money` | Y | `161Y005` | 1.1.3.1.1. M2 상품별 구성내역(평잔, 계절조정계열) | `BBHS00` | **M2(평잔,계절조정계열)** | M2(평잔,계절조정계열) | 일치 | 범위이상 |
| `M1_narrow_money` | Y | `161Y001` | 1.1.2.1.1. M1 상품별 구성내역(평잔, 계절조정계열) | `BBLS00` | **M1 (평잔, 계절조정계열)** | M1 (평잔, 계절조정계열) | 일치 | 정상 |
| `Lf_liquidity` | Y | `171Y003` | 1.1.4.1.1. Lf 구성내역(평잔, 계절조정계열) | `LAS0000` | **Lf(금융기관유동성) : 상품별(평잔, 계절조정계열)** | Lf(금융기관유동성) : 상품별(평잔, 계절조정계열) | 일치 | 정상 |
| `monetary_base_sa` | Y | `102Y004` | 1.1.1.1.1. 본원통화 구성내역(평잔, 계절조정계열) | `ABA1` | **본원통화(평잔,계절조정계열)** | 본원통화|계절조정 | 일치 | 정상 |
| `PPI_total` | Y | `404Y014` | 4.1.1.1. 생산자물가지수(기본분류) | `*AA` | **총지수** | 총지수|생산자물가지수 | 일치 | 정상 |
| `CPI_core` | Y | `901Y010` | 4.2.2. 소비자물가지수(특수분류) | `QB` | **농산물및석유류제외지수 2)** | 농산물및석유류제외지수 | 일치 | 정상 |
| `CPI_core_excl_food_energy` | Y | `901Y010` | 4.2.2. 소비자물가지수(특수분류) | `DB` | **식료품 및 에너지제외 지수 3)** | 식료품 및 에너지제외 지수 | 일치 | 정상 |
| `CPI_food_nonalcohol` | Y | `901Y009` | 4.2.1. 소비자물가지수 | `A` | **식료품 및 비주류음료** | 식료품 및 비주류음료 | 일치 | 정상 |
| `housing_price_index` | Y | `901Y062` | 4.4.1.1. 주택매매가격지수(KB) | `P63A` | **총지수** | 총지수|주택매매가격지수 | 일치 | 정상 |
| `export_price_index_KOR` | Y | `402Y014` | 4.3.1.1. 수출물가지수(기본분류) | `*AA / W` | **총지수 / 원화기준** | 총지수|수출물가지수|원화기준 | 일치 | 범위이상 |
| `current_account` | Y | `301Y013` | 2.5.1.1. 국제수지 | `000000` | **경상수지** | 경상수지 | 일치 | 확인필요 |
| `current_account_quarterly` | Y | `301Y013` | 2.5.1.1. 국제수지 | `000000` | **경상수지** | 경상수지 | 일치 | 확인필요 |
| `goods_balance` | Y | `301Y013` | 2.5.1.1. 국제수지 | `100000` | **상품수지** | 상품수지 | 일치 | 확인필요 |
| `export_index` | Y | `403Y001` | 3.3.1.1.1. 수출금액지수 | `*AA` | **총지수** | 총지수|수출금액지수 | 일치 | 정상 |
| `import_index` | Y | `403Y003` | 3.3.1.2.1. 수입금액지수 | `*AA` | **총지수** | 총지수|수입금액지수 | 일치 | 정상 |
| `trade_total` | N | `403Y003` | 3.3.1.2.1. 수입금액지수 | `*AA` | **총지수** | 총지수|수입금액지수 | 일치 | 정상 |
| `GNI_annual` | N | `251Y003` | 9.2.1.1. 총량 | `S` | **한국** | 국민총소득|실질GNI | 불일치 | 미검증 |
| `GNI_nominal` | N | `251Y003` | 9.2.1.1. 총량 | `NS1B` | **명목GNI** | 국민총소득|명목GNI | 불일치 | 미검증 |
| `GNI_per_capita` | N | `251Y003` | 9.2.1.1. 총량 | `NS1C` | **1인당GNI** | 국민총소득|1인당GNI | 불일치 | 미검증 |
| `household_credit` | Y | `151Y001` | 1.2.4.1.1. 가계신용(업권별, 분기) | `1000000` | **가계신용** | 가계신용 | 일치 | 범위이상 |
| `household_loan` | Y | `151Y001` | 1.2.4.1.1. 가계신용(업권별, 분기) | `1100000` | **가계대출** | 가계대출 | 일치 | 범위이상 |
| `manufacturing_index` | Y | `501Y013` | 5.8.1.1. 현금흐름표(2012~) | `C` | **C 제조업** | 생산지수|제조업 | 불일치 | 범위이상 |
| `CNY_KRW` | Y | `731Y003` | 3.1.1.3. 원화의 대미달러, 원화의 대위안/대엔 환율 | `0000010` | **원/위안(종가)** | 원/위안(종가) | 일치 | 정상 |
| `BSI_mfg_biz` | Y | `512Y013` | 6.1.1.1. 기업경기조사(실적) | `C0000 / AA` | **제 조 업 / 업황실적BSI 1)** | 기업경기조사(실적)|제 조 업|업황실적BSI | 일치 | 경고 |
| `BSI_mfg_export` | Y | `512Y013` | 6.1.1.1. 기업경기조사(실적) | `C0000 / AM` | **제 조 업 / 수출실적BSI 2)** | 기업경기조사(실적)|제 조 업|수출실적BSI | 일치 | 정상 |
| `BSI_mfg_domestic` | Y | `512Y013` | 6.1.1.1. 기업경기조사(실적) | `C0000 / AL` | **제 조 업 / 내수판매실적BSI 2)** | 기업경기조사(실적)|제 조 업|내수판매실적BSI | 일치 | 정상 |
| `BSI_nonmfg_biz` | Y | `512Y013` | 6.1.1.1. 기업경기조사(실적) | `Y9900 / AA` | **비제조업 / 업황실적BSI 1)** | 기업경기조사(실적)|비제조업|업황실적BSI | 일치 | 정상 |
| `CSI_composite` | Y | `511Y002` | 6.2.1. 소비자동향조사(전국, 월, 2008.9~) | `FME / 99988` | **소비자심리지수 / 전체** | 소비자동향조사|소비자심리지수 | 일치 | 정상 |
| `CSI_living_prospect` | Y | `511Y002` | 6.2.1. 소비자동향조사(전국, 월, 2008.9~) | `FMBA / 99988` | **생활형편전망CSI / 전체** | 소비자동향조사|생활형편전망CSI | 일치 | 정상 |
| `CP_91d` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010503000` | **CP(91일)** | CP(91일) | 일치 | 정상 |
| `MSB_91d` | Y | `817Y002` | 1.3.2.1. 시장금리(일별) | `010400000` | **통안증권(91일)** | 통안증권(91일) | 일치 | 정상 |

### ECOS 불일치·미조회 4건

- `GNI_annual` — 의도 **국민총소득|실질GNI** / 실제 **한국** (`251Y003` 9.2.1.1. 총량, `S`) · 산출물에 값 없음
- `GNI_nominal` — 의도 **국민총소득|명목GNI** / 실제 **명목GNI** (`251Y003` 9.2.1.1. 총량, `NS1B`) · 산출물에 값 없음
- `GNI_per_capita` — 의도 **국민총소득|1인당GNI** / 실제 **1인당GNI** (`251Y003` 9.2.1.1. 총량, `NS1C`) · 산출물에 값 없음
- `manufacturing_index` — 의도 **생산지수|제조업** / 실제 **C 제조업** (`501Y013` 5.8.1.1. 현금흐름표(2012~), `C`) · 지수 기준연도 100 근처 출발 기대 / 시작 9541.00, 실측 1838~1.128e+04

### ECOS 값 범위 검증 지적 10건

- `CD_rate_91d` [RATE] 범위이상 — 금리 0~10% 기대 / 실측 68.700~112.200
- `M2_broad_money` [MONEY] 범위이상 — 단위 일관성 확인 / 실측 0.5~3.5 (금리·비율 규모 — 잔액 아님)
- `export_price_index_KOR` [INDEX] 범위이상 — 지수 기준연도 100 근처 출발 기대 / 시작 -0.70, 실측 -0.7~4.613
- `current_account` [MONEY] 확인필요 — 단위 일관성 확인 / 실측 -6923~3.786e+04
- `current_account_quarterly` [MONEY] 확인필요 — 단위 일관성 확인 / 실측 -8070~7.421e+04
- `goods_balance` [MONEY] 확인필요 — 단위 일관성 확인 / 실측 -441.9~1965
- `household_credit` [MONEY] 범위이상 — 단위 일관성 확인 / 실측 2.66~5.49 (금리·비율 규모 — 잔액 아님)
- `household_loan` [MONEY] 범위이상 — 단위 일관성 확인 / 실측 2.69~5.5 (금리·비율 규모 — 잔액 아님)
- `manufacturing_index` [INDEX] 범위이상 — 지수 기준연도 100 근처 출발 기대 / 시작 9541.00, 실측 1838~1.128e+04
- `BSI_mfg_biz` [BSI] 경고 — BSI 50~150 기대 / 실측 49.0~98.0

## YAHOO ticker 대조

| series_name | ticker | **공식 명칭(Yahoo meta)** | 종목유형 | 거래소 | 통화 | 기대 | 판정 | 값범위 |
|---|---|---|---|---|---|---|---|---|
| `KOSPI` | `^KS11` | **KOSPI Composite Index** | INDEX | KSC | KRW | KOSPI Composite | 일치 | 정상 |
| `KOSDAQ` | `^KQ11` | **Kosdaq Composite Index** | INDEX | KOE | KRW | KOSDAQ Composite | 일치 | 정상 |
| `USD_KRW` | `KRW=X` | **USD/KRW** | CURRENCY | CCY | KRW | USD/KRW | 일치 | 정상 |
| `JPY_KRW` | `JPYKRW=X` | **JPY/KRW** | CURRENCY | CCY | KRW | JPY/KRW | 일치 | 정상 |
| `EUR_KRW` | `EURKRW=X` | **EUR/KRW** | CURRENCY | CCY | KRW | EUR/KRW | 일치 | 정상 |
| `WTI_crude_oil` | `CL=F` | **Crude Oil Oct 26** | FUTURE | NYM | USD | Crude Oil | 일치 | 정상 |
| `brent_crude_oil` | `BZ=F` | **Brent Crude Oil Last Day Financial Futures** | FUTURE | NYM | USD | Brent Crude Oil | 일치 | 정상 |
| `gold` | `GC=F` | **Gold Dec 26** | FUTURE | CMX | USD | Gold | 일치 | 정상 |
| `silver` | `SI=F` | **Silver Dec 26** | FUTURE | CMX | USD | Silver | 일치 | 정상 |
| `copper` | `HG=F` | **Copper Dec 26** | FUTURE | CMX | USD | Copper | 일치 | 정상 |
| `US_10Y_treasury` | `^TNX` | **CBOE Interest Rate 10 Year T No** | INDEX | CGI | USD | 10 Year | 일치 | 정상 |
| `US_3M_tbill` | `^IRX` | **13 WEEK TREASURY BILL** | INDEX | CGI | USD | 13 WEEK TREASURY BILL | 일치 | 미검증 |
| `SP500` | `^GSPC` | **S&P 500** | INDEX | SNP | USD | S&P 500 | 일치 | 정상 |
| `NASDAQ` | `^IXIC` | **NASDAQ Composite** | INDEX | NIM | USD | NASDAQ Composite | 일치 | 정상 |
| `DowJones` | `^DJI` | **Dow Jones Industrial Average** | INDEX | DJI | USD | Dow Jones Industrial Average | 일치 | 정상 |
| `VIX` | `^VIX` | **CBOE Volatility Index** | INDEX | CXI | USD | Volatility Index | 일치 | 정상 |
| `DXY_dollar_index` | `DX-Y.NYB` | **US Dollar Index** | INDEX | NYB | USD | US Dollar Index | 일치 | 정상 |
| `Nikkei225` | `^N225` | **Nikkei 225** | INDEX | OSA | JPY | Nikkei 225 | 일치 | 정상 |
| `Shanghai_Composite` | `000001.SS` | **SSE Composite Index** | INDEX | SHH | CNY | SSE Composite | 일치 | 정상 |
| `natural_gas` | `NG=F` | **Natural Gas Oct 26** | FUTURE | NYM | USD | Natural Gas | 일치 | 정상 |
| `soybean` | `ZS=F` | **Soybean Futures,Nov-2026** | FUTURE | CBT | USX | Soybean | 일치 | 정상 |
| `corn` | `ZC=F` | **Corn Futures,Dec-2026** | FUTURE | CBT | USX | Corn | 일치 | 정상 |

### YAHOO 불일치·미조회 0건


## KOSIS 통계표 대조

| series_name | orgId/tblId/itmId | **통계표명(TBL_NM)** | 항목(ITM_NM) | 단위 | 필터 전 행 | 필터 후 행 | 필터 전 값 | 필터 후 값 | 판정 |
|---|---|---|---|---|---|---|---|---|---|
| `unsold_housing` | `116/DT_MLTM_2080/ALL` | **규모별 미분양현황** | 호 | 호 | 1596 | 12 | 0~7.404e+04 | 6.376e+04~7.404e+04 | 일치 |
| `unemployment_rate` | `101/DT_1DA7102S/T80` | **성/연령별 실업률** | 실업률 | % | 720 | 12 | 0.6~17.1 | 1.9~3.8 | 일치 |
| `construction_cost_index` | `397/DT_39701_A003/16397AAA0` | **건설공사비지수(2020년기준)** | 건설공사비지수 | 2020＝100 | 288 | 12 | 127~137.5 | 129.7~130.4 | 일치 |

### KOSIS 차원 구성 (필터 대상)

- `unsold_housing` — {"C1_NM": ["강원", "경기", "경남", "경북", "광주", "대구", "대전", "부산"], "C2_NM": ["공공부문", "민간부문", "총합"], "C3_NM": ["40∼60㎡", "40㎡이하", "60∼85㎡", "85㎡초과", "공공부문", "소계", "총합"]}
- `unemployment_rate` — {"C1_NM": ["계", "남자", "여자"], "C2_NM": ["15 - 19세", "15 - 24세", "15 - 29세", "15 - 64세", "20 - 24세", "20 - 29세", "25 - 29세", "30 - 34세"]}
- `construction_cost_index` — {"C1_NM": ["건물건설 및 건축보수", "건설", "건축보수", "교통시설건설", "기타건설", "농림수산토목", "도로시설", "도시토목"]}

## 정정 확정표 — 불일치 전건

정정 후 코드는 전부 `StatisticTableList` / `StatisticItemList` 조회로 확인한 값이다.
`(x) 의도적 드롭` 은 다른 사유로 이미 `enabled=N` 이 확정된 지표다 — **미결이 아니다**.
`(d) 지표 부재` 는 **임의 대체 금지** 대상이므로 정정하지 않고 별도 승인을 기다린다.

| # | series_name | 기존 stat/item | **기존이 실제로 가리킨 ITEM_NAME** | 정정 후 stat/item | **정정 후 ITEM_NAME** | 불일치 유형 |
|---:|---|---|---|---|---|---|
| 1 | `GNI_annual` | `251Y003 / S` | **한국** | — (정정 없음) | **enabled=N. 차원 구조 재설계 필요 — 이번 정정에서 제외, 드롭 유지** | (x) 의도적 드롭 — Group2(계정항목) 미지정. Group1 구분코드 '한국' 만 지정된 구조 오류 |
| 2 | `GNI_nominal` | `251Y003 / NS1B` | **명목GNI** | — (정정 없음) | **enabled=N. Group2 를 item_code2 로 옮겨야 한다 — 드롭 유지** | (x) 의도적 드롭 — Group2 코드를 item_code1(Group1) 자리에 넣은 차원 자리 오류 |
| 3 | `GNI_per_capita` | `251Y003 / NS1C` | **1인당GNI** | — (정정 없음) | **enabled=N. Group2 를 item_code2 로 옮겨야 한다 — 드롭 유지** | (x) 의도적 드롭 — Group2 코드를 item_code1(Group1) 자리에 넣은 차원 자리 오류 |
| 4 | `manufacturing_index` | `501Y013 / C` | **C 제조업** | — (정정 없음) | **(x) 의도적 드롭 — DROP_COLS 유지. 정정하지 않는다** | (x) 의도적 드롭 — impute_data.DROP_COLS 에 유지. 501Y013 은 3차원(업종/연도기준/계정항목) 표인데 item_code1 만 지정해 41개 계열이 섞여 들어왔고, 연간이라 5행뿐이다. 대량 결측 드롭 사유가 여전히 유효하다 |

**유형별 집계** — (x) 의도적 드롭 4건  (합계 4건)
