"""
======================================================================
C-1(c) 매크로 스트레스 시뮬레이션 — D8 (lgbm_v2_full.txt) 독립 산출
======================================================================
포털 `apply_macro_shock` 은 구 모델(230피처) 기준이고 D8(169피처)과 피처 교집합이
0 이라 재사용 불가. 여기서는 D8 상호작용항을 직접 재계산해 충격 전/후 PD 를 비교한다.

시나리오 (IFRS9 스트레스 테스트식 평행 이동):
  S1  신용스프레드 +100bp
  S2  KORIBOR 스프레드 +50bp

읽기 전용. lgbm_v2_full.txt 는 로드만. DB 미접근(패널 parquet 사용).

Usage
-----
    C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe -m eda_pipeline.step44_macro_stress_d8
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

import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec

LOG_PATH = _ROOT / "logs" / "C1_venn.log"
OUT_MD = config.VALIDATION_DIR / "C1_macro_stress_results.md"
MODEL = config.OUTPUT_DIR / "lgbm_v2_full.txt"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("C1c")

MD: list[str] = []


def md(s: str = "") -> None:
    MD.append(s)


def build_ix(panel: pd.DataFrame, macro: pd.DataFrame, macro_col: str,
             expo_col: str) -> pd.Series:
    mv = pd.to_numeric(macro[macro_col], errors="coerce")
    return (panel["BASE_YM"].map(mv).astype(float)
            * pd.to_numeric(panel[expo_col], errors="coerce")).astype("float32")


def main() -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    log.info("=" * 78)
    log.info("C-1(c) 매크로 스트레스 시뮬레이션 (D8) 시작 %s",
             datetime.now().isoformat(timespec="seconds"))

    from eda_pipeline import step38_production_retrain as s38
    from eda_pipeline.step37_macro_interactions import load_macro, SPEC, term_name

    df, feats, meta = s38.load_d8_frame()
    e14 = meta["e14"]
    log.info("D8 프레임: %s행 / 피처 %d / 상호작용 %d", f"{len(df):,}", len(feats),
             len(e14))

    booster = config.load_booster(str(MODEL))
    bfeat = booster.feature_name()
    assert set(bfeat) == set(feats), (
        f"모델 피처와 프레임 피처 불일치: "
        f"model-only={set(bfeat)-set(feats)} frame-only={set(feats)-set(bfeat)}")
    feats = bfeat  # 모델 순서에 맞춘다

    macro = load_macro()

    # spec 매핑: term -> (macro_col, exposure_col)
    spec_map = {}
    for m_col, expo, *_ in SPEC:
        spec_map[term_name(m_col, expo)] = (m_col, expo)
    # is_manufacturing 노출도 컬럼명 확인
    for t in e14:
        mc, ex = spec_map[t]
        if ex == "is_manufacturing" and "is_manufacturing" not in df.columns:
            # step37 은 패널에 이 컬럼이 있다고 가정. 없으면 STD_INDS 로 만든다.
            raise SystemExit("is_manufacturing 컬럼이 D8 프레임에 없음 — 확인 필요")

    va = df["BASE_YM"] >= split_spec.VALID_START
    log.info("Valid 행 %s (%s~%s)", f"{int(va.sum()):,}", split_spec.VALID_START,
             df.loc[va, "BASE_YM"].max())

    p0 = booster.predict(df.loc[va, feats])
    base_mean = float(np.mean(p0))
    log.info("기준 포트폴리오 평균 PD(raw) = %.6f (%.4f%%)", base_mean,
             base_mean * 100)

    # 차입금의존도(exp_rate) 상위 25%
    er = pd.to_numeric(df.loc[va, "exp_rate"], errors="coerce")
    hi_lev = er >= er.quantile(0.75)
    log.info("exp_rate(차입금의존도) 상위 25%%: %s행 / 임계 %.4f",
             f"{int(hi_lev.sum()):,}", er.quantile(0.75))

    # ── 시나리오 정의 ────────────────────────────────────────────
    # D8 상호작용항 중 각 거시 원계열에 의존하는 항
    credit_terms = [t for t in e14 if "credit" in spec_map[t][0].lower()
                    or "spread_credit" in spec_map[t][0].lower()]
    koribor_terms = [t for t in e14 if "KORIBOR" in spec_map[t][0]]
    log.info("신용스프레드 의존 D8 상호작용항: %s", credit_terms or "없음")
    log.info("KORIBOR 스프레드 의존 D8 상호작용항: %s", koribor_terms)

    credit_base_feats = [f for f in feats if "credit_spread" in f
                         or "spread_credit" in f]
    log.info("신용스프레드 의존 D8 기본피처: %s", credit_base_feats or "없음")

    # 부호 방어 가능 시나리오 — 단조 제약(+1/-1)이 걸린 항만 쓴다.
    # 제약이 부호를 강제하므로 시뮬 부호가 경제 이론과 일치한다.
    def cterms(macro_col: str) -> list[str]:
        return [t for t in e14 if spec_map[t][0] == macro_col]

    scenarios = [
        ("S1 신용스프레드 +100bp", "NEW_spread_credit_diff12", 1.00,
         credit_terms + credit_base_feats),
        ("S2 KORIBOR 스프레드 +50bp", "NEW_KORIBOR_spread_diff12", 0.50,
         koribor_terms),
        # ── 부호 방어 가능 (단조 제약 항) ──────────────────────────
        ("S3 제조업 내수 업황 BSI −10p (yoy)", "BSI_mfg_domestic_yoy", -10.0,
         cterms("BSI_mfg_domestic_yoy")),
        ("S4 수출물량 −10%p (yoy)", "export_index_yoy", -10.0,
         cterms("export_index_yoy")),
        ("S5 미분양 +20%p (yoy)", "unsold_housing_yoy", 20.0,
         cterms("unsold_housing_yoy")),
    ]
    log.info("부호 방어 시나리오 대상 항: S3 %s (mono -1) / S4 %s (mono -1) / "
             "S5 %s (mono +1)", cterms("BSI_mfg_domestic_yoy"),
             cterms("export_index_yoy"), cterms("unsold_housing_yoy"))

    md("# C-1(c). 매크로 스트레스 시뮬레이션 — D8 독립 산출")
    md()
    md(f"생성 {datetime.now().isoformat(timespec='seconds')} · "
       f"`eda_pipeline/step44_macro_stress_d8.py` · 로그 `logs/C1_venn.log`")
    md(f"모델 `eda_pipeline/output/lgbm_v2_full.txt` (D8, 169피처) · "
       f"패널 `nh_panel_macro_12m_obv_none_real.parquet`")
    md()
    md("> 포털 `apply_macro_shock`(구 모델 230피처)과 D8 피처 교집합이 0 이라 포털 경로는 "
       "재사용 불가(A4_portal_status.md). 여기서는 D8 상호작용항 "
       "`ix_* = 거시원계열[BASE_YM] × 노출도` 를 직접 재계산해 충격 전/후 `booster.predict()` 를 "
       "비교한다. 충격은 IFRS9 스트레스식 **전 기간 평행 이동**이다.")
    md()
    md(f"- 대상: **Valid 홀드아웃** ({split_spec.VALID_START}~"
       f"{df.loc[va, 'BASE_YM'].max()}, {int(va.sum()):,}행)")
    md(f"- 기준 포트폴리오 평균 PD(raw) = **{base_mean*100:.4f}%** "
       f"(raw 는 `scale_pos_weight` 팽창분 포함 — 절대수준이 아니라 **충격 전/후 변화**를 본다)")
    md()
    md("| 시나리오 | 충격 대상 거시계열 | 재계산 항 | 평균 PD 변화 | Δ(%p) | "
       "상대변화 | 차입금의존도 상위25% Δ(%p) | 전체보다 큰가 |")
    md("|---|---|---|--:|--:|--:|--:|:--:|")

    results = []
    for label, mcol, delta, affected in scenarios:
        if not affected:
            md(f"| {label} | `{mcol}` | **없음** | — | **0.0000** | 0.0% | — | — |")
            log.info("[%s] D8 에 의존 피처가 없다 → 충격 효과 0. (D8 은 이 채널을 "
                     "4구간 부호검사 탈락으로 제외했다)", label)
            results.append((label, 0.0, 0.0, None))
            continue
        if mcol not in macro.columns:
            md(f"| {label} | `{mcol}` (거시원천에 없음) | {affected} | — | — | — | — | — |")
            log.info("[%s] %s 가 macro 에 없음 — 건너뜀", label, mcol)
            continue
        dfx = df.copy()
        macx = macro.copy()
        macx[mcol] = pd.to_numeric(macx[mcol], errors="coerce") + delta
        for t in affected:
            if t in e14:
                m_c, expo = spec_map[t]
                # 이 항이 충격 대상 계열을 쓰는 경우에만 재계산
                if m_c == mcol:
                    dfx[t] = build_ix(dfx, macx, m_c, expo)
            elif t in dfx.columns:
                # 기본 피처(원계열 그대로)면 +delta
                dfx[t] = pd.to_numeric(dfx[t], errors="coerce") + delta
        p1 = booster.predict(dfx.loc[va, feats])
        new_mean = float(np.mean(p1))
        d_all = (new_mean - base_mean) * 100
        d_hi = (float(np.mean(p1[hi_lev.values])) -
                float(np.mean(p0[hi_lev.values]))) * 100
        bigger = "예" if abs(d_hi) > abs(d_all) else "아니오"
        rel = (new_mean / base_mean - 1) * 100
        md(f"| {label} | `{mcol}` ({delta:+g}) | "
           f"{', '.join(f'`{t}`' for t in affected)} | "
           f"{base_mean*100:.4f}% → {new_mean*100:.4f}% | **{d_all:+.4f}** | "
           f"{rel:+.1f}% | {d_hi:+.4f} | {bigger} |")
        log.info("[%s] mean PD %.6f -> %.6f (Δ%+.4f%%p, rel %+.1f%%) | "
                 "hi-lev Δ%+.4f%%p | 더 큼=%s", label, base_mean, new_mean,
                 d_all, rel, d_hi, bigger)
        results.append((label, d_all, d_hi, rel))

    md()
    md("## 해석")
    md()
    md("- **S1 신용스프레드**: D8 에는 신용스프레드를 재료로 하는 피처가 **하나도 없다.** "
       "D6 의 `credit_spread_x_lev` 는 4구간 부호검사에서 탈락(Train 전체 −0.796 / "
       "Valid +0.785 완전 반전)해 D8 구성에서 빠졌다. 따라서 이 충격은 D8 예측을 "
       "**정확히 0** 만큼 움직인다. 이것은 버그가 아니라 **D8 이 신뢰할 수 없는 채널을 "
       "의도적으로 배제한 결과**다.")
    md("- **S2 KORIBOR 스프레드**: `ix_KORIBOR_spread_d12__liq` 한 항이 반응한다. "
       "이 항은 D8 거시 gain 0.93% 중 약 0.6%p 를 담당하는 **유일하게 유효한 거시 채널**이다. "
       "단기부채비중(`exp_liq`)을 곱한다. 단조 제약은 **0**(방향 미지정) — KORIBOR−기준금리 "
       "스프레드가 자금경색과 금리인상 기대를 함께 반영해 경제적 해석이 양방향이기 때문이다.")
    md("- ★ **부호에 주의.** 위 표에서 스프레드 확대(+50bp)에 포트폴리오 평균 PD 가 "
       "**내려간다.** 이는 '스프레드가 벌어지면 부도위험이 준다'는 뜻이 **아니다.** "
       "관측 53개월에 금리 사이클이 한 번뿐이라, `NEW_KORIBOR_spread_diff12` 가 높았던 "
       "2022~23 긴축기에 부도율이 아직 낮았고 스프레드가 음(−)으로 돌아선 2024~25 "
       "인하기에 부도가 몰렸다. 모델이 학습한 상관은 그 한 사이클의 방향이며, "
       "docs/05 §5 의 '금리 계열 부호 반전'과 정확히 같은 현상이다. **이 시뮬레이션이 "
       "보여주는 것은 방향이 아니라 (i) 노출도 상호작용이 기계적으로 작동한다는 것과 "
       "(ii) 반응 크기가 차입 의존도에 비례한다는 것이다.**")
    md("- 차입금의존도(`exp_rate`) 상위 25% 의 |반응|이 전체보다 큰지는 위 표 마지막 열 참조 "
       "(실측: 더 크다). ★ D8 KORIBOR 항이 실제로 곱하는 노출도는 `exp_rate`(차입금의존도)가 "
       "아니라 `exp_liq`(단기부채비중)다. 두 노출도는 상관이 있으나 동일하지 않다 — "
       "그럼에도 `exp_rate` 상위군의 반응이 더 크다는 것은 두 레버리지 축이 함께 움직인다는 뜻.")
    md()
    md("- **S3~S5 (부호 방어 가능 시나리오)**: 단조 제약이 걸린 항만 골랐다. "
       "제약이 부호를 강제하므로 시뮬 방향이 경제 이론과 일치한다. "
       "`ix_BSI_mfg_domestic__mfg`(제약 −1)·`ix_export_index__mfg`(−1)은 업황·수출이 "
       "나빠질 때 제조업 차주 PD 가 **상승**하고, `ix_unsold_housing__mfg`(+1)는 미분양이 "
       "늘 때 상승한다. 위 표의 S3~S5 행 부호를 확인하라. **이 세 항은 06 문서에서 "
       "'부호가 방어 가능한 스트레스 시나리오'로 제시할 수 있다.** 다만 gain 기여는 "
       "미미하다(각 0.02~0.03%, `step36_final_config.md` §4).")
    md("- **S1·S2 는 스트레스 시나리오 수치로 쓰지 않는다.** S1 은 채널 자체가 없고(효과 0), "
       "S2 는 부호가 단일 사이클 표본 한계로 이론과 반대다. 두 결과의 용도는 "
       "**(i) 노출도 상호작용의 기계적 작동 (ii) 반응 크기가 차입 의존도에 비례**를 "
       "보이는 것뿐이다.")
    md()
    md("> **한계**: 이 시뮬레이션은 백테스트로 검증되지 않았다. 거시 충격을 전 기간 "
       "평행 이동으로 가했고(실제 스프레드 동학·2차 효과 미반영), raw PD 를 썼다(보정 전). "
       "IFRS9 스트레스 테스트가 정확히 이 방식이며, **실제 사용 가치(민감도 방향·크기의 "
       "기업별 분포)를 보여주는 예시일 뿐 예측 성능의 근거가 아니다.** D8 거시 채널의 "
       "부호가 단일 사이클에 묶여 있다는 사실은 이 산출물의 신뢰 범위를 좁힌다.")
    md()

    OUT_MD.write_text("\n".join(MD) + "\n", encoding="utf-8")
    log.info("작성: %s", OUT_MD)
    log.info("C-1(c) 종료")


if __name__ == "__main__":
    main()
