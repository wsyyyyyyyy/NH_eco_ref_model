"""
======================================================================
STAGE 6 B축 — 패널 변종 생성
======================================================================
각 변종은 STAGE 1~5 의 수정 **하나만** 되돌린 패널이다. 나머지는 최종형 그대로
두어야 차이가 그 수정 하나로 귀속된다.

  B1  행 중복 미제거   generate_12m_target 을 merge(on='V_BZNO') 로 복원
  B4  CRIF 시점정합    CRDBD_OCU_YY(YYYYMM)를 월 단위로 as-of 조인
  B6  AC12 시점정합    BAS_YM(YYYYMM)를 월 단위로 as-of 조인
  B5  CG01 1년 시차    연도별 wide 원천이라 월 재구성 불가. 1년 시차만 적용

B4/B6 는 교정 방식이 같다. 원천에 월 정보가 있는데 step2 가 `str[:4]` 로 잘라
연 단위로 붙인 것이 원인이므로, 월 단위 backward as-of 로 바꾸고 관측시점
이전 레코드만 쓴다.

Usage
-----
    python -m eda_pipeline.step32_panel_variants --variant B1
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd

from eda_pipeline import config
from eda_pipeline import step5_panel_prep as step5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("variants")

OUT_DIR = config.OUTPUT_DIR
HORIZON_MONTHS = 12


# ══════════════════════════════════════════════════════════════════════
# B1 — 행 중복 미제거
# ══════════════════════════════════════════════════════════════════════

def generate_12m_target_legacy(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """구 방식 복원: merge(on='V_BZNO') 로 붙인다.

    step5_panel_prep.py.bak:26 의 로직이다. 다중부도 기업은 부도 건수만큼
    좌측 행이 복제되므로 행수가 늘고 양성이 부풀려진다.

    ★ 이벤트 원천은 현행과 동일하게 budo_events.csv 를 쓴다.
      .bak 은 스파인 안의 IS_BUDO_YN 만 봤는데, 그 차이까지 함께 되돌리면
      "행 중복" 과 "이벤트 원천" 두 변화가 섞여 B1 이 무엇을 재는지 흐려진다.
      B1 은 행 중복 효과만 분리해 측정한다.
    """
    n_before = len(df)
    ev = events[["V_BZNO", "DEFAULT_YM"]].copy()
    ev["V_BZNO"] = ev["V_BZNO"].astype(str)
    ev = ev.drop_duplicates()

    df = df.copy()
    df["V_BZNO"] = df["V_BZNO"].astype(str)
    merged = df.merge(ev, on="V_BZNO", how="left")          # ← 행 복제 지점

    # 좌측 조인이라 부도 이력이 없는 기업은 DEFAULT_YM 이 NaN 이다.
    # step5._ym_idx 는 문자열 슬라이스 후 astype(int) 라 NaN 을 못 받는다.
    ym = merged["DEFAULT_YM"].astype("string")
    has_ev = ym.notna()
    d = np.full(len(merged), np.nan)
    if has_ev.any():
        d[has_ev.values] = step5._ym_idx(ym[has_ev])
    gap = d - step5._ym_idx(merged["BASE_YM"])
    merged["IS_BUDO_12M"] = ((gap > 0) & (gap <= HORIZON_MONTHS)).astype(int)
    merged = merged.drop(columns=["DEFAULT_YM"], errors="ignore")

    pos = int(merged["IS_BUDO_12M"].sum())
    firms = merged.loc[merged["IS_BUDO_12M"] == 1, "V_BZNO"].nunique()
    dup = len(merged) - n_before
    log.info(f"[B1] 행수 {n_before:,} -> {len(merged):,} ({dup:+,} 복제)")
    log.info(f"[B1] IS_BUDO_12M={pos:,} ({pos/len(merged)*100:.3f}%), 기여기업 {firms:,}사")
    return merged


def build_b1(save: bool = True) -> pd.DataFrame:
    """step5 를 구 타겟 생성으로 한 번만 갈아끼워 실행한다."""
    spine = config.SPINE_MODE
    input_path = config.panel_path(spine)
    log.info(f"[B1] 원천 로딩: {input_path.name}")
    df = config.read_panel(input_path, dtype={"ETB_DT": str, "BASE_YM": str,
                                              "RECOVER_YM": str})
    for c in ("ETB_DT", "BASE_YM", "RECOVER_YM"):
        if c in df.columns and df[c].dtype != object:
            df[c] = df[c].astype("string").str.replace(r"\.0$", "", regex=True)

    original = step5.generate_12m_target
    step5.generate_12m_target = generate_12m_target_legacy
    try:
        out = step5.finalize(step5.prepare(df), "none")
    finally:
        step5.generate_12m_target = original

    log.info(f"[B1] 최종 shape={out.shape}")
    if save:
        p = config.save_panel(out, OUT_DIR / "nh_panel_prep_B1_rowdup.csv")
        log.info(f"[B1] 저장: {p.name}")
        _verify(p)
    return out


def _verify(path: Path) -> None:
    """OneDrive 동기화 중 쓰기가 깨지지 않았는지 확인한다."""
    if not path.exists() or path.stat().st_size < 1000:
        raise IOError(f"쓰기 이상: {path}")
    import duckdb
    con = duckdb.connect()
    try:
        n = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{path.as_posix()}')").fetchone()[0]
        log.info(f"  검증: 재읽기 OK, {n:,}행, {path.stat().st_size/1e6:.0f}MB")
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════════════
# B4 / B6 — 월 단위 시점 정합 조인
# ══════════════════════════════════════════════════════════════════════
# 두 건은 원인과 교정 방식이 같다.
#   CRIF  CRDBD_OCU_YY 는 YYYYMM(고유 63)인데 step2:679 가 str[:4] 로 자른다
#   AC12  BAS_YM       은 YYYYMM(고유 40)인데 step2:492 가 str[:4] 로 자른다
# 이름의 _YY 때문에 연도로 오인하기 쉬운 컬럼이다. 시점 누수가 데이터의 한계가
# 아니라 가공 과정에서 만들어졌다.
#
# 교정: (V_BZNO, 월) backward as-of. 관측시점 BASE_YM 이전 레코드만 쓴다.
# step1/step2 를 재실행하지 않고 패널의 해당 컬럼만 교체한다. A1/A2 에서 쓴
# 메모리 조인과 같은 경로이며, 변화가 그 컬럼들로 정확히 격리된다.

CARRY_FORWARD_MAX_MONTHS = 12      # as-of 후 이월 상한
CRIF_WINDOW_MONTHS = 12            # "최근 12개월 내 발생"

RAW_AC12 = config.INPUT_DIR / "가상사업자_AC12_외화부채v.txt"
# B4 가 구현만 되고 실행된 적이 없어 이 상수가 빠져 있었다 (2026-09-01 첫 실행에서 발견).
# 발생일자 CRDBD_OCU_YY 는 YYYYMM 6자리라 _ym_int 를 그대로 쓸 수 있다.
# 해제일 MAX(CRDBD_RLS_OCU_DT) / 해제사유 MAX(CRDBD_RLS_RSNC) 는 사용하지 않는다
#   — 부도 대비 평균 +35개월로 100% 사후 정보다.
RAW_CRIF = config.INPUT_DIR / "가상사업자_VH_CRIF_신용불량v.txt"


def _ym_int(s: pd.Series) -> pd.Series:
    """YYYYMM 문자열 -> 월 일련번호. NaN 은 NaN 으로 둔다."""
    t = s.astype("string").str.replace(r"\.0$", "", regex=True).str.strip()
    ok = t.str.fullmatch(r"\d{6}").fillna(False)
    out = pd.Series(np.nan, index=s.index, dtype="float64")
    out[ok] = (t[ok].str[:4].astype(int) * 12 + t[ok].str[4:6].astype(int)).astype(float)
    return out


def _read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="|", dtype=str, skiprows=[1],
                     encoding="utf-8", engine="python")
    return df.loc[:, [c for c in df.columns if not c.startswith("Unnamed")]]


def rebuild_ac12_asof(panel: pd.DataFrame) -> pd.DataFrame:
    """B6 — AC12 를 월 단위 backward as-of 로 다시 붙인다.

    현재 패널의 AC12_* 컬럼(연 단위 조인분)을 덮어쓴다.
    AC12_STALE_MONTHS(정보가 얼마나 오래됐는가)를 파생으로 추가한다 —
    외화부채 정보가 오래된 것 자체가 신호일 수 있다.
    """
    n_before = len(panel)
    raw = _read_raw(RAW_AC12)
    raw["V_BZNO"] = raw["V_BZNO"].astype(str).str.strip()
    raw["_M"] = _ym_int(raw["BAS_YM"])
    raw = raw[raw["_M"].notna()].copy()

    # ★ [2026-09-02] 원천의 **물리 컬럼명**(FC_AM1 / LA_INSP_KRW_AM1 ...)을
    #   step1 과 같은 논리명(US_FC_AM / US_KRW_AM ...)으로 먼저 바꾼다.
    #   이 리네임이 빠져 있었다. 그래서 `AC12_{원천컬럼}` = AC12_FC_AM1 같은
    #   **새 컬럼 10개가 추가되기만** 하고, 패널의 실제 AC12 피처
    #   (AC12_US_FC_AM ... AC12_TOTAL_KRW_AM)는 연 단위 조인분 그대로
    #   남아 있었다. B6/B46 의 AC12 정합화가 사실상 작동하지 않았다.
    #   step31 재판정에서 AC12 10개의 (기업,연도) 내 변동이 여전히 0 인 것으로
    #   드러났다 (2026-09-02).
    #
    #   리네임 맵과 EXT_OTHER 파생은 step1 을 정본으로 임포트한다.
    #   여기에 사본을 두면 두 곳이 갈라진다.
    from eda_pipeline.step1_load import AC12_RENAME
    raw = raw.rename(columns=AC12_RENAME)
    num = [c for c in raw.columns if c not in ("V_BZNO", "BAS_YM", "_M")]
    for c in num:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    # step1._process_ac12 와 같은 규칙: TOTAL 외 결측은 0, 기타통화는 잔차.
    fill = [c for c in num if c != "TOTAL_KRW_AM"]
    raw[fill] = raw[fill].fillna(0)
    krw4 = [c for c in ("US_KRW_AM", "JP_KRW_AM", "CN_KRW_AM", "EU_KRW_AM")
            if c in raw.columns]
    raw["EXT_OTHER_KRW_AM"] = (raw["TOTAL_KRW_AM"].fillna(0)
                               - raw[krw4].sum(axis=1)).clip(lower=0)

    feat = [c for c in raw.columns if c not in ("V_BZNO", "BAS_YM", "_M")]
    ren = {c: f"AC12_{c}" for c in feat}
    raw = raw.rename(columns=ren)
    cols = list(ren.values())
    raw = (raw.sort_values(["V_BZNO", "_M"])
              .drop_duplicates(["V_BZNO", "_M"], keep="last"))

    # 같은 사고를 다시 조용히 넘기지 않는다. 패널에 있는 AC12 금액 컬럼을
    # 하나라도 덮어쓰지 못하면 정합화가 안 된 것이므로 중단한다.
    panel_ac12 = {c for c in panel.columns
                  if c.startswith("AC12_") and c != "AC12_STALE_MONTHS"}
    uncovered = sorted(panel_ac12 - set(cols))
    if uncovered:
        raise ValueError(
            f"AC12 정합화가 패널 컬럼 {len(uncovered)}개를 덮어쓰지 못한다: "
            f"{uncovered}\n"
            f"  원천에서 만든 컬럼: {sorted(cols)}\n"
            f"  step1_load.AC12_RENAME 과 패널 컬럼명이 어긋났다는 뜻이다.")

    left = pd.DataFrame({
        "V_BZNO": panel["V_BZNO"].astype(str).values,
        "_M": _ym_int(panel["BASE_YM"]).values,
        "_row": np.arange(len(panel)),
    }).sort_values("_M", kind="mergesort")
    right = raw[["V_BZNO", "_M"] + cols].sort_values("_M", kind="mergesort")

    merged = pd.merge_asof(left, right, on="_M", by="V_BZNO",
                           direction="backward", allow_exact_matches=True)
    merged = merged.sort_values("_row", kind="mergesort")
    assert len(merged) == n_before, f"AC12 as-of 에서 행수 변동: {n_before} -> {len(merged)}"

    # 이월 상한. 12개월 넘게 묵은 값은 쓰지 않는다.
    # 매칭된 원천 레코드의 월(_SRC)을 따로 받아 BASE_YM 과의 간격을 잰다.
    src_m = pd.merge_asof(left, right[["V_BZNO", "_M"]].assign(_SRC=right["_M"]),
                          on="_M", by="V_BZNO", direction="backward",
                          allow_exact_matches=True).sort_values("_row")["_SRC"].values
    stale = merged["_M"].values - src_m
    too_old = stale > CARRY_FORWARD_MAX_MONTHS

    # ★ 결측 처리는 step5 의 규칙을 그대로 따른다 (유형 1 = 구조적 부재).
    #   step5._split_missing 은 AC12 를 "레코드 없음 = 외화부채 0" 으로 보고
    #   HAS_AC12_YN 플래그를 세운 뒤 fillna(0.0) 한다.
    #   여기서 NaN 으로 두면 B6 의 ΔAUC 가 '시점 교정 효과' 와
    #   '0 -> NaN 의미 변경 효과' 를 섞어 버린다. 재는 것은 시점 하나여야 한다.
    #   "레코드가 없다 / 오래됐다" 는 정보는 HAS_AC12_YN 과
    #   AC12_STALE_MONTHS 가 따로 담는다.
    out = panel.copy()
    for c in cols:
        v = merged[c].values.astype(float)
        v[too_old] = np.nan
        out[c] = np.nan_to_num(v, nan=0.0)
    out["AC12_STALE_MONTHS"] = np.where(too_old, np.nan, stale)
    out["HAS_AC12_YN"] = (~np.isnan(out["AC12_STALE_MONTHS"].values)).astype(int)

    log.info(f"[B6] AC12 월 단위 as-of 재구성 — 행수 {n_before:,} 유지")
    log.info(f"[B6]   덮어쓴 패널 AC12 컬럼 {len(panel_ac12 & set(cols))}개 "
             f"/ 원천 산출 {len(cols)}개")
    log.info(f"[B6]   보유율 {out['HAS_AC12_YN'].mean():.2%} "
             f"(연 단위 조인 시 {panel.get('HAS_AC12_YN', pd.Series([np.nan])).mean():.2%})")
    log.info(f"[B6]   AC12_STALE_MONTHS 중앙값 {np.nanmedian(out['AC12_STALE_MONTHS']):.1f}개월, "
             f"이월 상한 초과로 버린 행 {int(too_old.sum()):,}")

    # 하류 파생 재계산 — (d) 부분오염 해소
    if "JEMU_115000" in out.columns:
        den = out["JEMU_115000"].astype(float).replace(0, np.nan)
        out["exp_fx_dbt"] = (out["AC12_TOTAL_KRW_AM"].astype(float) / den)
        log.info(f"[B6]   exp_fx_dbt 재계산 — 결측률 {out['exp_fx_dbt'].isna().mean():.2%}")
    return out


def rebuild_crif_asof(panel: pd.DataFrame) -> pd.DataFrame:
    """B4 — CRIF 를 '최근 12개월 내 발생' 형태로 시점 정합 재구성한다.

    BASE_YM 이전(같은 달 포함)에 발생한 건만 세므로 미래 정보가 들어가지 않는다.
    """
    n_before = len(panel)
    raw = _read_raw(RAW_CRIF)
    raw["V_BZNO"] = raw["V_BZNO"].astype(str).str.strip()
    raw["_M"] = _ym_int(raw["CRDBD_OCU_YY"])
    raw = raw[raw["_M"].notna()].copy()
    raw["_RSN"] = pd.to_numeric(raw.get("SUM(CRDBD_RSN_AM)"), errors="coerce")
    raw["_OVD"] = pd.to_numeric(raw.get("SUM(CRDBD_OVD_AM)"), errors="coerce")
    raw["_CODE"] = pd.to_numeric(raw.get("CRDBD_RSNC"), errors="coerce")

    key = pd.DataFrame({
        "V_BZNO": panel["V_BZNO"].astype(str).values,
        "_M": _ym_int(panel["BASE_YM"]).values,
        "_row": np.arange(len(panel)),
    })
    # 기업별로 후보 이벤트를 붙인 뒤 창 조건으로 거른다.
    j = key.merge(raw[["V_BZNO", "_M", "_RSN", "_OVD", "_CODE"]]
                  .rename(columns={"_M": "_EV"}), on="V_BZNO", how="left")
    # BASE_YM 이전(같은 달 포함) 발생분 전체 — 여기서 두 창을 나눠 쓴다.
    past = j[j["_EV"] <= j["_M"]]
    # (1) 최근 12개월 창
    win = (past["_EV"] > past["_M"] - CRIF_WINDOW_MONTHS)
    j = past[win]
    agg = (j.groupby("_row")
             .agg(CRIF12_EVENT_CNT=("_EV", "size"),
                  CRIF12_RSN_AM_SUM=("_RSN", "sum"),
                  CRIF12_OVD_AM_SUM=("_OVD", "sum"),
                  CRIF12_WORST_RSNC=("_CODE", "min")))
    # (2) 마지막 발생 시점 — 창을 걸지 않는다.
    #     "최근 12개월에는 없지만 과거에 있었다" 를 12개월 창만으로는 표현할 수 없다.
    #     _EV <= _M 이므로 미래 정보는 들어가지 않는다.
    #
    #     ★ [2026-09-02] 누적 건수 CRIF_CNT_EVER 는 산출하지 않는다 (승인).
    #       CRIF_CNT_12M 과 비영 비율이 동일하고 값이 다른 행이 3개뿐이었다.
    #       같은 정보를 두 컬럼으로 넣으면 중요도만 쪼개지고 해석이 흐려진다.
    #       '과거에 있었다' 는 CRIF_MONTHS_SINCE 가 담는다.
    agg_ever = past.groupby("_row").agg(_LAST_EV=("_EV", "max"))

    out = panel.copy()
    idx = np.arange(len(panel))
    for c, fill in (("CRIF12_EVENT_CNT", 0.0), ("CRIF12_RSN_AM_SUM", 0.0),
                    ("CRIF12_OVD_AM_SUM", 0.0), ("CRIF12_WORST_RSNC", np.nan)):
        v = pd.Series(fill, index=idx, dtype="float64")
        v.loc[agg.index] = agg[c].values
        out[c] = v.values
    # '마지막 발생 이후 경과 개월'
    last_ev = pd.Series(np.nan, index=idx, dtype="float64")
    last_ev.loc[agg_ever.index] = agg_ever["_LAST_EV"].values
    # _M 은 YYYYMM 정수라 단순 뺄셈이 개월 수가 아니다. 연·월로 분해해 센다.
    base_m = key["_M"].values.astype(float)
    months_since = ((base_m // 100 - last_ev // 100) * 12
                    + (base_m % 100 - last_ev % 100))
    # 이력이 없으면 NaN 이다. 0 으로 채우면 '방금 발생' 과 구분되지 않는다.
    out["CRIF_MONTHS_SINCE"] = months_since

    # 지시서 명칭에 맞춘 별칭 — 12개월 창 건수 / 가장 심각한 사유코드
    out["CRIF_CNT_12M"] = out["CRIF12_EVENT_CNT"].values
    out["CRIF_WORST_RSNC"] = out["CRIF12_WORST_RSNC"].values

    assert len(out) == n_before, f"CRIF 재구성에서 행수 변동: {n_before} -> {len(out)}"
    nz = int((out["CRIF12_EVENT_CNT"] > 0).sum())
    n_hist = int(out["CRIF_MONTHS_SINCE"].notna().sum())
    log.info(f"[B4]   발생 이력이 있는(경과월 산출 가능) 행 {n_hist:,} "
             f"({n_hist/len(out):.3%}), CRIF_MONTHS_SINCE 중앙값 "
             f"{np.nanmedian(out['CRIF_MONTHS_SINCE']):.1f}개월")
    log.info(f"[B4] CRIF 최근 {CRIF_WINDOW_MONTHS}개월 재구성 — 행수 {n_before:,} 유지")
    log.info(f"[B4]   발생 이력 있는 행 {nz:,} ({nz/len(out):.3%}) "
             f"(연 단위 조인분은 10,243행이었다)")
    return out


def _load_v2_panel() -> pd.DataFrame:
    """portal_v2 에서 A0 피처 + 재구성에 필요한 컬럼을 읽는다."""
    from eda_pipeline import step30_stage6_ablation as ab
    a0, _, _ = ab.base_feature_pool()
    need = sorted(set(a0) | {"JEMU_115000"})
    return ab.load_base(need)


def build_b4(save: bool = True) -> pd.DataFrame:
    out = rebuild_crif_asof(_load_v2_panel())
    if save:
        _save(out, "nh_panel_B4_crif_asof.csv")
    return out


def build_b6(save: bool = True) -> pd.DataFrame:
    out = rebuild_ac12_asof(_load_v2_panel())
    if save:
        _save(out, "nh_panel_B6_ac12_asof.csv")
    return out


def build_b46(save: bool = True) -> pd.DataFrame:
    out = rebuild_crif_asof(rebuild_ac12_asof(_load_v2_panel()))
    if save:
        _save(out, "nh_panel_B46_asof.csv")
    return out


def _save(df: pd.DataFrame, name: str) -> None:
    p = config.save_panel(df, OUT_DIR / name)
    log.info(f"저장: {p.name}")
    _verify(p)


# ══════════════════════════════════════════════════════════════════════
# B1b — 이벤트 원천만 스파인 내부로
# ══════════════════════════════════════════════════════════════════════
# STAGE 3 이전에는 부도 이벤트를 스파인 안의 IS_BUDO_IN_SPINE_YN 으로만 잡았다.
# 부도가 나면 여신이 정리되어 OBV 레코드가 사라지므로 부도월이 스파인 밖에
# 있는 경우가 오히려 다수다.
#   스파인 내부   658건 / 614사
#   budo_events  1,281건 / 1,192사   <- 현행
# 즉 구 방식은 부도 이벤트 623건, 기업 578사를 통째로 놓쳤다.
# B1b 는 타겟 생성 방식(merge_asof)은 현행 그대로 두고 원천만 바꿔
# "이벤트 누락" 효과 하나만 분리 측정한다.

def build_b1b(save: bool = True) -> pd.DataFrame:
    spine = config.SPINE_MODE
    input_path = config.panel_path(spine)
    log.info(f"[B1b] 원천 로딩: {input_path.name}")
    df = config.read_panel(input_path, dtype={"ETB_DT": str, "BASE_YM": str,
                                              "RECOVER_YM": str})
    for c in ("ETB_DT", "BASE_YM", "RECOVER_YM"):
        if c in df.columns and df[c].dtype != object:
            df[c] = df[c].astype("string").str.replace(r"\.0$", "", regex=True)

    def load_events_from_spine(frame):
        # step5.drop_in_default_periods 가 IS_RECOVERED / RECOVER_YM 을 요구하므로
        # 스파인 행에 들어 있는 값을 그대로 가져온다 (없으면 결측으로 채운다).
        cols = ["V_BZNO", "BASE_YM"] + [c for c in ("IS_RECOVERED", "RECOVER_YM")
                                        if c in frame.columns]
        ev = (frame.loc[frame["IS_BUDO_IN_SPINE_YN"] == 1, cols]
                   .rename(columns={"BASE_YM": "DEFAULT_YM"})
                   .drop_duplicates())
        for c in ("IS_RECOVERED", "RECOVER_YM"):
            if c not in ev.columns:
                ev[c] = np.nan
        ev["V_BZNO"] = ev["V_BZNO"].astype(str)
        log.info(f"[B1b] 스파인 내부 이벤트 {len(ev):,}건 / {ev['V_BZNO'].nunique():,}사 "
                 f"(현행 budo_events.csv 는 1,281건 / 1,192사)")
        return ev

    original = step5.load_budo_events
    step5.load_budo_events = load_events_from_spine
    try:
        out = step5.finalize(step5.prepare(df), "none")
    finally:
        step5.load_budo_events = original

    pos = int(out["IS_BUDO_12M"].sum())
    log.info(f"[B1b] 최종 shape={out.shape}, 양성 {pos:,} "
             f"({pos/len(out)*100:.3f}%), 기여기업 "
             f"{out.loc[out['IS_BUDO_12M']==1,'V_BZNO'].nunique():,}사")
    if save:
        _save(out, "nh_panel_B1b_spine_events.csv")
    return out


def train_variant(panel: pd.DataFrame, tag: str, seeds: list[int] | None = None) -> list[dict]:
    """변종 패널을 A0 피처 구성으로 학습한다.

    피처 목록은 portal_v2 기준 A0 를 그대로 쓰되, 변종 패널에 실재하는 컬럼만
    남긴다. 학습 파라미터와 분할은 step30 과 동일하다 (R2 / Dev early stopping).
    scale_pos_weight 는 run_one 이 이 패널의 실측 비율로 다시 계산한다 —
    B1 은 양성이 크게 늘어나므로 반드시 재계산돼야 한다.
    """
    import json
    from eda_pipeline import step30_stage6_ablation as ab

    a0, _, _ = ab.base_feature_pool()
    feats = [c for c in a0 if c in panel.columns]
    missing = [c for c in a0 if c not in panel.columns]
    log.info(f"[{tag}] A0 피처 {len(a0)}개 중 {len(feats)}개 사용 / 변종에 없는 컬럼 {len(missing)}개")
    if missing:
        log.info(f"[{tag}]   없는 컬럼: {missing[:10]}")

    df = panel.copy()
    df["BASE_YM"] = df["BASE_YM"].astype(str)
    df[ab.TARGET] = df[ab.TARGET].astype("int8")
    for c in feats:
        if not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = df[c].astype("category")

    out = []
    for sd in (seeds or [42]):
        prm = ab.active_params(); prm["random_state"] = sd
        r = ab.run_one(tag, df, feats, save_model=False, params=prm,
                       tag=f"{tag}_seed{sd}")
        r["seed"] = sd
        r["variant"] = tag
        out.append(r)

    fp = ab.OUT_DIR / "ablation_B_results.json"
    prev = []
    if fp.exists():
        try:
            prev = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            prev = []
    keep = [r for r in prev if not (r.get("variant") == tag and r.get("seed") in
                                    {x["seed"] for x in out})]
    fp.write_text(json.dumps(keep + out, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"[{tag}] 결과 저장: {fp.name}")
    return out


BUILDERS = {"B1": build_b1, "B1b": build_b1b, "B4": build_b4,
            "B6": build_b6, "B46": build_b46}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=sorted(BUILDERS))
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--train", action="store_true", help="생성 후 바로 학습")
    ap.add_argument("--seeds", default="42")
    a = ap.parse_args()
    if "OneDrive" in str(_PROJECT_ROOT):
        log.warning("OneDrive 동기화 폴더다. 대용량 쓰기 중 동기화 일시중지를 권고한다.")
    panel = BUILDERS[a.variant](save=not a.no_save)
    if a.train:
        res = train_variant(panel, a.variant, [int(x) for x in a.seeds.split(",")])
        print()
        print(f"{'변종':6s} {'시드':>6s} {'행수':>10s} {'양성':>8s} {'spw':>8s} "
              f"{'best':>6s} {'Train':>7s} {'Dev':>7s} {'Valid':>7s}")
        for r in res:
            print(f"{r['variant']:6s} {r['seed']:6d} {r['n_train']+r['n_dev']+r['n_valid']:10,d} "
                  f"{r['pos_train']+r['pos_dev']+r['pos_valid']:8,d} {r['scale_pos_weight']:8.2f} "
                  f"{r['best_iteration']:6d} {r['train']['auc']:7.4f} {r['dev']['auc']:7.4f} "
                  f"{r['valid']['auc']:7.4f}")


if __name__ == "__main__":
    main()
