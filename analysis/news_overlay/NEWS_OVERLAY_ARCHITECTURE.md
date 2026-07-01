# 📊 뉴스 감성 기반 차주별 리스크 오버레이 지표 산출 파이프라인

> **News Sentiment-Based Risk Overlay Pipeline (DuckDB Refactored)**
> 
> 매일 수집되는 경제 뉴스 텍스트 분석 결과와 내부 차주(기업) 마스터 정보를 결합하여,
> 최종 신용평점 조정에 사용할 **뉴스 감성 기반 차주별 리스크 오버레이 지표(Overlay Index)**를 산출합니다.

---

## 목차

1. [아키텍처 개요](#아키텍처-개요)
2. [Phase 1: 매크로 키워드 감성 분석, 휴일 롤오버 및 평활화](#phase-1-매크로-키워드-감성-분석-휴일-롤오버-및-평활화)
3. [Phase 2: 업종 임베딩 매칭 기반 차주별 유사도 DuckDB 캐싱](#phase-2-업종-임베딩-매칭-기반-차주별-유사도-duckdb-캐싱)
4. [Phase 3: 최종 차주별 리스크 스코어 가중평균 산출](#phase-3-최종-차주별-리스크-스코어-가중평균-산출)
5. [모델링 지침 바인딩](#모델링-지침-바인딩)
6. [디렉토리 구조](#디렉토리-구조)
7. [실행 방법](#실행-방법)
8. [입출력 데이터 명세](#입출력-데이터-명세)
9. [운영 가이드](#운영-가이드)

---

## 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│              3단계 데이터 공학 아키텍처 (DuckDB 활용)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Phase 1] Macro Level (Pandas)                                 │
│  ┌────────────────────────────────────────┐                     │
│  │  df_news (date, keyword, score)        │                     │
│  │           ↓                            │                     │
│  │  주말/공휴일 뉴스 익영업일 전향(Roll-over) │                     │
│  │           ↓                            │                     │
│  │  키워드별 90일 이동평균 평활화 (MA90D)    │                     │
│  └────────────────────────────────────────┘                     │
│               ↓                                                 │
│  [Phase 2] Micro Level (Static Cache)                           │
│  ┌────────────────────────────────────────┐                     │
│  │  기업 마스터 (업종코드 → 한글 업종명)     │                     │
│  │           ↓                            │                     │
│  │  Sentence Embedding (키워드 ↔ 업종명)    │                     │
│  │           ↓                            │                     │
│  │  Cosine Similarity 연산 후              │                     │
│  │  DuckDB: lookup_industry_keyword_sim   │                     │
│  │  (최초 1회 생성, 영구 캐싱)              │                     │
│  └────────────────────────────────────────┘                     │
│               ↓                                                 │
│  [Phase 3] Fusion Level (DuckDB SQL)                            │
│  ┌────────────────────────────────────────┐                     │
│  │  SQL LEFT JOIN:                         │                     │
│  │  가중 평균 (Weighted Average) 적용:     │                     │
│  │  Σ(ma90d × similarity) / Σ(similarity)  │                     │
│  │           ↓                            │                     │
│  │  clip(-1.0, +1.0) → CORP_NEWS_RISK_INDEX│                    │
│  │           ↓                            │                     │
│  │  [(DuckDB) mart_news_overlay_index_daily│                     │
│  └────────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: 매크로 키워드 감성 분석, 휴일 롤오버 및 평활화

### 목적
일별 뉴스 텍스트의 극심한 노이즈 방지 및 주말/공휴일 뉴스의 누락 방지.

### 핵심 로직
1. **시계열 무결성 제약 (중요)**:
   주말/공휴일 뉴스를 롤오버한 직후, 동일 일자(date)와 동일 키워드(keyword) 기준으로 감성 점수를 반드시 평균(Mean) 가집계(Aggregation)합니다. 이를 통해 하루 내에 동일 키워드가 중복 적재되어 Rolling Window 통계량이 왜곡되는 현상을 차단합니다.
2. **휴일 롤오버 (Forward Roll-over)**: 
   파이썬 `holidays` 라이브러리를 활용해 주말 및 법정 공휴일에 발생한 뉴스 데이터를 다음 첫 번째 영업일(월요일 등)로 이관(Roll-over)시킵니다.
3. **90일 이동평균**: 
   이후 단기 노이즈 흡수를 위해 키워드별로 90영업일 윈도우 이동평균을 적용합니다.

---

## Phase 2: 업종 임베딩 매칭 기반 차주별 유사도 DuckDB 캐싱

### 목적
뉴스 키워드와 차주의 업종 간 연관성을 정량화하고, **GPU 및 CPU 연산 부하를 0으로 통제**합니다.

### 핵심 로직 (정적 매스터 사전)
- 매일 배치 작업 시 차주와 키워드 간의 임베딩을 전수 연산하지 않습니다.
- 키워드 풀과 표준산업분류 업종명 간의 코사인 유사도 조합을 최초 1회 생성하여, DuckDB 내 `lookup_industry_keyword_sim` 테이블에 캐싱합니다.
- 이후 배치에서는 해당 매스터 사전을 단순 SQL `LEFT JOIN`으로 호출하기만 합니다.

---

## Phase 3: 최종 차주별 리스크 스코어 가중평균 산출

### 목적
스코어 왜곡(점수 무한 증식, 클리핑 편향 등)을 막기 위해 가중 평균 방식을 적용합니다.

### 핵심 수식

$$
\text{CORP\_NEWS\_RISK\_INDEX}_{i,t} = \text{clip}\left( \frac{\sum_{k \in K_t} \left( \text{ma90d}_{k,t} \times \text{sim\_weight}_{i,k} \right)}{\sum_{k \in K_t} \text{sim\_weight}_{i,k}}, -1.0, +1.0 \right)
$$

### 유효 연관성 컷오프(Cut-off) 규칙
무관한 대량의 노이즈 뉴스의 낮은 유사도가 가중평균의 분모를 키워 핵심 리스크 시그널을 희석(Dilution)시키는 현상을 방지하기 위해 **유사도 컷오프 지수(`SIMILARITY_THRESHOLD = 0.25`)**를 도입합니다. 오직 `similarity_weight >= 0.25` 조건을 충족하는 유효 활성 키워드 집합에 대해서만 가중평균 수식을 적용합니다.

### 결합 연산 구조 (DuckDB SQL)
Pandas 기반의 인메모리 연산을 피하고, DuckDB 커넥션을 통해 3개의 테이블/데이터프레임 조인으로 처리:
1. `df_corp` (기업 마스터)
2. `lookup_industry_keyword_sim` (Phase 2 캐시)
3. `df_news_smoothed` (Phase 1 결과)

0으로 나누기 방지를 위해 DuckDB의 `NULLIF()` 함수가 적용됩니다.

---

## 모델링 지침 바인딩

### ⚠️ 지침 2: Calendar Date Index 매칭
- **휴일 롤오버 적용**: 단순 Shift가 아닌, 달력 기반 휴일 마스터(`holidays.KR`)를 활용한 영업일 전향 롤오버.

### 🔒 오버레이 격리 원칙
- 결과물은 모델 훈련용 마트가 아닌 **오버레이 전용 마트(`mart_news_overlay_index_daily`)**에 별도로 저장됩니다.

---

## 입출력 데이터 명세

### 입력 #1: 일별 뉴스 감성 데이터 (`daily_news_sentiment.csv`)
| 컬럼 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `date` | string | ✅ | 날짜 (YYYY-MM-DD) |
| `keyword` | string | ✅ | 경제 뉴스 키워드 |
| `sentiment_score` | float | ✅ | 감성 점수 (-1.0 ~ +1.0) |

### 입력 #2: 기업 마스터 (`UPCHE_TOT.txt`)
| 컬럼 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `V_BZNO` | string | ✅ | 사업자번호 (차주 고유키) |
| `STD_INDS_CFC` | string | ✅ | 표준산업분류 5자리 코드 |

### 출력: 뉴스 리스크 오버레이 지표 (`mart_news_overlay_index_daily`)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `date` | timestamp | 기준 날짜 (영업일 기준) |
| `V_BZNO` | string | 차주 고유키 |
| `industry_name` | string | 한글 업종명 |
| `CORP_NEWS_RISK_INDEX` | double | 최종 가중 평균 리스크 지표 (-1.0 ~ +1.0) |
| `active_keyword_count` | bigint | 해당 일자 활성 키워드 수 |

---

## 운영 가이드

### 일별 배치 스케줄
```
06:00  NLP 파이프라인 → daily_news_sentiment.csv 생성
06:30  news_overlay_pipeline.py 실행 
        (내부적으로 DuckDB nh_credit_risk.db 연결 및 SQL 조인 처리)
07:00  운영계 스코어카드 시스템 → mart_news_overlay_index_daily 테이블 참조
```

### 🔒 DuckDB 동시성 락킹(Database Locked) 방어 가이드
DuckDB의 단일 프로세스 단독 쓰기(Write) 제약 조건에 따른 배치 실패를 막기 위해 다음 설정을 강제합니다.
1. `news_overlay_pipeline.py` 스크립트 내 DuckDB 커넥션은 작업 완료 즉시 종료되도록 `with duckdb.connect(...) as con:` 컨텍스트 매니저를 엄격히 유지합니다.
2. 리스크 관리자의 데이터 검증 도구(DBeaver 등)에서는 해당 DB 연결 프로필 설정을 반드시 **`Connection Mode: Read-only (읽기 전용)`**로 커스텀 설정하여, 아침 배치 스크립트의 쓰기 트랜잭션 락 충돌을 원천 차단해야 합니다.
