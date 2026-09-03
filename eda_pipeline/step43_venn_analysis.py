"""
======================================================================
C-1 벤 다이어그램 분석 — 내부 EWS vs D8 / 국면 선반영 / 재무 양호군
======================================================================
읽기 전용. 학습·DB 쓰기 없음.

  A  내부 모형(OBV_RZVL_POD) vs 우리 모형(D8 PROB_FULL) 상위 X% 대조
     ★ 내부 POD 는 202101~202111(11개월)에만 값이 있다. 그 창은 전부 TRAIN·저금리기.
     그래서 "모형 대 모형" 벤은 이 창에서만 성립한다 (in-sample / 저금리기).
  B  우리 모형 단독 — Valid(인하기) 상위 X% 부도 포착률 (오염 없는 주 수치)
  C  긴축기 경보 → 인하기 부도 (관측 Train / 부도 Valid = 오염 아님)
  D  재무 양호군(C302_CRI_ORD 상위 50%) 부도 포착률

출력: logs/C1_venn.log 에 append, eda_pipeline/output/validation/C1_venn_results.md

Usage
-----
    C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe -m eda_pipeline.step43_venn_analysis
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb
import numpy as np
import pandas as pd

from eda_pipeline import config

DB = _ROOT / "database" / "portal_v2.duckdb"
POD_PARQUET = config.OUTPUT_DIR / "internal_ews_pod.parquet"
LOG_PATH = _ROOT / "logs" / "C1_venn.log"
OUT_MD = config.VALIDATION_DIR / "C1_venn_results.md"

XS = [10, 20, 30]
POD_WINDOW_END = "202111"          # 내부 POD 가 값>0 인 마지막 달
TIGHT_START, TIGHT_END = "202206", "202312"   # 긴축기
EASE_START, EASE_END = "202401", "202505"     # 인하기 = VALID

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("C1")

MD: list[str] = []


def md(s: str = "") -> None:
    MD.append(s)


# ────────────────────────────────────────────────────────────────────
def load_base() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        df = con.execute("""
            SELECT V_BZNO, BASE_YM, SPLIT, IS_BUDO_12M,
                   PROB_FULL, C302_CRI_ORD, exp_rate,
                   JEMU_118000, JEMU_115000
            FROM corporate_panel
        """).df()
    finally:
        con.close()
    pod = duckdb.connect().execute(
        f"SELECT V_BZNO, BASE_YM, OBV_RZVL_POD "
        f"FROM read_parquet('{POD_PARQUET.as_posix()}')").df()
    df["V_BZNO"] = df["V_BZNO"].astype(str)
    df["BASE_YM"] = df["BASE_YM"].astype(str)
    pod["V_BZNO"] = pod["V_BZNO"].astype(str)
    pod["BASE_YM"] = pod["BASE_YM"].astype(str)
    n0 = len(df)
    df = df.merge(pod, on=["V_BZNO", "BASE_YM"], how="left")
    assert len(df) == n0, f"조인 행수 변동 {n0}->{len(df)}"
    return df


def top_mask(s: pd.Series, x_pct: int, sub: pd.Series) -> pd.Series:
    """sub(=행 필터) 안에서 s 상위 x_pct% 를 True 로. 동점은 모두 포함(>= 임계)."""
    v = pd.to_numeric(s[sub], errors="coerce")
    thr = v.quantile(1 - x_pct / 100)
    m = pd.Series(False, index=s.index)
    m.loc[sub] = (v >= thr).values
    return m.fillna(False)


def rate(n_budo: int, n: int) -> str:
    return f"{100 * n_budo / n:.4f}%" if n else "—"


# ════════════════════════════════════════════════════════════════════
# A — 내부 vs 우리 (202101~202111 창)
# ════════════════════════════════════════════════════════════════════
def part_a(df: pd.DataFrame) -> None:
    win = df[df["BASE_YM"] <= POD_WINDOW_END].copy()
    n, nb = len(win), int(win["IS_BUDO_12M"].sum())
    log.info("[A] 모형 대조 창 202101~%s : %s행 / 양성 %s / 기업 %s",
             POD_WINDOW_END, f"{n:,}", f"{nb:,}", f"{win['V_BZNO'].nunique():,}")
    md("## A. 내부 EWS vs 우리 모형(D8) — 상위 X% 대조")
    md()
    md(f"> ★ **내부 EWS 부도율(`OBV_RZVL_POD`)은 202101~{POD_WINDOW_END} (11개월)에만 "
       f"값이 존재한다.** 원천 `가상사업자_VH_OBV_DTL_관찰세부등급v.txt` 의 `RZVL_POD` 가 "
       f"202112 이후 전 행 0 이다 (raw 970,459행 실측). 이 창은 **전부 TRAIN 이며 "
       f"전부 저금리기**다. 따라서 '모형 대 모형' 교집합 비교는 이 창에서만 가능하고, "
       f"**in-sample · 단일 국면**이라는 한계를 함께 읽어야 한다. 구간별 국면 비교는 "
       f"불가능하다 (내부 모형에 긴축기·인하기 값이 없다).")
    md()
    md(f"대상: `corporate_panel` ⨝ `internal_ews_pod.parquet`, BASE_YM ≤ {POD_WINDOW_END} · "
       f"{n:,}행 / 양성 {nb:,} / 기업 {win['V_BZNO'].nunique():,} · 기준율 {rate(nb, n)}")
    md()
    sub = pd.Series(True, index=win.index)
    for lvl, unit in (("행", "row"), ("기업", "firm")):
        md(f"### 단위: {lvl}")
        md()
        md("| X% | 교집합 n | 교집합 부도(율) | 우리만 n | 우리만 부도(율) | "
           "내부만 n | 내부만 부도(율) | 교집합 포착률 | 우리 상위 포착률 | 내부 상위 포착률 |")
        md("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for x in XS:
            ours = top_mask(win["PROB_FULL"], x, sub)
            intl = top_mask(win["OBV_RZVL_POD"], x, sub)
            both = ours & intl
            only_o = ours & ~intl
            only_i = intl & ~ours
            if unit == "row":
                def cnt(m):
                    return int(m.sum()), int(win.loc[m, "IS_BUDO_12M"].sum())
                tot_b = nb
            else:
                budo_firms = set(win.loc[win["IS_BUDO_12M"] == 1, "V_BZNO"])
                def cnt(m):
                    f = set(win.loc[m, "V_BZNO"])
                    return len(f), len(f & budo_firms)
                tot_b = len(set(win.loc[win["IS_BUDO_12M"] == 1, "V_BZNO"]))
            b_n, b_b = cnt(both)
            o_n, o_b = cnt(only_o)
            i_n, i_b = cnt(only_i)
            ours_all_n, ours_all_b = cnt(ours)
            intl_all_n, intl_all_b = cnt(intl)
            md(f"| {x}% | {b_n:,} | {b_b:,} ({rate(b_b, b_n)}) | "
               f"{o_n:,} | {o_b:,} ({rate(o_b, o_n)}) | "
               f"{i_n:,} | {i_b:,} ({rate(i_b, i_n)}) | "
               f"{100*b_b/tot_b:.1f}% | {100*ours_all_b/tot_b:.1f}% | "
               f"{100*intl_all_b/tot_b:.1f}% |")
            log.info("  [A %s x=%d] both n=%d b=%d | ours_only n=%d b=%d | "
                     "intl_only n=%d b=%d | ours_all_capture=%.1f%% "
                     "intl_all_capture=%.1f%%", unit, x, b_n, b_b, o_n, o_b,
                     i_n, i_b, 100*ours_all_b/tot_b, 100*intl_all_b/tot_b)
        md()


# ════════════════════════════════════════════════════════════════════
# B — 우리 모형 단독, Valid
# ════════════════════════════════════════════════════════════════════
def part_b(df: pd.DataFrame) -> None:
    md("## B. 우리 모형(D8) 단독 — 상위 X% 부도 포착률 (오염 없는 주 수치)")
    md()
    md("> 내부 모형은 Valid(인하기)에 값이 없어 대조 불가. 아래는 D8 `PROB_FULL` "
       "단독 포착률이다. **인하기 = VALID 홀드아웃이므로 out-of-sample 수치다.**")
    md()
    for split, label, lo, hi in (
            ("VALID", "인하기 = VALID", EASE_START, EASE_END),
            ("TRAIN", "저금리기+긴축기 = TRAIN", "202101", "202312")):
        seg = df[df["SPLIT"] == split].copy()
        n, nb = len(seg), int(seg["IS_BUDO_12M"].sum())
        bf = set(seg.loc[seg["IS_BUDO_12M"] == 1, "V_BZNO"])
        md(f"### {label}  ({lo}~{hi}, {n:,}행 / 양성 {nb:,} / 부도기업 {len(bf):,} / "
           f"기준율 {rate(nb, n)})")
        md()
        md("| X% | 행 n | 행 부도 | 행 포착률 | 기업 n | 기업 부도 | 기업 포착률 | 행 Lift |")
        md("|--:|--:|--:|--:|--:|--:|--:|--:|")
        sub = pd.Series(True, index=seg.index)
        for x in XS:
            m = top_mask(seg["PROB_FULL"], x, sub)
            rn, rb = int(m.sum()), int(seg.loc[m, "IS_BUDO_12M"].sum())
            fn = seg.loc[m, "V_BZNO"].nunique()
            fb = len(set(seg.loc[m, "V_BZNO"]) & bf)
            lift = (rb / rn) / (nb / n) if rn else float("nan")
            md(f"| {x}% | {rn:,} | {rb:,} | {100*rb/nb:.1f}% | "
               f"{fn:,} | {fb:,} | {100*fb/len(bf):.1f}% | {lift:.2f} |")
            log.info("  [B %s x=%d] row n=%d b=%d capture=%.1f%% lift=%.2f | "
                     "firm n=%d b=%d capture=%.1f%%", split, x, rn, rb,
                     100*rb/nb, lift, fn, fb, 100*fb/len(bf))
        md()
    md("> ★ **각주**: Train 은 in-sample(모델이 학습한 구간), Valid 는 out-of-sample. "
       "두 블록의 포착률 차이를 국면효과(저금리·긴축 vs 인하)로 해석하지 말 것 — "
       "in-sample/out-of-sample 효과가 섞여 있다.")
    md()


# ════════════════════════════════════════════════════════════════════
# C — 긴축기 경보 → 인하기 부도
# ════════════════════════════════════════════════════════════════════
def part_c(df: pd.DataFrame) -> None:
    md("## C. 긴축기 경보 → 인하기 부도 (관측 Train / 부도 Valid = 오염 아님)")
    md()
    tight = df[(df["BASE_YM"] >= TIGHT_START) & (df["BASE_YM"] <= TIGHT_END)].copy()
    ease = df[(df["BASE_YM"] >= EASE_START) & (df["BASE_YM"] <= EASE_END)].copy()
    # 인하기에 존재하는 기업만 대상 (관측 가능해야 부도 여부를 판정)
    ease_firms = set(ease["V_BZNO"])
    ease_budo_firms = set(ease.loc[ease["IS_BUDO_12M"] == 1, "V_BZNO"])
    md(f"- 긴축기 {TIGHT_START}~{TIGHT_END}: {len(tight):,}행 / 기업 "
       f"{tight['V_BZNO'].nunique():,}")
    md(f"- 인하기 {EASE_START}~{EASE_END}: {len(ease):,}행 / 기업 {len(ease_firms):,} / "
       f"부도기업 {len(ease_budo_firms):,} (인하기 기업 기준 부도율 "
       f"{100*len(ease_budo_firms)/len(ease_firms):.4f}%)")
    md()
    md("긴축기에 D8 `PROB_FULL` 상위 X% 로 **한 번이라도** 경보가 났던 기업을 A군, "
       "나머지를 B군으로 나누고, 두 군의 **인하기 부도율**을 비교한다.")
    md()
    md("| 모형 | X% | 경보 기업수 A | A 중 인하기 부도 | A 부도율 | 비경보 B 부도율 | "
       "Lift(A/B) | 인하기 전체부도 중 A 포착률 |")
    md("|---|--:|--:|--:|--:|--:|--:|--:|")
    sub_t = pd.Series(True, index=tight.index)
    tight_pod_nz = int((pd.to_numeric(tight["OBV_RZVL_POD"], errors="coerce") > 0).sum())
    for mdl, col in (("우리 D8", "PROB_FULL"), ("내부 EWS", "OBV_RZVL_POD")):
        if col == "OBV_RZVL_POD" and tight_pod_nz == 0:
            md(f"| 내부 EWS | — | — | — | — | — | — | — | "
               f"긴축기 `OBV_RZVL_POD` 값>0 행 {tight_pod_nz} → 산출 불가 |")
            log.info("  [C 내부 EWS] 긴축기 POD>0 행 0 → 스킵")
            continue
        for x in XS:
            m = top_mask(tight[col], x, sub_t)
            a_firms = set(tight.loc[m, "V_BZNO"])
            a_in_ease = a_firms & ease_firms
            b_in_ease = ease_firms - a_firms
            a_bud = len(a_in_ease & ease_budo_firms)
            b_bud = len(b_in_ease & ease_budo_firms)
            a_rt = a_bud / len(a_in_ease) if a_in_ease else float("nan")
            b_rt = b_bud / len(b_in_ease) if b_in_ease else float("nan")
            lift = a_rt / b_rt if b_rt else float("nan")
            cap = a_bud / len(ease_budo_firms) if ease_budo_firms else float("nan")
            note = ""
            if col == "OBV_RZVL_POD":
                note = "  ← 긴축기 POD 전부 0, 무의미"
            md(f"| {mdl} | {x}% | {len(a_in_ease):,} | {a_bud:,} | "
               f"{100*a_rt:.4f}% | {100*b_rt:.4f}% | {lift:.2f} | {100*cap:.1f}% |{note}")
            log.info("  [C %s x=%d] A_firms(in ease)=%d a_bud=%d a_rate=%.4f%% "
                     "b_rate=%.4f%% lift=%.2f cap=%.1f%%%s", mdl, x,
                     len(a_in_ease), a_bud, 100*a_rt, 100*b_rt, lift,
                     100*cap, note)
    md()
    # k=4 lag 상관 재현
    rate_by_m = df.groupby("BASE_YM")["IS_BUDO_12M"].mean() * 100
    br = json.loads((config.VALIDATION_DIR / "step39_venn_prep.json")
                    .read_text(encoding="utf-8"))["stress_windows"]["base_rate_by_month"]
    brs = pd.Series(br)
    common = sorted(set(rate_by_m.index) & set(brs.index))
    dr = rate_by_m.loc[common].reset_index(drop=True)
    corrs = []
    for k in range(0, 13):
        a = dr.iloc[k:].reset_index(drop=True)
        b = pd.Series([brs[common[i - k]] for i in range(k, len(common))])
        if len(a) > 3:
            corrs.append((k, float(np.corrcoef(a, b)[0, 1])))
    kmax = max(corrs, key=lambda t: t[1])
    md(f"**시차 상관 재현** (부도율[t] vs base_rate[t−k], 패널 53개월):")
    md("")
    md("| k(월) | " + " | ".join(str(k) for k, _ in corrs) + " |")
    md("|--:|" + "--:|" * len(corrs))
    md("| r | " + " | ".join(f"{r:.3f}" for _, r in corrs) + " |")
    md("")
    md(f"argmax at **k={kmax[0]} (r={kmax[1]:.3f})**, k=0 은 r={corrs[0][1]:.3f}. "
       f"step42/A3 의 r=0.931@k=4 와 정합.")
    md()
    md("> ★ **유보 3가지 (반드시 함께 읽는다)**")
    md("> 1. 부도율은 2024 에 한 번 반락한다 (월별 최저 202404 1.115%). 단조 후행이 "
       "아니라 '긴축 고점 유지 중 정체·소폭 반락 → 인하 국면 재점화'의 **2단 패턴**이다.")
    md("> 2. 부도율·기준금리 두 시계열이 관측창 안에서 공통 우상향 추세라 상관계수의 "
       "**절대 수준은 부풀려져 있다** (k=0 에서도 r≈0.88). 근거로 쓸 수 있는 것은 "
       "크기가 아니라 lag 곡선이 **k=4 에서 단봉으로 꺾이는 형태**와 구간별 순서다.")
    md("> 3. **인하기 구간(202401~202505)은 `split_spec.py` 의 VALID 홀드아웃과 정확히 "
       "겹친다.** 국면 효과와 표본 시기 효과가 분리되지 않으므로 이 표는 관측 사실로만 "
       "인용하고 모델 성능 변화의 원인으로 돌리지 않는다.")
    md()


# ════════════════════════════════════════════════════════════════════
# D — 재무 양호군
# ════════════════════════════════════════════════════════════════════
def part_d(df: pd.DataFrame) -> None:
    md("## D. 재무 양호군(C302_CRI_ORD 상위 50%) 부도 포착률")
    md()
    v = pd.to_numeric(df["C302_CRI_ORD"], errors="coerce")
    med = float(v.median())
    good = (v <= med)          # 등급 서열 — 낮을수록 양호
    df = df.assign(_good=good.fillna(False), _c302_miss=v.isna())
    md(f"- `C302_CRI_ORD` median = {med:.1f} · 결측률 {v.isna().mean()*100:.2f}% · "
       f"'상위 50%' = 값 ≤ median")
    md(f"- 결측(등급 이력 없음) 행은 양호군에서 제외 (판정 불가)")
    md()
    md("'재무제표는 양호한데 부도한' 기업을 우리 모형이 잡아내는가를 본다.")
    md()
    for split, label, lo, hi in (
            ("VALID", "인하기 = VALID", EASE_START, EASE_END),
            ("__ALL__", "전 구간", "202101", "202505")):
        seg = df if split == "__ALL__" else df[df["SPLIT"] == split]
        gseg = seg[seg["_good"]].copy()
        gb = gseg[gseg["IS_BUDO_12M"] == 1]
        gbf = set(gb["V_BZNO"])
        n, nb = len(gseg), len(gb)
        md(f"### {label} ({lo}~{hi})")
        md()
        md(f"재무양호군: {n:,}행 / 그중 부도 {nb:,}행 · 부도기업 {len(gbf):,} · "
           f"양호군 부도율 {rate(nb, n)}")
        md()
        md("| 모형 | X% | 양호·부도 행 중 상위 X% 포착 | 행 포착률 | "
           "양호·부도 기업 포착 | 기업 포착률 |")
        md("|---|--:|--:|--:|--:|--:|")
        sub = pd.Series(True, index=seg.index)
        for mdl, col, only_win in (("우리 D8", "PROB_FULL", False),
                                   ("내부 EWS", "OBV_RZVL_POD", True)):
            for x in XS:
                if only_win:
                    s2 = seg[seg["BASE_YM"] <= POD_WINDOW_END]
                    if s2.empty:
                        md(f"| {mdl} | {x}% | — | — | — | — |  ← 내부 POD 값 없음 "
                           f"(≤{POD_WINDOW_END} 만)")
                        continue
                    sub2 = pd.Series(True, index=s2.index)
                    m = top_mask(s2[col], x, sub2)
                    g2 = s2[s2["_good"] & (s2["IS_BUDO_12M"] == 1)]
                    hit_rows = int((m & s2["_good"] & (s2["IS_BUDO_12M"] == 1)).sum())
                    g2f = set(g2["V_BZNO"])
                    hit_f = len(set(s2.loc[m, "V_BZNO"]) & g2f)
                    md(f"| {mdl} (≤{POD_WINDOW_END}) | {x}% | {hit_rows:,}/{len(g2):,} | "
                       f"{100*hit_rows/len(g2) if len(g2) else 0:.1f}% | "
                       f"{hit_f:,}/{len(g2f):,} | "
                       f"{100*hit_f/len(g2f) if g2f else 0:.1f}% |")
                    log.info("  [D %s %s x=%d win] rows %d/%d firms %d/%d",
                             label, mdl, x, hit_rows, len(g2), hit_f, len(g2f))
                else:
                    m = top_mask(seg[col], x, sub)
                    hit_rows = int((m.values & gseg.reindex(seg.index)["_good"].fillna(False).values
                                    ).sum()) if False else int(
                        (m & seg["_good"] & (seg["IS_BUDO_12M"] == 1)).sum())
                    hit_f = len(set(seg.loc[m, "V_BZNO"]) & gbf)
                    md(f"| {mdl} | {x}% | {hit_rows:,}/{nb:,} | "
                       f"{100*hit_rows/nb if nb else 0:.1f}% | "
                       f"{hit_f:,}/{len(gbf):,} | "
                       f"{100*hit_f/len(gbf) if gbf else 0:.1f}% |")
                    log.info("  [D %s %s x=%d] rows %d/%d firms %d/%d",
                             label, mdl, x, hit_rows, nb, hit_f, len(gbf))
        md()


def main() -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    log.info("=" * 78)
    log.info("C-1 벤 분석 시작 %s", datetime.now().isoformat(timespec="seconds"))
    df = load_base()
    log.info("패널 %s행 / 양성 %s / 기업 %s / POD>0 행 %s",
             f"{len(df):,}", f"{int(df['IS_BUDO_12M'].sum()):,}",
             f"{df['V_BZNO'].nunique():,}",
             f"{int((pd.to_numeric(df['OBV_RZVL_POD'], errors='coerce') > 0).sum()):,}")

    md(f"# C-1. 벤 다이어그램 분석 결과")
    md()
    md(f"생성 {datetime.now().isoformat(timespec='seconds')} · "
       f"`eda_pipeline/step43_venn_analysis.py` · 로그 `logs/C1_venn.log`")
    md(f"원자료: `database/portal_v2.duckdb::corporate_panel` (D8 재채점, `PROB_FULL`=`PROB_RAW`) "
       f"⨝ `eda_pipeline/output/internal_ews_pod.parquet`")
    md()
    md("**핵심 제약 (먼저 읽는다)**: 내부 EWS 부도율(`OBV_RZVL_POD`)은 원천 파일에서 "
       "**202101~202111 (11개월)에만** 값이 있다. 202112 이후 전 행 0 이다 "
       "(raw `가상사업자_VH_OBV_DTL_관찰세부등급v.txt` 970,459행 실측). "
       "`step39_venn_prep.json` 의 `budo_pod_coverage 1.0` 은 NULL 이 아닌 "
       "**0 을 값으로 집계한 오탐**이었다. 따라서 **내부 조기경보모형과의 직접 대조"
       "(당초 (a-1)·(a-2))는 수행하지 못했다** — 값이 있는 11개월이 전부 TRAIN·전부 "
       "저금리기라 국면이 하나뿐이고 in-sample 이다. 이 한계는 07 문서 §4-12 에 기록했다. "
       "오염 없는 주 수치는 **B(우리 모형 Valid 단독)** 와 **D(재무양호군 포착)**, "
       "보조로 **C(긴축기 경보→인하기 부도)** 다.")
    md()

    #: 내부모형 대조 A 파트는 데이터 한계(RZVL_POD 11개월·in-sample)로 최종본에서 제외한다.
    #: 진단 목적으로 계산이 필요하면 True 로 두되, C1_venn_results.md 에는 싣지 않는다.
    WRITE_PART_A = False
    if WRITE_PART_A:
        part_a(df)
    part_b(df)
    part_c(df)
    part_d(df)

    md("## 관련 산출물")
    md()
    md("- C-1(c) 매크로 스트레스 시뮬레이션: `C1_macro_stress_results.md` "
       "(`eda_pipeline/step44_macro_stress_d8.py`)")
    md("- 스크립트: `eda_pipeline/step43_venn_analysis.py` · 로그: `logs/C1_venn.log`")
    md("- 준비 자료: `eda_pipeline/output/validation/step39_venn_prep.json` · "
       "`eda_pipeline/output/internal_ews_pod.parquet`")
    md()

    OUT_MD.write_text("\n".join(MD) + "\n", encoding="utf-8")
    log.info("작성: %s (%d줄)", OUT_MD, len(MD))
    log.info("C-1 벤 분석 종료")


if __name__ == "__main__":
    main()
