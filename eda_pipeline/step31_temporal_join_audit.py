"""
======================================================================
시점 정합성 전수 진단 — 조인 단위 감사
======================================================================
STAGE 6 A9 검증에서 나온 방법을 전 피처로 확대한 것이다.

  원리: (V_BZNO, 연도) 그룹 안에서 값이 한 번도 변하지 않으면
        그 컬럼은 연 단위로 조인됐다는 뜻이다.
        연 단위 조인은 BASE_YM 이후의 정보를 끌어온다 — 시점 누수다.

  실증 근거 (STAGE 6):
    C302_MISSING_YN  월별 변동 21,040건 -> 유효기간 as-of 조인 -> 정합
    CG01_MISSING_YN  월별 변동      0건 -> BASE_YM[:4] 연 단위 -> 누수

  변수명이나 의미가 아니라 **조인 로직**을 봐야 한다는 것이 핵심이다.
  이름이 같은 두 _MISSING_YN 플래그의 판정이 정반대였다.

분류
----
  (a) 연단위정상 : 원천이 연 1회 갱신이고 공시지연을 적용해 붙인 것
  (b) 시점누수   : 관측시점 이후 정보가 들어옴. 조치 필요
  (c) 시불변     : 애초에 시간에 따라 변하지 않음 (업종, 설립일 등)
  (d) 부분오염   : 월별 변동은 있으나 상류 성분 하나가 누수. 자동 판정 불가

★ 이 진단의 한계: 변동 > 0 은 정합의 충분조건이 아니다. (d) 참조.

(b) 로 분류된 것은 **보고만 하고 제거하지 않는다.**

JEMU 변경월 점검
---------------
JEMU 는 as-of 조인이므로 같은 결산이 여러 달 반복되는 것이 정상이다.
다만 PUB_LAG_MONTHS=4 를 적용했으므로 값이 바뀌는 달은 **4월 부근**이어야 한다.
1월에 바뀌면 as-of 가 아니라 역년(calendar year) 경계로 붙은 것이다.

Usage
-----
    python -m eda_pipeline.step31_temporal_join_audit
    python -m eda_pipeline.step31_temporal_join_audit --changemonth
    python -m eda_pipeline.step31_temporal_join_audit --level    # E1-3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd

from eda_pipeline import config
from eda_pipeline.leaky_cols import feature_columns

OUT = config.VALIDATION_DIR / "step31_temporal_join_audit"

# ── 분류 규칙 ────────────────────────────────────────────────────────
# 접두사/이름으로 1차 분류한 뒤, 월별 변동 실측으로 확정한다.
TIME_INVARIANT_PREFIX = ("STD_INDS_",)
TIME_INVARIANT_EXACT = {"is_manufacturing", "exp_fx_industry", "exp_fx_industry_level",
                        "exp_fx_source", "AA17_EXT_PROD_RECORD_YN",
                        # 설립일(ETB_DT) 파생. 기업 단위 상수 — 변하는 기업 0개 (실측).
                        "AGE_MISSING_YN"}

# 연 1회 갱신이 정상인 원천.
# ★ 판정 기준은 "원천이 연 1회인가" 가 아니라 "원천에 월 정보가 있는가" 다.
#   원천에 월이 있는데 연 단위로 조인했다면, 갱신 주기와 무관하게 누수다.
#   JEMU 는 FNA_CLS_YM(월)로 PUB_LAG=4 as-of 조인을 하므로 4월에 값이 바뀐다
#   (실측 97.41%). 따라서 월별 변동이 잡히고 "정합" 으로 분류된다.
ANNUAL_OK_PREFIX: tuple[str, ...] = ()      # 현재 해당 없음
ANNUAL_OK_EXACT: set[str] = set()

# 연 단위 조인이 확인된 누수 (STAGE 6 실증)
KNOWN_LEAK = {
    # 원천 KIS_LS_FNA_MKS_2021~_2025 (연도별 wide, 날짜 없음).
    # step2._join_cg01 이 BASE_YM[:4] 로 merge. 월 단위 재구성 불가.
    "CG01_MISSING_YN", "CG01_KIS_SCORE",
}
# AC12(외화부채): 원천 BAS_YM 이 YYYYMM 인데 step2._join_ac12 가 BAS_YM[:4] 로
# 자른다. 레코드의 96.9% 가 12월 기준이므로 12월 값이 같은 해 1월 행에 붙는다
# — 최대 11개월 선행. CRIF(CRDBD_OCU_YY 절단)와 동일한 구조다.
# 원천에 월이 있으므로 월 단위 조인으로 교정 가능하다.
AC12_YEAR_JOIN_LEAK = {
    "AC12_US_FC_AM", "AC12_US_KRW_AM", "AC12_JP_FC_AM", "AC12_JP_KRW_AM",
    "AC12_CN_FC_AM", "AC12_CN_KRW_AM", "AC12_EU_FC_AM", "AC12_EU_KRW_AM",
    "AC12_TOTAL_KRW_AM", "AC12_EXT_OTHER_KRW_AM", "HAS_AC12_YN",
}
KNOWN_LEAK |= AC12_YEAR_JOIN_LEAK

# ── (d) 부분오염 — 상류 계보 기반 자동 판정 ──────────────────────────
# 이 진단의 한계: "월별 변동 > 0" 은 정합의 **충분조건이 아니다.**
# 정합 성분과 누수 성분을 함께 쓴 파생은 정합 성분 때문에 변동이 생겨
# 정합처럼 보인다. 예: exp_fx_dbt = AC12_TOTAL_KRW_AM / JEMU_115000 은
# 분자가 연 단위인데도 분모(JEMU, 4월 as-of) 때문에 월별 변동이 잡힌다.
#
# 수동 지정은 누락된다. 초판에서 exp_fx / exp_fx_hybrid 를 AC12 파생으로
# 잘못 적었는데, 실제로는 AA17(생산판매) 파생이었다 (step6:179, 341).
# 따라서 파생 변수의 상류를 메타데이터로 명시하고, 상류 중 하나라도
# (b) 시점누수면 자동으로 (d) 로 판정한다.
#
# 출처: step6_macro_integration.py:154-157, 179-190, 341-351
FEATURE_LINEAGE: dict[str, list[str]] = {
    # 노출도 (step6 [5-1])
    "exp_fx":        ["AA17_YTD_XPO", "AA17_YTD_TOT"],
    "exp_fx_dbt":    ["AC12_TOTAL_KRW_AM", "JEMU_115000"],
    "exp_rate":      ["JEMU_118000", "JEMU_115000"],
    "exp_liq":       ["JEMU_116000", "JEMU_118000"],
    "exp_inv":       ["JEMU_191505_val"],
    "exp_fx_hybrid": ["exp_fx", "exp_fx_industry"],
    # 거시 x 기업 상호작용 (step6:341-351)
    "fx_shock_x_export":         ["USD_KRW_log_ret", "exp_fx"],
    "fx_vol_x_fxdebt":           ["USD_KRW_vol_m", "exp_fx_dbt"],
    "eur_shock_x_export":        ["EUR_KRW_log_ret", "exp_fx"],
    "rate_shock_x_leverage":     ["base_rate_diff12", "exp_rate"],
    "credit_spread_x_lev":       ["credit_spread_diff12", "exp_rate"],
    "liq_spread_x_shortdebt":    ["liquidity_spread_diff12", "exp_liq"],
    "oil_shock_x_inv":           ["WTI_crude_oil_log_ret", "exp_inv"],
    "bsi_x_industry":            ["BSI_mfg_biz_yoy", "is_manufacturing"],
    "fx_shock_x_export_hybrid":  ["USD_KRW_log_ret", "exp_fx_hybrid"],
    "eur_shock_x_export_hybrid": ["EUR_KRW_log_ret", "exp_fx_hybrid"],
}


def _leaky_ancestors(col: str, measured: dict[str, int] | None = None,
                     _seen: set[str] | None = None) -> list[str]:
    """상류를 재귀적으로 훑어 **이 패널에서** 누수인 조상을 모두 반환한다.

    ★ [2026-09-02] `measured` 를 받도록 바꿨다.

    KNOWN_LEAK 은 "이 컬럼은 연 단위 조인이다" 라는 **과거 관측의 목록**이다.
    교정된 패널(B4/B6/B46)을 감사할 때 그 목록을 그대로 쓰면, 월 단위 as-of 로
    다시 붙여 (기업,연도) 내 변동이 생긴 컬럼도 계속 누수로 남는다.
    그러면 교정의 효과를 이 진단으로는 볼 수 없다.

    그래서 조상의 누수 여부도 **이 패널에서 실측한 변동 건수**로 판정한다.
      - 조상이 이 패널에 있고 변동 > 0  -> 교정됨. 누수 아님
      - 조상이 이 패널에 있고 변동 == 0 -> 누수 유지
      - 조상이 이 패널에 없다          -> 확인할 수 없으므로 KNOWN_LEAK 을 따른다
    `measured` 를 주지 않으면 종전과 같이 목록만으로 판정한다.
    """
    _seen = _seen or set()
    if col in _seen:
        return []
    _seen.add(col)
    out = []
    for parent in FEATURE_LINEAGE.get(col, []):
        if parent in KNOWN_LEAK:
            if measured is None or measured.get(parent, 0) == 0:
                out.append(parent)
        out.extend(_leaky_ancestors(parent, measured, _seen))
    return sorted(set(out))


def _classify(col: str, n_vary: int, n_distinct: int,
              measured: dict[str, int] | None = None) -> tuple[str, str]:
    if n_distinct <= 1:
        return "무분산", "패널 전체에서 값이 1개뿐"
    bad = _leaky_ancestors(col, measured)
    if bad:
        return "(d) 부분오염", f"상류에 누수 성분: {', '.join(bad)}"
    if n_vary > 0:
        return "정합", f"(기업,연도) 내 월별 변동 {n_vary:,}건"
    # 여기서부터 변동 0건
    if col in KNOWN_LEAK:
        why = ("AC12 연 단위 조인. 원천 BAS_YM 96.9%가 12월 -> 최대 11개월 선행"
               if col in AC12_YEAR_JOIN_LEAK else "연 단위 조인 확정 (STAGE 6 실증)")
        return "(b) 시점누수", why
    if col.startswith(TIME_INVARIANT_PREFIX) or col in TIME_INVARIANT_EXACT:
        return "(c) 시불변", "시간에 따라 변하지 않는 속성"
    if ANNUAL_OK_PREFIX and col.startswith(ANNUAL_OK_PREFIX):
        return "(a) 연단위정상", "연 1회 갱신 원천. 변경월 점검 대상"
    return "(b) 시점누수?", "변동 0건. 조인 단위 확인 필요"


def audit(panel: Path | None = None) -> pd.DataFrame:
    """시점 정합성 감사. `panel` 을 주면 portal_v2 대신 그 parquet 을 본다.

    B4/B6/B46 교정 패널의 (b) 판정이 해소됐는지 보려면 같은 진단을 그 패널에
    돌려야 한다. portal_v2 는 교정 전 패널이므로 비교 대상이 못 된다.
    """
    if panel is not None:
        if not panel.exists():
            raise FileNotFoundError(panel)
        import duckdb
        con = duckdb.connect()
        src = f"read_parquet('{panel.as_posix()}')"
        label = panel.name
    else:
        con = config.connect_db("v2")
        src = config.PANEL_TABLE
        label = f"portal_v2.{config.PANEL_TABLE}"
    try:
        cols = con.execute(f"SELECT * FROM {src} LIMIT 0").df().columns.tolist()
        meta = json.loads(
            (config.OUTPUT_DIR / "macro_columns_v2.json").read_text(encoding="utf-8"))
        # 상호작용항은 거시 제외분이지만 (d) 판정 대상이므로 진단에는 포함한다.
        drop = set(meta["pure_macro"])
        feats = [c for c in feature_columns(pd.DataFrame(columns=cols),
                                            extra_exclude=["V_BRANCH_CODE"])
                 if c not in drop]
        print(f"패널 {label}")
        print(f"진단 대상 피처 {len(feats)}개 (거시 {len(drop)}개 제외)")
        print()

        # ── 1차: 전 피처 실측 ────────────────────────────────────
        # 분류를 나중에 하는 이유는 (d) 부분오염 판정이 **조상의 실측값**을
        # 필요로 하기 때문이다. 한 번에 분류하면 조상을 아직 재지 않았다.
        stat = {}
        for i, c in enumerate(feats, 1):
            n_distinct = con.execute(
                f'SELECT COUNT(DISTINCT "{c}") FROM {src}').fetchone()[0]
            n_vary = con.execute(f'''
                SELECT COUNT(*) FROM (
                  SELECT V_BZNO FROM {src}
                  GROUP BY V_BZNO, SUBSTR(BASE_YM, 1, 4)
                  HAVING COUNT(DISTINCT "{c}") > 1)''').fetchone()[0]
            stat[c] = (int(n_vary), int(n_distinct))
            if i % 25 == 0:
                print(f"  ... {i}/{len(feats)}")
    finally:
        con.close()

    # ── 2차: 실측을 근거로 분류 ──────────────────────────────────
    measured = {c: v[0] for c, v in stat.items()}
    rows = []
    for c in feats:
        n_vary, n_distinct = stat[c]
        cls, note = _classify(c, n_vary, n_distinct, measured)
        rows.append(dict(feature=c, n_vary=n_vary, n_distinct=n_distinct,
                         classification=cls, note=note))
    return pd.DataFrame(rows)


def change_month() -> pd.DataFrame:
    """JEMU 값이 바뀌는 달의 분포. PUB_LAG_MONTHS=4 면 4월 부근이어야 한다."""
    con = config.connect_db("v2")
    try:
        # 대표 컬럼 하나로 본다 (자산총계). 같은 as-of 조인을 타므로 전 JEMU 가 동일하다.
        df = con.execute(f'''
            WITH t AS (
              SELECT V_BZNO, BASE_YM, JEMU_115000,
                     LAG(JEMU_115000) OVER (PARTITION BY V_BZNO ORDER BY BASE_YM) prev
              FROM {config.PANEL_TABLE})
            SELECT SUBSTR(BASE_YM, 5, 2) AS mm, COUNT(*) AS n_change
            FROM t
            WHERE prev IS NOT NULL AND JEMU_115000 IS NOT NULL
              AND JEMU_115000 <> prev
            GROUP BY 1 ORDER BY 1''').df()
    finally:
        con.close()
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changemonth", action="store_true")
    ap.add_argument("--level", action="store_true",
                    help="E1-3: Phase 6 수준·누적 계열 12개 감사")
    ap.add_argument("--panel", default=None,
                    help="감사 대상 parquet 경로. 기본은 portal_v2 패널 테이블. "
                         "B46 교정 패널 재판정에 쓴다")
    ap.add_argument("--out-suffix", default="",
                    help="산출 CSV 파일명 접미사 (덮어쓰기 방지)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if a.level:
        main_level()
        return

    if a.changemonth:
        df = change_month()
        tot = df["n_change"].sum()
        print(f"JEMU_115000(자산총계) 값이 바뀐 (기업,월) 건수 = {tot:,}")
        print(f"공시지연 설정 PUB_LAG_MONTHS = {config.PUB_LAG_MONTHS}\n")
        print(f"  {'월':4s} {'변경건수':>10s} {'비중':>8s}")
        for _, r in df.iterrows():
            print(f"  {r['mm']:>4s} {int(r['n_change']):10,d} "
                  f"{r['n_change']/tot:8.2%}")
        top = df.loc[df["n_change"].idxmax(), "mm"]
        print(f"\n  최다 변경월 = {top}월")
        expect = f"{config.PUB_LAG_MONTHS:02d}"
        print(f"  기대 = {expect}월 (PUB_LAG_MONTHS={config.PUB_LAG_MONTHS})")
        print(f"  판정: {'as-of 정상' if top == expect else '★ 확인 필요 — 역년 경계 조인 의심'}")
        df.to_csv(OUT / "jemu_change_month.csv", index=False, encoding="utf-8-sig")
        return

    df = audit(Path(a.panel) if a.panel else None)
    out_csv = OUT / f"temporal_join_audit{a.out_suffix}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 74)
    print("분류 집계")
    print("=" * 74)
    for k, v in df["classification"].value_counts().items():
        print(f"  {k:16s} {v:4d}개")

    zero = df[df["n_vary"] == 0].sort_values(["classification", "feature"])
    print("\n" + "=" * 74)
    print(f"월별 변동 0건인 피처 — 전체 {len(zero)}개")
    print("=" * 74)
    print(f"  {'피처':34s} {'고유값':>7s}  {'분류':14s} 비고")
    for _, r in zero.iterrows():
        print(f"  {r['feature']:34s} {r['n_distinct']:7d}  "
              f"{r['classification']:14s} {r['note']}")

    partial = df[df["classification"].str.startswith("(d)")]
    if len(partial):
        print()
        print("=" * 74)
        print(f"(d) 부분오염 — {len(partial)}개. 월별 변동이 있으나 상류에 누수 성분이 있다.")
        print("=" * 74)
        for _, r in partial.iterrows():
            print(f"  {r['feature']:24s} 변동 {int(r['n_vary']):>7,}건  {r['note']}")

    leak = df[df["classification"].str.startswith("(b)")]
    print("\n" + "=" * 74)
    print(f"★ (b) 시점누수 후보 — {len(leak)}개. 보고만 하고 제거하지 않는다.")
    print("=" * 74)
    for _, r in leak.iterrows():
        print(f"  {r['feature']:34s} {r['note']}")
    print()
    print(f"저장: {out_csv}")



# ======================================================================
# E1-3 — Phase 6 수준·누적 계열 12개 시점 정합성 감사
# ======================================================================
# 기존 감사는 (V_BZNO, 연도) 단위로 봤다. Phase 6 산출물은 거시라 BASE_YM 하나당
# 값이 하나뿐이므로 기업 축이 의미가 없다. 같은 원리를 **(연도) 단위**로 적용한다.
#
#   원리: (연도) 안에서 값이 한 번도 변하지 않으면 연 단위 정보라는 뜻이다.
#   단, DUR_ 계열은 상태 지속 개월 수라 느리게 변하는 것이 정상이다.
#   따라서 "몇 개월마다 바뀌는가" 를 함께 재서 판정한다.

LEVEL_OUT = OUT / "phase6_level_audit.csv"
PERTURB_ROWS = (30, 45, 60)      # 섭동을 넣을 행 위치 (원천 프레임 기준)
PERTURB_DELTA = 5.0              # 눈에 띄게 큰 값


def _phase6_frame():
    """impute_data 의 Phase 0→1 을 그대로 태워 Phase 6 입력/출력을 만든다."""
    sys.path.insert(0, str(_PROJECT_ROOT / "api_data_processing"))
    import importlib
    imp = importlib.import_module("impute_data")
    raw = pd.read_csv(imp.INPUT_FILE)
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.sort_values("date").reset_index(drop=True)
    df, _ga, gb, gc = imp.phase0(raw)
    snap = imp.phase1(df, gb, gc)
    return imp, snap


def audit_level() -> pd.DataFrame:
    imp, snap = _phase6_frame()
    lv = imp.phase6(snap)
    lv = lv.iloc[imp.TRUNCATION_MONTHS:].reset_index(drop=True)
    lv["BASE_YM"] = pd.to_datetime(lv["date"]).dt.strftime("%Y%m")
    lv["_Y"] = lv["BASE_YM"].str[:4]

    rows = []
    for c in imp.PHASE6_COLS:
        s = pd.to_numeric(lv[c], errors="coerce")
        g = lv.assign(_v=s).groupby("_Y")["_v"]
        nun_y = g.nunique(dropna=True)
        cnt_y = g.count()
        # 그 해가 통째로 결측인 것과 값이 평평한 것은 다른 사건이다.
        years_nan = [y for y, n in cnt_y.items() if n == 0]
        years_flat = [y for y, v in nun_y.items() if v <= 1 and cnt_y[y] > 0]
        # 값이 바뀐 달 / 바뀌는 간격
        chg = s.ne(s.shift(1)) & s.notna() & s.shift(1).notna()
        n_chg = int(chg.sum())
        idx = list(np.flatnonzero(chg.to_numpy()))
        gaps = [b - a for a, b in zip(idx, idx[1:])] if len(idx) > 1 else []
        # 같은 값이 이어진 가장 긴 구간. 변경 사이 간격만 보면 계열 앞뒤의
        # 긴 상수 구간(예: DUR_ 이 0 으로 머무는 구간)을 통째로 놓친다.
        obs = s.dropna()
        run = obs.ne(obs.shift(1)).cumsum()
        longest_run = int(obs.groupby(run).size().max()) if len(obs) else 0
        rows.append(dict(
            feature=c,
            n_months=int(s.notna().sum()),
            n_missing=int(s.isna().sum()),
            n_distinct=int(s.nunique(dropna=True)),
            n_change=n_chg,
            change_every_months=(round(float(np.mean(gaps)), 2) if gaps else None),
            max_flat_run=longest_run,
            n_years_flat=len(years_flat),
            years_flat=";".join(years_flat),
            n_years_all_nan=len(years_nan),
            years_all_nan=";".join(years_nan),
        ))
    return pd.DataFrame(rows), imp, snap


def perturb_test(imp, snap) -> list[dict]:
    """미래 섭동 검사 — 롤링이 미래를 참조하지 않는다는 코드 수준 증거.

    원천 계열의 t >= T 구간을 크게 흔든 뒤 Phase 6 을 다시 돌린다.
    t < T 의 산출값이 **비트 단위로 동일**하면 그 산출은 미래를 보지 않는다.
    (반대로 한 칸이라도 미래를 참조하면 T 직전 값이 바뀐다.)
    """
    base = imp.phase6(snap)
    src = ["base_rate", "credit_spread", "BSI_mfg_biz",
           "treasury_bond_3y", "liquidity_spread"]
    out = []
    for T in PERTURB_ROWS:
        if T >= len(snap):
            continue
        pert = snap.copy()
        for c in src:
            if c in pert.columns:
                pert.loc[pert.index[T:], c] = \
                    pd.to_numeric(pert[c], errors="coerce").iloc[T:] + PERTURB_DELTA
        got = imp.phase6(pert)
        for c in imp.PHASE6_COLS:
            a = pd.to_numeric(base[c], errors="coerce").iloc[:T].to_numpy(float)
            b = pd.to_numeric(got[c], errors="coerce").iloc[:T].to_numpy(float)
            same = bool(np.array_equal(a, b, equal_nan=True))
            n_after = int((~np.isclose(
                pd.to_numeric(base[c], errors="coerce").iloc[T:].to_numpy(float),
                pd.to_numeric(got[c], errors="coerce").iloc[T:].to_numpy(float),
                equal_nan=True)).sum())
            out.append({"perturb_row": T, "perturb_ym": str(snap['date'].iloc[T])[:7],
                        "feature": c, "past_unchanged": same,
                        "n_changed_after_T": n_after})
    return out


def main_level() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df, imp, snap = audit_level()
    df.to_csv(LEVEL_OUT, index=False, encoding="utf-8-sig")

    print("=" * 96)
    print("E1-3  Phase 6 수준·누적 계열 12개 — 시점 정합성 감사")
    print("=" * 96)
    print(f"{'변수':24s} {'개월':>5s} {'결측':>5s} {'고유':>5s} {'변경':>5s} "
          f"{'평균간격':>8s} {'최장동일값':>10s} {'연내무변동':>10s}")
    print("-" * 96)
    for _, r in df.iterrows():
        ce = "—" if r["change_every_months"] is None else f"{r['change_every_months']:.2f}"
        mf = f"{int(r['max_flat_run'])}"
        print(f"{r['feature']:24s} {r['n_months']:5d} {r['n_missing']:5d} "
              f"{r['n_distinct']:5d} {r['n_change']:5d} {ce:>8s} {mf:>10s} "
              f"{r['n_years_flat']:10d}")

    print()
    print("=" * 96)
    print("(연도) 내 월별 변동이 0 인 변수")
    print("=" * 96)
    nanrows = df[df["n_years_all_nan"] > 0]
    if len(nanrows):
        print("  [참고] 아래는 그 해가 통째로 결측이라 변동을 잴 수 없는 것이다.")
        print("         무변동이 아니라 min_periods=24 warm-up 구간이다.")
        for _, r in nanrows.iterrows():
            print(f"    {r['feature']:24s} 전결측 연도 {r['years_all_nan']} "
                  f"(총 결측 {r['n_missing']}개월)")
        print()
    flat = df[df["n_years_flat"] > 0]
    if flat.empty:
        print("  실제 무변동: 없음 — 12개 전부 관측 구간에서는 월별로 변한다.")
    else:
        for _, r in flat.iterrows():
            f = r["feature"]
            if f.startswith(("DUR_", "CUM_")):
                kind = ("상태 지속·누적 지표다. 임계 미달 구간에서 0 이 이어지는 것이 "
                        "정의대로의 동작이다.")
            elif f == "LV_base_rate":
                kind = ("정책금리는 금통위 결정 시에만 바뀌는 계단 함수다. "
                        "동결 구간의 정체는 정상이다 (D축 G1-5b 와 같은 사유).")
            elif f.startswith("PCT_"):
                kind = ("분위 지표는 상단/하단에 붙으면 포화된다. 최장 정체가 길면 "
                        "그 구간에서 변별력이 없다는 뜻이다 — 누수가 아니라 유용성 문제다.")
            else:
                kind = "★ 확인 필요"
            print(f"  {f:24s} 무변동 연도 {r['n_years_flat']}개 "
                  f"({r['years_flat']})  최장 동일값 {int(r['max_flat_run'])}개월")
            print(f"  {'':24s} -> {kind}")

    print()
    print("=" * 96)
    print("미래 참조 섭동 검사 — 원천 t >= T 를 +%.1f 흔들고 t < T 산출을 비교"
          % PERTURB_DELTA)
    print("=" * 96)
    pt = perturb_test(imp, snap)
    bad = [p for p in pt if not p["past_unchanged"]]
    for T in sorted({p["perturb_row"] for p in pt}):
        sub = [p for p in pt if p["perturb_row"] == T]
        ok = sum(p["past_unchanged"] for p in sub)
        eff = sum(1 for p in sub if p["n_changed_after_T"] > 0)
        print(f"  T={T:3d} ({sub[0]['perturb_ym']})  과거 불변 {ok}/{len(sub)}개  "
              f"| T 이후가 실제로 바뀐 변수 {eff}/{len(sub)}개 (섭동이 먹혔다는 증거)")
    if bad:
        print()
        print("  ★ 과거 값이 바뀐 변수 — 미래 참조 의심")
        for p in bad:
            print(f"    T={p['perturb_row']} {p['feature']}")
    else:
        print()
        print("  판정: 12개 전부 T 이전 산출이 비트 단위로 동일하다.")
        print("        원천의 미래 구간을 아무리 흔들어도 과거 산출이 바뀌지 않는다")
        print("        = 롤링이 미래를 참조하지 않는다.")

    (OUT / "phase6_perturb_test.csv").write_text(
        pd.DataFrame(pt).to_csv(index=False), encoding="utf-8-sig")
    print(f"\n저장: {LEVEL_OUT}")
    print(f"저장: {OUT / 'phase6_perturb_test.csv'}")

if __name__ == "__main__":
    main()
