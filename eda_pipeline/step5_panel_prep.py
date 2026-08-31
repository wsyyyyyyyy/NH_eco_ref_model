"""
======================================================================
Step 5 — 패널 전처리 & 12개월 타겟 생성
======================================================================
STAGE 3 리팩터링:
  3-1 IS_BUDO_12M 을 merge(on=V_BZNO) 가 아니라 merge_asof(forward) 로 만든다.
      기존 방식은 다중부도 기업의 전 구간을 복제해 양성을 4.89배 과대계상했다.
  3-2 부도 진행 중 구간을 스파인에서 제거한다.
  3-3 우측절단(CENSOR_END) 처리를 명시한다.
  3-4 BZSCAL_C(2026 스냅샷) 필터를 segment_mode 로 대체한다. 기본값은 'none'.
  3-5 결측을 3가지 유형으로 분리한다. JEMU 는 0으로 채우지 않는다.
  3-6 ffill 을 OBV 월단위 변수에만, 최대 3개월로 제한한다.

실행:
    python eda_pipeline/step5_panel_prep.py                  # segment_mode=none
    python eda_pipeline/step5_panel_prep.py --segment bzscal
    python eda_pipeline/step5_panel_prep.py --compare        # 3종 비교표만 출력
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 프로젝트 루트를 sys.path에 추가 (스크립트 단독 실행 대응)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eda_pipeline import config
from eda_pipeline.leaky_cols import LEAK_CONFIRMED

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# ── 상수 ────────────────────────────────────────────────────────────
HORIZON_MONTHS = 12
# 부도 데이터가 존재하는 마지막 월. BASE_YM + HORIZON 이 이 값을 넘으면
# 12개월 라벨을 확정할 수 없으므로(우측절단) 제외한다.
CENSOR_END = '202605'

# 부도 발생 월 자체를 제외할지. True 면 [부도월, 종료월], False 면 (부도월, 종료월].
# 부도 발생 월의 행은 이미 부도 상태이므로 기본값 True.
EXCLUDE_DEFAULT_MONTH = True

# 규모 세그먼트. BZSCAL_C 는 UPCHE 의 2026 스냅샷이라 관측시점에 붙이면 선택편향이 생긴다.
SEGMENT_MODES = ('none', 'bzscal', 'sales')
BZSCAL_KEEP = 4.0
# 부도 신호가 거의 없는 규모군 (대기업2 / 중견6 / 기타9, 989사 중 부도 4건).
# 기본값은 제외하지 않는다. BZSCAL 스냅샷 기반이므로 확정 정책이 아니다.
LOW_SIGNAL_BZSCAL = ['2', '6', '9']
EXCLUDE_LOW_SIGNAL = False
# 'sales' 모드에서 남길 매출 분위. 기준값은 협의 전이므로 잠정값이다.
SALES_SEGMENT_KEEP = [1, 2, 3]

# ffill 은 월단위로 관측되는 OBV 계열에만, 최대 이월 개월수를 두고 적용한다.
# JEMU 는 STAGE 2의 as-of 조인이 이미 시점 정합성을 처리하므로 대상에서 제외한다.
FFILL_PREFIXES = ('OBV_',)
FFILL_LIMIT = 3


def _ym_idx(s):
    """YYYYMM -> 월 일련번호(int)."""
    s = s.astype(str).str.strip()
    return (s.str[:4].astype(int) * 12 + s.str[4:6].astype(int)).values


def load_budo_events(df=None):
    """부도 이벤트 원천을 읽는다.

    스파인은 '관측시점 후보'만 정의하고 부도 이벤트를 제한하지 않는다.
    부도가 나면 여신이 정리되어 VH_OBV_DTL 레코드가 사라지므로 부도월이 스파인 밖인
    경우가 전체의 약 49%다. 이를 스파인으로 걸러내면 그 기업들이 통째로 음성이 되어
    '조용히 부도나고 여신이 정리된' 유형(376사)이 학습에서 사라진다.

    step2 가 남긴 budo_events.csv 를 쓴다. 원천보다 오래된 파일이면 조용히 폴백하지
    않고 예외를 발생시킨다. 조용한 폴백은 잘못된 결과를 만들고도 알아채지 못하게 한다.
    """
    path = config.budo_events_path()
    meta_path = config.budo_events_meta_path()

    if not path.exists():
        raise FileNotFoundError(
            f"{path} 가 없습니다. step2 를 먼저 재실행하세요.\n"
            f"  python eda_pipeline/run.py")

    _assert_events_fresh(meta_path)

    ev = pd.read_csv(path, dtype={'V_BZNO': str, 'DEFAULT_YM': str,
                                  'RECOVER_YM': str})
    logging.info(f"부도 이벤트 원천 {path.name}: {len(ev):,}건 "
                 f"(정상화 {int(ev['IS_RECOVERED'].fillna(0).sum()):,}건)")
    return ev


def _assert_events_fresh(meta_path):
    """budo_events.csv 가 input/ 원천보다 오래되었으면 중단한다."""
    src = config.budo_source_path()
    if src is None:
        logging.warning("input/ 에서 부도 원천 파일을 찾지 못해 신선도 검사를 건너뜁니다.")
        return
    if not meta_path.exists():
        raise FileNotFoundError(
            f"{meta_path.name} 이 없습니다. budo_events.csv 의 생성 시점을 확인할 수 없습니다.\n"
            f"  step2 를 먼저 재실행하세요: python eda_pipeline/run.py")

    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    cur_m, cur_s = round(src.stat().st_mtime, 3), src.stat().st_size
    old_m, old_s = meta.get('source_mtime'), meta.get('source_size')
    if old_m is None or abs(cur_m - old_m) > 1.0 or cur_s != old_s:
        raise RuntimeError(
            f"budo_events.csv 가 원천 데이터보다 오래되었습니다 (스테일).\n"
            f"  원천 : {src.name}  mtime={cur_m}  size={cur_s:,}\n"
            f"  메타 : mtime={old_m}  size={old_s if old_s is None else f'{old_s:,}'}\n"
            f"  step2 를 먼저 재실행하세요: python eda_pipeline/run.py")
    logging.info(f"부도 이벤트 신선도 OK (원천 {src.name} mtime {cur_m} 일치, "
                 f"생성 {meta.get('created_at')})")


def calculate_business_age(base_ym, etb_dt):
    base = pd.to_datetime(base_ym.astype(str), format='%Y%m', errors='coerce')
    etb_str = etb_dt.astype(str).str.replace(r'\.0$', '', regex=True)
    etb = pd.to_datetime(etb_str, format='%Y%m%d', errors='coerce')
    return ((base - etb).dt.days / 365.25).clip(lower=0)


# ====================================================================
# 3-1 12개월 타겟
# ====================================================================

def generate_12m_target(df, events):
    """(V_BZNO, BASE_YM) 별로 'BASE_YM < 부도월 <= BASE_YM+12' 인 부도가 있으면 1.

    관측시점 t 는 스파인에 있어야 하지만(예측을 수행하는 시점이므로),
    부도월 t+k 는 스파인에 있을 필요가 없다(이미 이탈한 차주이므로).
    따라서 events 는 스파인이 아니라 부도 원천(budo_events.csv)에서 온다.

    merge(on='V_BZNO') 는 다중부도 기업의 전 구간을 복제하므로 절대 쓰지 않는다.
    merge_asof(direction='forward', allow_exact_matches=False) 로
    각 행의 '다음 부도월' 하나만 붙인다. 좌측 행수가 그대로 보존된다.
    """
    n_before = len(df)

    events = events[['V_BZNO', 'DEFAULT_YM']].copy()
    events['V_BZNO'] = events['V_BZNO'].astype(str)
    events['_EV'] = _ym_idx(events['DEFAULT_YM'])
    events = (events[['V_BZNO', '_EV']]
              .drop_duplicates()
              .sort_values('_EV', kind='mergesort'))

    left = pd.DataFrame({
        'V_BZNO': df['V_BZNO'].astype(str).values,
        '_B': _ym_idx(df['BASE_YM']),
        '_row': np.arange(len(df)),
    }).sort_values('_B', kind='mergesort')

    merged = pd.merge_asof(
        left, events,
        left_on='_B', right_on='_EV', by='V_BZNO',
        direction='forward', allow_exact_matches=False,
    ).sort_values('_row', kind='mergesort')

    gap = merged['_EV'].values - merged['_B'].values
    df['IS_BUDO_12M'] = ((gap > 0) & (gap <= HORIZON_MONTHS)).astype(int)

    assert len(df) == n_before, f"타겟 생성에서 행수 변동: {n_before} -> {len(df)}"
    pos = int(df['IS_BUDO_12M'].sum())
    firms = df.loc[df['IS_BUDO_12M'] == 1, 'V_BZNO'].nunique()
    logging.info(f"[3-1] IS_BUDO_12M={pos:,} ({pos/len(df)*100:.3f}%), 기여기업 {firms:,}사, "
                 f"행수 {n_before:,} 유지 (부도 이벤트 {len(events):,}건)")
    return df


# ====================================================================
# 3-2 부도 진행 중 구간 제외
# ====================================================================

def drop_in_default_periods(df, events):
    """부도 발생 ~ 정상화 구간의 (기업, 월) 행을 제거한다.

      IS_RECOVERED=0 : 부도월부터 패널 끝까지 제거
      IS_RECOVERED=1 : 부도월 ~ 정상화월 구간만 제거. 그 이후는 정상 관측치로 복귀.
      복귀 이후 재부도는 새로운 이벤트로 취급된다 (구간이 각각 계산되므로 자동).

    이미 부도 상태인 기업을 학습에 넣으면 '부도기업은 부도난다'를 학습하게 된다.
    """
    n_before = len(df)
    ev = events[['V_BZNO', 'DEFAULT_YM', 'IS_RECOVERED', 'RECOVER_YM']].copy()
    ev['V_BZNO'] = ev['V_BZNO'].astype(str)
    if ev.empty:
        logging.info("[3-2] 부도 이벤트 없음 — 제거 대상 없음")
        return df

    ev['_D'] = _ym_idx(ev['DEFAULT_YM'])
    ev['_R'] = np.where(
        ev['IS_RECOVERED'].fillna(0).astype(int) == 1,
        pd.to_numeric(ev['RECOVER_YM'], errors='coerce')
          .fillna(0).astype('int64').astype(str).str.zfill(6)
          .pipe(lambda s: s.str[:4].astype(int) * 12 + s.str[4:6].astype(int)),
        np.iinfo(np.int32).max,
    )
    # 정상화월이 부도월보다 앞서면 데이터 오류이므로 미정상화로 간주한다.
    bad = ev['_R'] < ev['_D']
    if bad.any():
        logging.warning(f"[3-2] 정상화월 < 부도월 인 이벤트 {int(bad.sum())}건 → 미정상화로 처리")
        ev.loc[bad, '_R'] = np.iinfo(np.int32).max

    idx = _ym_idx(df['BASE_YM'])
    groups = df.assign(_v=df['V_BZNO'].astype(str)).groupby('_v', sort=False).indices
    drop = np.zeros(len(df), dtype=bool)
    lo_off = 0 if EXCLUDE_DEFAULT_MONTH else 1

    n_rec = n_unrec = 0
    for v, d, r in zip(ev['V_BZNO'].values, ev['_D'].values, ev['_R'].values):
        pos = groups.get(v)
        if pos is None:
            continue
        sub = idx[pos]
        hit = (sub >= d + lo_off) & (sub <= r)
        if hit.any():
            drop[pos[hit]] = True
        if r == np.iinfo(np.int32).max:
            n_unrec += 1
        else:
            n_rec += 1

    df = df.loc[~drop].copy()
    logging.info(f"[3-2] 부도 진행 중 구간 제거: {n_before:,} -> {len(df):,} "
                 f"({len(df) - n_before:+,}행)  "
                 f"[미정상화 이벤트 {n_unrec}, 정상화 이벤트 {n_rec}, "
                 f"부도월 포함제거={EXCLUDE_DEFAULT_MONTH}]")
    return df


# ====================================================================
# 3-3 우측절단
# ====================================================================

def apply_censoring(df):
    """BASE_YM + HORIZON 이 CENSOR_END 를 넘으면 12개월 라벨이 확정 불가하므로 제외."""
    n_before = len(df)
    limit = int(CENSOR_END[:4]) * 12 + int(CENSOR_END[4:6])
    keep = (_ym_idx(df['BASE_YM']) + HORIZON_MONTHS) <= limit
    df = df.loc[keep].copy()
    logging.info(f"[3-3] 우측절단(CENSOR_END={CENSOR_END}, +{HORIZON_MONTHS}개월): "
                 f"{n_before:,} -> {len(df):,} ({len(df) - n_before:+,}행)")
    return df


# ====================================================================
# 3-4 세그먼트
# ====================================================================

def add_sales_segment(df):
    """관측시점 매출액(JEMU_121000) 분위. 경계는 반드시 TRAIN 구간에서만 산출한다.

    VALID 로 경계를 만들면 검증구간 정보가 학습에 새어 들어간다.
    """
    sales = pd.to_numeric(df.get('JEMU_121000'), errors='coerce')
    if sales is None or sales.isna().all():
        df['SEG_SALES_Q'] = np.nan
        df['SEG_SALES_MISSING_YN'] = 1
        return df, None

    train = df['SPLIT'] == 'TRAIN'
    bounds = sales[train].quantile([.25, .50, .75]).values
    q = np.digitize(sales.values, bounds, right=True) + 1
    q = q.astype(float)
    q[sales.isna().values] = np.nan
    df['SEG_SALES_Q'] = q
    df['SEG_SALES_MISSING_YN'] = sales.isna().astype(int)
    logging.info(f"[3-4] SEG_SALES_Q 경계(TRAIN {int(train.sum()):,}행에서만 산출) = "
                 f"{[f'{b:,.0f}' for b in bounds]}")
    logging.info(f"       매출액 결측 = {df['SEG_SALES_MISSING_YN'].mean()*100:.2f}%")
    return df, bounds


def apply_segment(df, mode):
    """세그먼트 필터. 기본값 'none' 은 필터가 아니라 리포팅 축으로만 쓴다."""
    if mode not in SEGMENT_MODES:
        raise ValueError(f"알 수 없는 segment_mode: {mode!r} (가능: {SEGMENT_MODES})")
    n_before = len(df)

    if mode == 'none':
        out = df
    elif mode == 'bzscal':
        out = df[df['BZSCAL_C'] == BZSCAL_KEEP].copy()
    else:  # sales
        out = df[df['SEG_SALES_Q'].isin(SALES_SEGMENT_KEEP)].copy()

    if EXCLUDE_LOW_SIGNAL and 'BZSCAL_C' in out.columns:
        low = out['BZSCAL_C'].astype('Int64').astype(str).isin(LOW_SIGNAL_BZSCAL)
        out = out[~low].copy()

    logging.info(f"[3-4] segment_mode={mode}: {n_before:,} -> {len(out):,}행")
    return out


def segment_report(df):
    """3종 세그먼트의 표본수 / 부도율 / 부도기업 보존율 비교표."""
    base_firms = df.loc[df['IS_BUDO_12M'] == 1, 'V_BZNO'].nunique()
    rows = []
    for mode in SEGMENT_MODES:
        sub = apply_segment(df, mode)
        firms = sub.loc[sub['IS_BUDO_12M'] == 1, 'V_BZNO'].nunique()
        rows.append({
            'segment_mode': mode,
            '행수': len(sub),
            '기업수': sub['V_BZNO'].nunique(),
            '양성수': int(sub['IS_BUDO_12M'].sum()),
            '부도율%': round(sub['IS_BUDO_12M'].mean() * 100, 4),
            '부도기업': firms,
            '보존율%': round(firms / base_firms * 100, 1) if base_firms else np.nan,
        })
    return pd.DataFrame(rows)


# ====================================================================
# 3-5 / 3-6 결측 처리
# ====================================================================

def limited_ffill(df):
    """[3-6] OBV 계열만, 최대 FFILL_LIMIT 개월까지 이월한다."""
    cols = [c for c in df.columns
            if c.startswith(FFILL_PREFIXES) and df[c].dtype != object]
    if not cols:
        return df
    df = df.sort_values(['V_BZNO', 'BASE_YM'], kind='mergesort')
    before = df[cols].isna().sum().sum()
    df[cols] = df.groupby('V_BZNO', sort=False)[cols].ffill(limit=FFILL_LIMIT)
    after = df[cols].isna().sum().sum()
    logging.info(f"[3-6] ffill 대상 {len(cols)}컬럼(OBV만, limit={FFILL_LIMIT}개월): "
                 f"결측 {before:,} -> {after:,}")
    return df


def process_missing_values(df):
    """[3-5] 결측을 3유형으로 분리해 처리한다.

      유형 1 구조적 부재 (= 0 이 맞음)  : 0 채움 + HAS_xxx_YN 플래그
      유형 2 미해당                     : 금액은 0, 비율은 NaN 유지 + HAS_xxx_YN
      유형 3 진짜 결측                  : NaN 그대로 유지 + xxx_MISSING_YN
                                          (LightGBM 이 NaN 을 네이티브 처리한다)

    JEMU_* 는 유형 3이다. 절대 0으로 채우지 않는다.
    """
    # ── 유형 1: 구조적 부재 ──────────────────────────────────────
    ac12 = [c for c in df.columns if c.startswith('AC12_')]
    if ac12:
        df['HAS_AC12_YN'] = df[ac12].notna().any(axis=1).astype(int)
        df[ac12] = df[ac12].fillna(0.0)

    obv_amt = [c for c in df.columns
               if c.startswith('OBV_') and (c.endswith('_AM') or c.endswith('_BAC'))]
    obv_rate = [c for c in df.columns
                if c.startswith('OBV_') and (c.endswith('_POD') or c.endswith('_ELGD'))]
    obv_all = [c for c in df.columns if c.startswith('OBV_')]
    if obv_all:
        df['HAS_OBV_YN'] = df[obv_all].notna().any(axis=1).astype(int)
        df[obv_amt] = df[obv_amt].fillna(0.0)   # 여신 없음 = 잔액 0
        # PD / LGD 는 0 이 '위험 없음'을 뜻해버리므로 NaN 유지

    # ── 유형 2: 미해당 ───────────────────────────────────────────
    aa17_lvl = [c for c in df.columns
                if c.startswith(('AA17_YTD_', 'AA17_QTR_')) and c != 'AA17_YTD_Q']
    aa17_flag = [c for c in df.columns if c.startswith('AA17_') and c.endswith('_YN')]
    if any(c.startswith('AA17_') for c in df.columns):
        df['HAS_AA17_YN'] = df[aa17_lvl].notna().any(axis=1).astype(int) if aa17_lvl else 0
        df[aa17_lvl] = df[aa17_lvl].fillna(0.0)      # 생산판매 실적 없음 = 0
        df[aa17_flag] = df[aa17_flag].fillna(0)
        # AA17_YOY_* / AA17_EXPORT_RATIO 는 비율이므로 NaN 유지 (0 은 실제 값)

    # ── 유형 3: 진짜 결측 → NaN 유지 + 플래그 ────────────────────
    # 감사의견: 코드는 범주형, 파생 플래그는 0/1.
    # '00'(자료없음) / '50'(감사미필)은 비외감이라 감사의견이 미해당인 것이며 결측이 아니다.
    aud_flags = [c for c in df.columns if c.startswith('JEMU_AUD_') and c.endswith('_YN')]
    aud_all = [c for c in df.columns if c.startswith('JEMU_AUD_')]

    # JEMU 미제출 판정은 자산총계(115000) 단독으로 한다.
    # 자산총계는 어떤 재무제표에도 반드시 존재하므로 '재무 미제출' 기준으로 적절하다.
    # 파생 전체의 결측 여부(JEMU_ALL_NA_YN)는 참고용으로 따로 남긴다.
    jemu_all = [c for c in df.columns if c.startswith('JEMU_') and c not in aud_all]
    if 'JEMU_115000' in df.columns:
        df['JEMU_MISSING_YN'] = df['JEMU_115000'].isna().astype(int)
    # JEMU_ALL_NA_YN 은 만들지 않는다. as-of 조인이 매칭 실패 시 모든 JEMU 컬럼을
    # 한꺼번에 NaN 으로 만들므로 JEMU_MISSING_YN 과 구조적으로 항상 동일하다(실측 차이 0행).

    type3 = {
        'C302': [c for c in df.columns if c in ('C302_CRI_ORD',)],
        'CG01': [c for c in df.columns if c == 'CG01_KIS_SCORE'],
        'AA10': [c for c in df.columns if c.startswith('AA10_')],
        'AGE':  [c for c in df.columns if c == 'BUSINESS_AGE'],
    }
    for tag, cols in type3.items():
        if not cols:
            continue
        df[f'{tag}_MISSING_YN'] = df[cols].isna().all(axis=1).astype(int)

    if aud_flags:
        df[aud_flags] = df[aud_flags].fillna(0).astype(int)
    if 'JEMU_AUD_OPI_DSC' in df.columns:
        df['JEMU_AUD_OPI_DSC'] = df['JEMU_AUD_OPI_DSC'].astype('object').fillna('-1')

    # C302 의 D / NR / R 플래그는 등급 자체가 없으면 0 (해당 없음)
    for c in ('C302_IS_D_YN', 'C302_IS_NR_YN', 'C302_IS_R_YN'):
        if c in df.columns:
            df[c] = df[c].fillna(0)

    # 범주형 코드: 별도 범주값 '-1'
    for c in ('STD_INDS_CFC', 'OBV_ELYWRN_OBV_GRD_DSC',
              'GRD_CRDEVL_PTTP_DSC', 'GRD_LS_NICS_GRDC'):
        if c in df.columns:
            df[c] = df[c].astype('object').fillna('-1')

    kept = df.isna().sum()
    kept = kept[kept > 0]
    logging.info(f"[3-5] NaN 을 의도적으로 남긴 컬럼 {len(kept)}개 "
                 f"(LightGBM 네이티브 처리 대상)")
    for c, n in kept.sort_values(ascending=False).head(8).items():
        logging.info(f"        {c:<24} {n:>9,} ({n/len(df)*100:5.2f}%)")
    return df


# ====================================================================
# 파이프라인
# ====================================================================

def prepare(df):
    """세그먼트 분기 이전까지의 공통 전처리 (3-1 ~ 3-4의 분위 산출)."""
    logging.info(f"Initial shape: {df.shape}")
    events = load_budo_events(df)
    df = generate_12m_target(df, events)
    pos_before = int(df['IS_BUDO_12M'].sum())
    df = drop_in_default_periods(df, events)
    pos_after = int(df['IS_BUDO_12M'].sum())
    logging.info(f"[3-2] 양성 {pos_before:,} -> {pos_after:,} ({pos_after-pos_before:+,}). "
                 f"양성은 t < 부도월 인 행이므로 크게 줄면 안 된다.")
    df = apply_censoring(df)
    df, _ = add_sales_segment(df)
    return df


def finalize(df, segment_mode):
    df = apply_segment(df, segment_mode)

    if 'ETB_DT' in df.columns:
        df['BUSINESS_AGE'] = calculate_business_age(df['BASE_YM'], df['ETB_DT'])

    drop_cols = [
        'CONM', 'BZSCAL_C', 'ETB_DT', 'EMPCN',
        'GRD_LS_NICS_GRDC', 'GRD_CRDEVL_PTTP_DSC', 'OBV_RZVL_POD',
        'C302_CRI_GRD', 'IS_BUDO_IN_SPINE_YN', 'IS_RECOVERED', 'RECOVER_YM',
    ] + LEAK_CONFIRMED
    actual = [c for c in drop_cols if c in df.columns]
    logging.info(f"Dropping columns ({len(actual)}): {actual}")
    df = df.drop(columns=actual)

    df = limited_ffill(df)
    df = process_missing_values(df)
    return df


def main(spine_mode=None, segment_mode='none', compare=False, save=True):
    spine = spine_mode or config.SPINE_MODE
    input_path = config.panel_path(spine)
    logging.info(f"Loading data from {input_path}")
    df = config.read_panel(input_path, dtype={'ETB_DT': str, 'BASE_YM': str,
                                              'RECOVER_YM': str})
    for _c in ('ETB_DT', 'BASE_YM', 'RECOVER_YM'):
        if _c in df.columns and df[_c].dtype != object:
            df[_c] = df[_c].astype('string').str.replace(r'\.0$', '', regex=True)
    df = prepare(df)

    logging.info("\n[3-4] 세그먼트 비교표")
    rep = segment_report(df)
    for line in rep.to_string(index=False).splitlines():
        logging.info("  " + line)

    if 'SEG_SALES_Q' in df.columns:
        logging.info("\n[3-4] SEG_SALES_Q 분위별 부도율 (매출 클수록 낮아야 정상)")
        g = (df.groupby('SEG_SALES_Q')['IS_BUDO_12M']
               .agg(행수='size', 양성='sum', 부도율=lambda s: round(s.mean() * 100, 4)))
        for line in g.to_string().splitlines():
            logging.info("  " + line)
        logging.info("\n[3-4] BZSCAL_C x SEG_SALES_Q 교차표 (행수)")
        ct = pd.crosstab(df['BZSCAL_C'], df['SEG_SALES_Q'], dropna=False)
        for line in ct.to_string().splitlines():
            logging.info("  " + line)

    if compare:
        return rep

    out = finalize(df, segment_mode)
    if save:
        output_path = config.save_panel(
            out, config.OUTPUT_DIR / f'nh_panel_prep_{spine}_{segment_mode}.csv')
        logging.info(f"Saved to {output_path.name}. Final shape: {out.shape}")
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--spine', default=None, choices=['obv', 'full', 'legacy'])
    ap.add_argument('--segment', default='none', choices=list(SEGMENT_MODES))
    ap.add_argument('--compare', action='store_true')
    a = ap.parse_args()
    main(spine_mode=a.spine, segment_mode=a.segment, compare=a.compare)
