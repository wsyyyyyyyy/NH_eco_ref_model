"""
======================================================================
STAGE 6 D축 — 게이트 1 (데이터 무결성) 검증
======================================================================
기준서: eda_pipeline/output/validation/D_AXIS_SUCCESS_CRITERIA.md (개정 R1 반영)

  G1-1  model_input_monthly_cleaned.csv 첫 행 <= 2021-01-31
  G1-2  NaN 0개 (impute_data assert)
  G1-3  거시 조인 후 패널 행수 == 조인 전
  G1-4  2021년 행의 거시 값 != 2022-01 값        (bfill 누수 검증)
  G1-5  [개정 R1] 거시 충격 항이 0 이 아닌 달에 한해, 상호작용항의 기업 간 분산 > 0
        (충격 항 == 0 인 달은 판정 대상에서 제외하고 건수만 기록)
  G1-5b [개정 R1 신설] 각 상호작용항의 "충격 0 인 달" 개수와 행 비율 기록
  G1-6  거시 변수 중 (연도) 내 월별 변동 0 인 것 없음
  G1-7  step6 shift 중복 제거 후 각 Group 의 실제 총 시차 확인
        (기대 시차는 impute_data 의 GROUP_*_COLS 에서 파생한다 — 하드코딩 금지)

  + [확인] 금리 경로 커버리지 — 정책금리/신용스프레드/유동성스프레드 월별 충격값

하나라도 실패하면 D축을 실행하지 않는다.

Usage
-----
    python -m eda_pipeline.step33_macro_gate1
    python -m eda_pipeline.step33_macro_gate1 --panel-tag real
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb
import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec
from eda_pipeline.step6_macro_integration import INTERACTIONS, MACRO_LAG_MONTHS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("gate1")

MACRO_CLEANED = config.macro_input_path()
MACRO_RAW_MONTHLY = (_PROJECT_ROOT / "api_data_processing" / "output"
                     / "model_input" / "model_input_monthly.csv")

# 8종 = INTERACTIONS 에서 _hybrid 변형 2개를 뺀 것.
# 하이브리드는 같은 거시 충격에 다른 노출도를 쓴 대체 정의이므로 별도 세지 않는다.
INTERACTION_8 = [n for n, _, _ in INTERACTIONS if not n.endswith("_hybrid")]
INTERACTION_HYBRID = [n for n, _, _ in INTERACTIONS if n.endswith("_hybrid")]

# 분기 공표 지표. 월 단위로는 같은 값이 3개월 반복되는 것이 정상이므로
# G1-6 의 예외로 둔다. 연 단위로 변동이 0 이면 예외가 아니다.
QUARTERLY_HINTS = ("current_account_quarterly",)

# 금리 경로 확인 대상 충격 항
RATE_CHANNEL_COLS = ["base_rate_diff12", "credit_spread_diff12", "liquidity_spread_diff12"]


def _fail(results: list, gid: str, name: str, ok: bool, detail: str) -> bool:
    results.append({"id": gid, "name": name, "pass": bool(ok), "detail": detail})
    log.info("  %-6s %-46s %s", gid, name, "PASS" if ok else "*** FAIL ***")
    for line in detail.splitlines():
        log.info("         %s", line)
    return ok


# ══════════════════════════════════════════════════════════════════════
# G1-1 / G1-2 — 거시 원천
# ══════════════════════════════════════════════════════════════════════

def gate_1_2(res: list) -> pd.DataFrame:
    macro = pd.read_csv(MACRO_CLEANED, dtype={"BASE_YM": str})
    macro["BASE_YM"] = macro["BASE_YM"].astype(str).str.strip()
    first = macro["BASE_YM"].min()
    last = macro["BASE_YM"].max()
    _fail(res, "G1-1", "거시 원천 첫 행 <= 2021-01", first <= "202101",
          f"첫 행 {first} / 마지막 {last} / {len(macro)}개월 x {macro.shape[1] - 1}컬럼")

    vcols = [c for c in macro.columns if c != "BASE_YM"]
    n_nan = int(macro[vcols].isna().sum().sum())
    _fail(res, "G1-2", "거시 원천 NaN 0개", n_nan == 0,
          f"NaN {n_nan}개 (impute_data Phase5 assert 와 동일 기준)")
    return macro


# ══════════════════════════════════════════════════════════════════════
# G1-3 — 조인 전후 행수
# ══════════════════════════════════════════════════════════════════════

def gate_3(res: list, panel: pd.DataFrame) -> None:
    pre = config.OUTPUT_DIR / "nh_panel_prep_obv_none.parquet"
    con = duckdb.connect()
    try:
        n_before = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{pre.as_posix()}')").fetchone()[0]
    finally:
        con.close()
    n_after = len(panel)
    dup = int(panel.duplicated(["V_BZNO", "BASE_YM"]).sum())
    _fail(res, "G1-3", "거시 조인 후 행수 == 조인 전",
          n_before == n_after and dup == 0,
          f"조인 전 {n_before:,} -> 조인 후 {n_after:,} / "
          f"(V_BZNO, BASE_YM) 중복 {dup}건")


# ══════════════════════════════════════════════════════════════════════
# G1-4 — bfill 누수
# ══════════════════════════════════════════════════════════════════════

def gate_4(res: list, panel: pd.DataFrame, macro: pd.DataFrame,
           macro_cols: list) -> None:
    """2021년 각 월의 거시 값이 2022-01 값과 같아지지 않았는지 본다.

    거시 원천이 패널 기간을 못 덮으면 옛 step6 은 bfill 로 뒤쪽 값을 앞으로
    끌어왔다. 그러면 2021년 전 구간이 미래 값으로 채워진다.
    """
    pm = (panel[["BASE_YM"] + macro_cols]
          .drop_duplicates("BASE_YM").set_index("BASE_YM").sort_index())
    ref = pm.loc["202201"]

    rows = []
    for ym in [y for y in pm.index if y.startswith("2021")]:
        same = int((pm.loc[ym].astype(float).values
                    == ref.astype(float).values).sum())
        rows.append((ym, same))
    worst = max(r[1] for r in rows)
    n = len(macro_cols)
    # 정상적으로도 우연히 같은 값이 나올 수 있으므로 "전 컬럼 동일" 을 실패로 본다.
    detail = (f"거시 {n}개 중 2022-01 과 값이 같은 개수 (2021년 각 월)\n"
              + "  " + "  ".join(f"{ym}:{c}" for ym, c in rows))
    ok = worst < n

    # 패널의 거시 값이 원천 CSV 와 행 단위로 정확히 일치하는지도 본다.
    src = macro.set_index("BASE_YM").sort_index()
    common = [c for c in macro_cols if c in src.columns]
    aligned = src.loc[pm.index, common].astype(float)
    diff = np.abs(pm[common].astype(float).values - aligned.values)
    max_diff = float(np.nanmax(diff)) if diff.size else 0.0
    ok = ok and max_diff < 1e-9
    detail += (f"\n원천 CSV 대비 최대 절대차 {max_diff:.3e} "
               f"(0 이면 조인 후 어떤 채움도 일어나지 않았다는 뜻)")
    _fail(res, "G1-4", "2021년 거시 값 != 2022-01 값 (bfill 누수)", ok, detail)


# ══════════════════════════════════════════════════════════════════════
# G1-5 / G1-5b — 상호작용항 [개정 R1]
# ══════════════════════════════════════════════════════════════════════

def gate_5(res: list, panel: pd.DataFrame) -> dict:
    """G1-5 [개정 R1] + G1-5b.

    판정 대상은 "거시 충격 항이 0 이 아닌 달" 로 한정한다.
    충격이 0 인 달에 곱셈 결과가 전 기업 0 이 되는 것은 시점 더미로의 퇴화가
    아니라 설계대로의 정상 동작이다 (개정 사유는 기준서 §개정 이력 R1).

    노출도가 원천 공표 시차 warm-up 으로 그 달 전 행 결측인 경우도 같은 이유로
    판정에서 뺀다. 두 경우 모두 개수와 행 비율을 반드시 남긴다 (G1-5b).
    """
    n_all = len(panel)
    months = sorted(panel["BASE_YM"].unique())
    n_months = len(months)
    rows_by_ym = panel.groupby("BASE_YM").size()
    is_valid = panel["BASE_YM"] >= split_spec.VALID_START
    n_valid = int(is_valid.sum())
    rows_by_ym_valid = panel[is_valid].groupby("BASE_YM").size()

    lines, table, all_ok = [], [], True
    for name, mac, exp in INTERACTIONS:
        core = not name.endswith("_hybrid")
        if name not in panel.columns:
            lines.append(f"{name:28s} 컬럼 없음 — 판정 불가")
            if core:
                all_ok = False
            continue

        shock = (panel.groupby("BASE_YM", observed=True)[mac].first()
                 if mac in panel.columns else None)
        zero_ym = ([] if shock is None else
                   [ym for ym, v in shock.items() if pd.notna(v) and float(v) == 0.0])
        nn = panel.groupby("BASE_YM", observed=True)[name].count()
        empty_ym = [ym for ym, c in nn.items() if c == 0 and ym not in zero_ym]

        judged = [ym for ym in months if ym not in zero_ym and ym not in empty_ym]
        g = panel.groupby("BASE_YM", observed=True)[name].std()
        bad = [ym for ym in judged if not (pd.notna(g.get(ym)) and g[ym] > 0)]
        ok = not bad
        if core and not ok:
            all_ok = False

        z_rows = int(rows_by_ym.reindex(zero_ym).sum() or 0)
        e_rows = int(rows_by_ym.reindex(empty_ym).sum() or 0)
        z_rows_v = int(rows_by_ym_valid.reindex(zero_ym).sum() or 0)
        table.append({
            "interaction": name, "macro": mac, "exposure": exp, "core8": core,
            "n_months": n_months, "n_judged": len(judged),
            "n_var_pos": len(judged) - len(bad), "failed_months": bad,
            "zero_shock_months": zero_ym, "n_zero_shock": len(zero_ym),
            "zero_shock_rows": z_rows,
            "zero_shock_row_pct": round(100 * z_rows / n_all, 2),
            "zero_shock_rows_valid": z_rows_v,
            "zero_shock_row_pct_valid": round(100 * z_rows_v / max(n_valid, 1), 2),
            "exposure_empty_months": empty_ym, "n_exposure_empty": len(empty_ym),
            "exposure_empty_rows": e_rows,
            "exposure_empty_row_pct": round(100 * e_rows / n_all, 2),
            "std_median": float(g.median()),
            "missing_pct": float(panel[name].isna().mean() * 100),
            "pass": bool(ok),
        })
        tag = "" if core else "  (하이브리드, 8종 외)"
        mark = "OK" if ok else ("*** 미달 " + str(bad) + " ***")
        lines.append(
            f"{name:28s} 판정 {len(judged) - len(bad):2d}/{len(judged):2d}  "
            f"충격0 {len(zero_ym):2d}개월({100 * z_rows / n_all:5.2f}%/V{100 * z_rows_v / max(n_valid, 1):5.2f}%)  "
            f"노출도공백 {len(empty_ym):2d}개월({100 * e_rows / n_all:4.2f}%)  "
            f"std중앙 {g.median():.6g}  {mark}{tag}")

    _fail(res, "G1-5", "충격!=0 인 달에서 상호작용 8종 분산 > 0 [개정 R1]",
          all_ok, "\n".join(lines))

    b = [f"{'상호작용':28s} {'충격0월':>7s} {'행%':>7s} {'Valid행%':>9s} "
         f"{'노출공백월':>10s} {'행%':>7s}"]
    for t in table:
        b.append(f"{t['interaction']:28s} {t['n_zero_shock']:7d} "
                 f"{t['zero_shock_row_pct']:6.2f}% {t['zero_shock_row_pct_valid']:8.2f}% "
                 f"{t['n_exposure_empty']:10d} {t['exposure_empty_row_pct']:6.2f}%")
    for t in table:
        if t["n_zero_shock"]:
            b.append(f"  {t['interaction']} 충격0 월: {t['zero_shock_months']}")
        if t["n_exposure_empty"]:
            b.append(f"  {t['interaction']} 노출도공백 월: {t['exposure_empty_months']}")
    _fail(res, "G1-5b", "충격 0 인 달 개수/행비율 기록 [개정 R1 신설]", True, "\n".join(b))
    return {"per_interaction": table}


# ══════════════════════════════════════════════════════════════════════
# G1-6 — 연도 내 월별 변동
# ══════════════════════════════════════════════════════════════════════

def gate_6(res: list, macro: pd.DataFrame, macro_cols: list) -> None:
    m = macro.copy()
    m["_Y"] = m["BASE_YM"].str[:4]
    flat_all, flat_some = [], []
    for c in macro_cols:
        if c not in m.columns:
            continue
        nun = m.groupby("_Y")[c].nunique()
        if (nun <= 1).all():
            flat_all.append(c)
        elif (nun <= 1).any():
            flat_some.append((c, [y for y, v in nun.items() if v <= 1]))

    exempt = [c for c in flat_all if any(h in c for h in QUARTERLY_HINTS)]
    hard = [c for c in flat_all if c not in exempt]
    lines = [f"거시 {len(macro_cols)}개 중 모든 연도에서 월별 변동 0 인 컬럼: "
             f"{len(flat_all)}개"]
    if exempt:
        lines.append(f"  분기 지표 예외 {len(exempt)}개: {exempt}")
    if hard:
        lines.append(f"  ★ 예외 아님 {len(hard)}개: {hard}")
    if flat_some:
        lines.append(f"  일부 연도만 변동 0: {len(flat_some)}개 "
                     f"(정상 범위 — 예: {flat_some[:3]})")
    _fail(res, "G1-6", "연도 내 월별 변동 0 인 거시 변수 없음", not hard,
          "\n".join(lines))


# ══════════════════════════════════════════════════════════════════════
# G1-7 — Group A 실제 총 시차
# ══════════════════════════════════════════════════════════════════════

def _best_lag(target: pd.Series, candidate: pd.Series, max_lag: int = 4):
    """candidate 를 k개월 shift 했을 때 target 과 가장 잘 맞는 k 를 찾는다."""
    best = (None, np.inf)
    for k in range(0, max_lag + 1):
        c = candidate.shift(k)
        j = target.index.intersection(c.dropna().index)
        if len(j) < 12:
            continue
        err = float(np.nanmean(np.abs(target.loc[j].values - c.loc[j].values)))
        if err < best[1]:
            best = (k, err)
    return best


def gate_7(res: list, macro: pd.DataFrame) -> None:
    """공표 시차를 되짚어 각 Group 의 실제 총 시차를 실측한다.

    원천 레벨(model_input_monthly.csv)에서 변환식을 그대로 재현한 뒤,
    정제본의 같은 컬럼과 몇 개월 어긋나 있는지를 잰다.
    """
    if not MACRO_RAW_MONTHLY.exists():
        _fail(res, "G1-7", "Group A 총 시차", False,
              f"{MACRO_RAW_MONTHLY} 없음 — 시차를 실측할 수 없다")
        return

    raw = pd.read_csv(MACRO_RAW_MONTHLY)
    raw["BASE_YM"] = pd.to_datetime(raw["date"]).dt.strftime("%Y%m")
    raw = raw.sort_values("BASE_YM").set_index("BASE_YM")
    cl = macro.set_index("BASE_YM").sort_index()

    # ★ [2026-09-02] 기대 시차를 하드코딩하지 않는다. `impute_data` 의 그룹 배정에서
    #   파생한다. 초판은 `M2_broad_money` 를 Group B(+1) 로 박아 두었는데 2026-09-01 에
    #   Group C(+2) 로 옮겨졌고, 그래서 데이터가 옳은데도 G1-7 이 실패했다.
    #   시차 배정의 정본은 `impute_data` 하나여야 한다.
    def _expect_lag(level_col: str | None) -> tuple[int, str]:
        from api_data_processing import impute_data as _imp
        table = (("A", _imp.GROUP_A_COLS, 0),
                 ("B", _imp.GROUP_B_COLS, _imp.LAG_MONTHS_B),
                 ("C", _imp.GROUP_C_COLS, _imp.LAG_MONTHS_C),
                 ("D", _imp.GROUP_D_COLS, _imp.LAG_MONTHS_D))
        for g, cols, lag in table:
            if level_col in cols:
                return lag, g
        return 0, "미배정"

    # (정제본 컬럼, 원천 레벨, 변환) — 기대 시차·그룹은 impute_data 에서 읽는다
    probe_spec = [
        ("KOSPI_log_ret",                  "KOSPI",                     "log_ret"),
        ("USD_KRW_log_ret",                "USD_KRW",                   "log_ret"),
        ("credit_spread_diff12",           None,                        "spread"),
        ("CPI_core_yoy",                   "CPI_core",                  "yoy"),
        ("M2_broad_money_yoy",             "M2_broad_money",            "yoy"),
        ("base_rate_diff12",               "base_rate",                 "diff12"),
        ("BSI_mfg_biz_yoy",                "BSI_mfg_biz",               "yoy"),
        # Group D(+3) 대표. 2026-09-02 신설분이 실제로 3개월 밀렸는지 확인한다.
        ("household_credit_yoy",           "household_credit",          "yoy"),
        ("current_account_quarterly_yoy",  "current_account_quarterly", "yoy"),
    ]
    probes = []
    for _col, _lvl, _kind in probe_spec:
        if _kind == "spread":
            # 파생 스프레드는 Group A 금리 두 개의 차이라 시차 0 이 정의상 기대값이다.
            probes.append((_col, _lvl, _kind, 0, "A(파생)"))
            continue
        _lag, _g = _expect_lag(_lvl)
        probes.append((_col, _lvl, _kind, _lag, _g))
    # _best_lag 의 탐색 상한이 기대 시차보다 작으면 판정 자체가 불가능하다.
    _max_lag = max(4, max(e for _, _, _, e, _ in probes) + 1)
    lines, all_ok = [], True
    for col, lvl, kind, expect, grp in probes:
        if col not in cl.columns:
            lines.append(f"{col:24s} 정제본에 없음 — 건너뜀")
            continue
        if kind == "spread":
            if not {"corporate_bond_3y_AA", "treasury_bond_3y"} <= set(raw.columns):
                continue
            s = raw["corporate_bond_3y_AA"] - raw["treasury_bond_3y"]
            cand = s - s.shift(12)
        elif lvl not in raw.columns:
            lines.append(f"{col:24s} 원천 레벨 {lvl} 없음 — 건너뜀")
            continue
        elif kind == "log_ret":
            s = pd.to_numeric(raw[lvl], errors="coerce").clip(lower=1e-10)
            cand = np.log(s / s.shift(1))
        elif kind == "yoy":
            s = pd.to_numeric(raw[lvl], errors="coerce")
            past = s.shift(12).replace(0, 1e-6)
            cand = (s - past) / past * 100
        else:  # diff12
            s = pd.to_numeric(raw[lvl], errors="coerce")
            cand = s - s.shift(12)

        tgt = pd.to_numeric(cl[col], errors="coerce").dropna()
        k, err = _best_lag(tgt, cand, max_lag=_max_lag)
        ok = (k == expect)
        all_ok = all_ok and ok
        lines.append(f"{col:24s} Group {grp:7s} 실측 시차 {k}개월 "
                     f"(기대 {expect}) 잔차 {err:.3e}  "
                     f"{'OK' if ok else '*** 불일치 ***'}")
    lines.append(f"step6 추가 시차 MACRO_LAG_MONTHS = {MACRO_LAG_MONTHS}")
    from api_data_processing import impute_data as _imp
    lines.append(f"-> 패널 기준 총 시차: Group A {0 + MACRO_LAG_MONTHS}개월 / "
                 f"Group B {_imp.LAG_MONTHS_B + MACRO_LAG_MONTHS} / "
                 f"Group C {_imp.LAG_MONTHS_C + MACRO_LAG_MONTHS} / "
                 f"Group D {_imp.LAG_MONTHS_D + MACRO_LAG_MONTHS}")
    ok = all_ok and MACRO_LAG_MONTHS == 0
    if MACRO_LAG_MONTHS != 0:
        lines.append("★ step6 가 전 컬럼에 시차를 더 걸고 있다 = 이중 시차")
    _fail(res, "G1-7", "Group A 총 시차 = 0개월 (공표 시차만 적용)", ok,
          "\n".join(lines))


# ══════════════════════════════════════════════════════════════════════
# [확인] 금리 경로 커버리지
# ══════════════════════════════════════════════════════════════════════

def rate_channel_check(panel: pd.DataFrame, macro: pd.DataFrame) -> dict:
    """금리 경로가 실제로 커버되는지 확인한다.

    정책금리(base_rate_diff12)는 계단함수라 동결 구간에서 0 이 된다.
    시장 스프레드(credit_spread_diff12 / liquidity_spread_diff12)가 그 구간을
    메워 주는지 월별 충격값 시계열로 확인한다.
    """
    cols = [c for c in RATE_CHANNEL_COLS if c in macro.columns]
    lo, hi = panel["BASE_YM"].min(), panel["BASE_YM"].max()
    m = macro[["BASE_YM"] + cols].copy()
    m["BASE_YM"] = m["BASE_YM"].astype(str)
    m = m[(m["BASE_YM"] >= lo) & (m["BASE_YM"] <= hi)].sort_values("BASE_YM")
    m = m.set_index("BASE_YM")

    rows_by_ym = panel.groupby("BASE_YM").size()
    n_all = len(panel)
    n_valid = int((panel["BASE_YM"] >= split_spec.VALID_START).sum())
    rows_v = (panel[panel["BASE_YM"] >= split_spec.VALID_START]
              .groupby("BASE_YM").size())

    log.info("=" * 78)
    log.info("[확인] 금리 경로 커버리지 — 충격 항의 월별 값")
    log.info("=" * 78)
    summary = {}
    for c in cols:
        z = [ym for ym, v in m[c].items() if float(v) == 0.0]
        zr = int(rows_by_ym.reindex(z).sum() or 0)
        zrv = int(rows_v.reindex(z).sum() or 0)
        summary[c] = {"n_zero_months": len(z), "n_months": len(m), "zero_months": z,
                      "zero_row_pct": round(100 * zr / n_all, 2),
                      "zero_row_pct_valid": round(100 * zrv / max(n_valid, 1), 2),
                      "abs_median": float(m[c].abs().median()),
                      "min": float(m[c].min()), "max": float(m[c].max())}
        log.info("  %-26s 0 인 달 %2d개/%d  행비율 %5.2f%%  Valid행비율 %5.2f%%  "
                 "|값|중앙 %.4f  범위 %.3f ~ %.3f",
                 c, len(z), len(m), 100 * zr / n_all, 100 * zrv / max(n_valid, 1),
                 m[c].abs().median(), m[c].min(), m[c].max())

    log.info("")
    header = "  {:<8}".format("BASE_YM") + "".join("{:>24}".format(c) for c in cols) + "   구분"
    log.info(header)
    for ym, r in m.iterrows():
        seg = ("VALID" if ym >= split_spec.VALID_START
               else "DEV" if ym >= split_spec.DEV_START else "TRAIN")
        cells = "".join("{:>22.4f}{}".format(float(r[c]), " *" if float(r[c]) == 0.0 else "  ")
                        for c in cols)
        log.info("  %-8s%s   %s", ym, cells, seg)
    log.info("  (* = 그 달 충격 항이 정확히 0)")
    return {"monthly": m.reset_index().to_dict("records"), "summary": summary}


# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-tag", default="real")
    a = ap.parse_args()

    suffix = f"_{a.panel_tag}" if a.panel_tag else ""
    panel_path = config.OUTPUT_DIR / f"nh_panel_macro_12m_obv_none{suffix}.parquet"
    if not panel_path.exists():
        raise FileNotFoundError(
            f"{panel_path} 없음. 먼저 실행:\n"
            f"  python -m eda_pipeline.step6_macro_integration --tag {a.panel_tag}")

    res: list = []
    log.info("=" * 78)
    log.info("D축 게이트 1 — 데이터 무결성 (기준서 개정 R1 반영)")
    log.info("=" * 78)
    macro = gate_1_2(res)
    macro_cols = [c for c in macro.columns if c != "BASE_YM"]

    log.info("패널 로딩: %s", panel_path.name)
    con = duckdb.connect()
    try:
        cols = con.execute(
            f"SELECT * FROM read_parquet('{panel_path.as_posix()}') LIMIT 0").df().columns
        panel_macro = [c for c in cols if c in set(macro_cols)]
        want = (["V_BZNO", "BASE_YM"] + panel_macro
                + [n for n, _, _ in INTERACTIONS if n in set(cols)])
        sel = ", ".join(f'"{c}"' for c in want)
        panel = con.execute(
            f"SELECT {sel} FROM read_parquet('{panel_path.as_posix()}')").df()
    finally:
        con.close()
    panel["BASE_YM"] = panel["BASE_YM"].astype(str)
    log.info("  패널 %s / 거시 컬럼 %d개", panel.shape, len(panel_macro))

    gate_3(res, panel)
    gate_4(res, panel, macro, panel_macro)
    g5 = gate_5(res, panel)
    gate_6(res, macro, panel_macro)
    gate_7(res, macro)
    rate_ch = rate_channel_check(panel, macro)

    n_pass = sum(r["pass"] for r in res)
    log.info("=" * 78)
    log.info("게이트 1 결과: %d/%d 통과", n_pass, len(res))
    for r in res:
        log.info("  %-6s %-46s %s", r["id"], r["name"],
                 "PASS" if r["pass"] else "*** FAIL ***")
    log.info("=" * 78)

    out = config.VALIDATION_DIR / "D_axis_gate1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"panel": panel_path.name, "macro_source": MACRO_CLEANED.name,
         "criteria_revision": "R1",
         "macro_lag_months_step6": MACRO_LAG_MONTHS,
         "n_panel_macro": len(panel_macro),
         "interactions_8": INTERACTION_8, "interactions_hybrid": INTERACTION_HYBRID,
         "all_pass": n_pass == len(res), "checks": res,
         "g1_5_detail": g5, "rate_channel": rate_ch},
        ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("저장: %s", out)
    sys.exit(0 if n_pass == len(res) else 1)


if __name__ == "__main__":
    main()
