# DuckDB Data Warehouse Migration

> **DuckDB 기반 통합 데이터웨어하우스 마이그레이션 가이드**
>
> 기존 엑셀/CSV/TXT 원장 관리 방식을 탈피하여, DuckDB 단일 데이터베이스로
> 모든 원천 데이터와 가공 마트를 통합 관리합니다.

---

## 아키텍처 개요

```
                    DuckDB Data Warehouse
                  (nh_credit_risk.db)
                         |
          +--------------+--------------+
          |                             |
    [RAW Tables]                  [MART Tables]
    원장 데이터                    가공 분석 마트
          |                             |
    +-----+-----+             +--------+--------+
    |           |             |        |        |
  input/      input/     analysis/  api_data/  news_
  *.txt       *.xlsx     output/    output/    overlay/
  (pipe-      (Excel)    (CSV)      (CSV)      output/
  delimited)                                   (CSV)
```

## 파이프라인 흐름

```
[1] Input Scan               [2] Mart Migration        [3] Indexing & Verify
+-------------------+    +---------------------+    +--------------------+
| glob(input/*.txt) |    | glob(output/*.csv)  |    | CREATE INDEX       |
| glob(input/*.xlsx)|    | glob(output/*.xlsx) |    |   ON V_BZNO        |
|        |          |    |        |            |    |   ON BAS_YM        |
|   pd.read_csv()   |    |   pd.read_csv()    |    |        |           |
|   pd.read_excel() |    |   pd.read_excel()  |    | Verify Report      |
|        |          |    |        |            |    | (table list +      |
| CREATE OR REPLACE |    | CREATE OR REPLACE  |    |  row counts)       |
|   TABLE raw_XXX   |    |   TABLE mart_XXX   |    +--------------------+
|        |          |    |        |            |
|   del df          |    |   del df           |
|   gc.collect()    |    |   gc.collect()     |
+-------------------+    +---------------------+
```

---

## 테이블 명명 규칙

### 원장 테이블 (RAW)

| 원본 파일명 | DuckDB 테이블명 |
|-----------|----------------|
| `가상사업자_UPCHE_TOT_기업정보v.txt` | `raw_UPCHE_TOT_기업정보` |
| `가상사업자_VH_OBV_DTL_관찰세부등급v.txt` | `raw_VH_OBV_DTL_관찰세부등급` |
| `가상사업자_JEMU_재무데이터v.txt` | `raw_JEMU_재무데이터` |
| `가상사업자_AA10_종업원수.txt` | `raw_AA10_종업원수` |
| `Metadata Registry.xlsx` | `raw_Metadata_Registry` |

### 마트 테이블 (MART)

| 원본 파일명 | DuckDB 테이블명 |
|-----------|----------------|
| `01_raw_statistics.csv` | `mart_01_raw_statistics` |
| `05_final_selected_variables.csv` | `mart_05_final_selected_variables` |
| `news_overlay_index_daily.csv` | `mart_news_overlay_index_daily` |
| `daily.csv` | `mart_daily` |

---

## 실행 방법

### 전체 마이그레이션 (기본)
```bash
python -m database.db_migration
```

### 원장만 적재
```bash
python -m database.db_migration --input-only
```

### 분석 마트만 이관
```bash
python -m database.db_migration --mart-only
```

### 검증 리포트만 출력
```bash
python -m database.db_migration --verify-only
```

---

## Python API 사용법

### 마트 즉시 저장 (엑셀 대체)

```python
# 기존: df_result.to_csv("output/result.csv")  <-- 폐기
# 신규: DuckDB 즉시 저장
from database.db_migration import save_mart_to_db

save_mart_to_db(df_result, "final_macro_vars")       # -> mart_final_macro_vars
save_mart_to_db(df_iv, "univariate_iv_ranking")       # -> mart_univariate_iv_ranking
```

### SQL 쿼리 실행

```python
from database.db_migration import query_db

# 기업 마스터 조회
df = query_db("SELECT * FROM raw_UPCHE_TOT_기업정보 LIMIT 10")

# 관찰세부등급 집계 (97만건 초고속 조회)
df = query_db("""
    SELECT BAS_YM, COUNT(*) as cnt, AVG(CAST(RZVL_POD AS DOUBLE)) as avg_pod
    FROM "raw_VH_OBV_DTL_관찰세부등급"
    GROUP BY BAS_YM
    ORDER BY BAS_YM
""")

# 조인 쿼리
df = query_db("""
    SELECT a.V_BZNO, a.CONM, b.BAS_YM, b.LN_BAC
    FROM "raw_UPCHE_TOT_기업정보" a
    JOIN "raw_VH_OBV_DTL_관찰세부등급" b ON a.V_BZNO = b.V_BZNO
    WHERE b.BAS_YM = '202401'
    LIMIT 100
""")
```

---

## 인덱싱 전략

자동 인덱싱 대상 컬럼:

| 컬럼 | 용도 | 대상 테이블 |
|------|------|-----------|
| `V_BZNO` | 차주 고유키 (사업자번호) | 전체 |
| `BAS_YM` | 기준년월 | 관찰세부등급, 외화부채 등 |
| `BAS_DT` | 기준일자 | 시계열 데이터 |
| `BASDT1` | 기준일자1 | 종업원수 등 |
| `FNA_CLS_YM` | 결산연도 | 재무데이터 |
| `DSH_DT` | 부도일자 | 부도정보 |

---

## 디렉토리 구조

```
database/
├── __init__.py            # 패키지 초기화
├── db_migration.py        # 마이그레이션 메인 스크립트
├── DB_MIGRATION_GUIDE.md  # 본 문서
├── nh_credit_risk.db      # DuckDB 데이터베이스 파일 (자동 생성)
└── logs/
    └── db_migration.log   # 실행 로그
```

---

## 안정성 보장

### 메모리 누수 방지
```python
# 루프 내 매 파일 적재 후
del df           # DataFrame 명시적 해제
gc.collect()     # 가비지 컬렉터 강제 호출
```

### 컨텍스트 매니저
```python
# 파일 Lock 및 동시성 에러 방지
with duckdb.connect('database/nh_credit_risk.db') as con:
    # 모든 DB 연산은 이 블록 안에서만 실행
    con.execute("CREATE OR REPLACE TABLE ...")
```

### 에러 핸들링
- 파일 로드 실패 시 해당 파일 스킵 후 다음 파일 계속 처리
- `#N/A` 오류 행 자동 필터링
- 엑셀 잠금 파일(`~$`) 자동 제외
