"""
======================================================================
거시 피처 한글 라벨 생성 — 원천 대조 방식
======================================================================
`api_data_processing/config/indicator_names.csv` 를 **원천으로 삼아** 거시 변환
변수와 상호작용항의 한글 라벨을 만든다.

★ 수동 하드코딩 금지. JEMU 라벨이 한 칸 밀려 28개 중 21개가 틀렸던 사고가 있었다.
  원천 CSV 의 `series_name -> name_kr` 매핑만 쓰고, 없는 것은 **빈칸으로 둔다**
  (원본 코드명을 그대로 노출하는 기존 `get_feature_label` 동작과 같다).

생성 규칙
--------
  거시 변환 변수   `{원지표}_{접미사}` -> "{한글명} {접미사 한글}"
      _log_ret -> 월간 로그수익률 / _vol_m -> 월간 변동성
      _diff12  -> 12개월 차분     / _yoy   -> 전년동월대비
      _ma3m    -> 3개월 이동평균  (중첩 가능: _yoy_ma3m -> "전년동월대비 3개월 이동평균")
  상호작용항       `ix_{거시}__{노출도}` -> "{거시 라벨} × {노출도 라벨}"

Usage
-----
    python -m eda_pipeline.step41_macro_labels            # 미리보기만
    python -m eda_pipeline.step41_macro_labels --write    # feature_labels.py 에 추가
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd

from eda_pipeline import config

NAMES_CSV = (_PROJECT_ROOT / "api_data_processing" / "config"
             / "indicator_names.csv")
LABELS_PY = _PROJECT_ROOT / "backend" / "feature_labels.py"
SPEC_JSON = config.VALIDATION_DIR / "macro_interaction_candidates.json"
OUT_JSON = config.VALIDATION_DIR / "macro_labels_generated.json"

#: 접미사 -> 한글. 긴 것부터 매칭해야 `_yoy_ma3m` 이 `_yoy` 로 먼저 잡히지 않는다.
SUFFIX_KR = [
    ("_log_ret", "월간 로그수익률"),
    ("_vol_m", "월간 변동성"),
    ("_diff12", "12개월 차분"),
    ("_yoy", "전년동월대비"),
    ("_ma3m", "3개월 이동평균"),
]

#: 노출도 한글명. 원천 CSV 에 없는 기업 재무 파생이므로 여기서 정의한다.
#: 정의는 `step6_macro_integration.build_exposures` docstring 과 일치시킨다.
EXPOSURE_KR = {
    "exp_rate": "차입금의존도",
    "exp_liq": "단기부채비중",
    "exp_inv": "재고부담",
    "exp_fx": "수출비중",
    "exp_fx_hybrid": "수출비중(업종추정 병용)",
    "exp_young": "업력 5년 이하",
    "is_manufacturing": "제조업 여부",
    # step37 의 term_name 이 축약한 형태
    "rate": "차입금의존도",
    "liq": "단기부채비중",
    "inv": "재고부담",
    "fx": "수출비중",
    "fx_hybrid": "수출비중(업종추정 병용)",
    "young": "업력 5년 이하",
    "mfg": "제조업 여부",
}

#: 원천 CSV 에 없는 파생 거시. 계산식이 명확한 것만 둔다.
DERIVED_MACRO_KR = {
    "credit_spread": "신용스프레드(회사채AA-3년 − 국고채3년)",
    "liquidity_spread": "유동성스프레드(CP91일 − 통안91일)",
    "KORIBOR_spread": "단기금리스프레드(KORIBOR3M − 기준금리)",
    "spread_term": "기간스프레드(국고채10년 − 3년)",
    "spread_credit": "신용스프레드(회사채AA-3년 − 국고채3년)",
}


def load_name_map() -> dict[str, str]:
    df = pd.read_csv(NAMES_CSV, dtype=str, comment="#").fillna("")
    m = {}
    for _, r in df.iterrows():
        k = str(r["series_name"]).strip()
        v = str(r["name_kr"]).strip()
        if k and v:
            m[k] = v
    return m


def split_suffixes(name: str) -> tuple[str, list[str]]:
    """접미사를 뒤에서부터 벗겨 (원지표, [접미사 한글]) 로 나눈다."""
    parts: list[str] = []
    cur = name
    changed = True
    while changed:
        changed = False
        for suf, kr in SUFFIX_KR:
            if cur.endswith(suf):
                parts.insert(0, kr)
                cur = cur[: -len(suf)]
                changed = True
                break
    return cur, parts


def macro_label(name: str, nm: dict[str, str]) -> str:
    """거시 변환 변수의 한글 라벨. 원지표를 못 찾으면 빈 문자열."""
    base = name[4:] if name.startswith("NEW_") else name
    root, sufs = split_suffixes(base)
    kr = nm.get(root) or DERIVED_MACRO_KR.get(root, "")
    if not kr:
        return ""
    return " ".join([kr] + sufs)


def interaction_label(term: str, nm: dict[str, str]) -> str:
    """`ix_{거시}__{노출도}` -> "{거시} × {노출도}"."""
    m = re.fullmatch(r"ix_(.+?)__(.+)", term)
    if not m:
        return ""
    macro_part, expo_part = m.group(1), m.group(2)
    # step37.term_name 이 축약한 접미사를 되돌린다
    macro_part = (macro_part.replace("_ret", "_log_ret")
                  .replace("_vol", "_vol_m").replace("_d12", "_diff12"))
    mk = macro_label(macro_part, nm)
    if not mk:
        # yoy 는 축약 시 제거되므로 원지표만 남은 경우가 있다
        mk = nm.get(macro_part) or DERIVED_MACRO_KR.get(macro_part, "")
        if mk and "_" not in macro_part:
            mk = f"{mk} 전년동월대비"
    ek = EXPOSURE_KR.get(expo_part, "")
    if not mk or not ek:
        return ""
    return f"{mk} × {ek}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="backend/feature_labels.py 에 추가한다")
    a = ap.parse_args()

    nm = load_name_map()
    print(f"원천 매핑 {len(nm)}건 로딩: {NAMES_CSV.name}")

    # 대상 1 — cleaned 산출물의 거시 변환 변수 전체
    cleaned = pd.read_csv(config.macro_input_path(), nrows=1)
    macro_cols = [c for c in cleaned.columns if c != "BASE_YM"]

    # 대상 2 — 최종 상호작용 14개
    terms = []
    if SPEC_JSON.exists():
        terms = [r["term"] for r in
                 json.loads(SPEC_JSON.read_text(encoding="utf-8"))["final"]]

    from backend.feature_labels import FEATURE_LABELS

    gen, skipped = {}, []
    for c in macro_cols:
        if c in FEATURE_LABELS:
            continue
        lab = macro_label(c, nm)
        (gen.__setitem__(c, lab) if lab else skipped.append(c))
    for t in terms:
        if t in FEATURE_LABELS:
            continue
        lab = interaction_label(t, nm)
        (gen.__setitem__(t, lab) if lab else skipped.append(t))

    print(f"생성 {len(gen)}건 / 원천에 없어 건너뜀 {len(skipped)}건")
    print()
    print("── 상호작용항 14개 ──")
    for t in terms:
        print(f"  {t:40s} -> {gen.get(t) or FEATURE_LABELS.get(t) or '(라벨 없음)'}")
    print()
    print("── 거시 변환 변수 표본 12건 ──")
    for c in list(gen)[:12]:
        if not c.startswith("ix_"):
            print(f"  {c:40s} -> {gen[c]}")
    if skipped:
        print()
        print(f"── 원천에 없어 라벨을 만들지 않은 것 {len(skipped)}건 (일부) ──")
        for c in skipped[:10]:
            print(f"  {c}")
        print("  ※ 추측하지 않는다. 원본 코드명이 그대로 노출된다.")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"source": NAMES_CSV.name, "n_generated": len(gen),
         "n_skipped": len(skipped), "labels": gen, "skipped": skipped},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"저장: {OUT_JSON.relative_to(_PROJECT_ROOT)}")

    if not a.write:
        print("※ --write 를 주면 backend/feature_labels.py 에 추가한다 (미리보기 모드)")
        return

    s = LABELS_PY.read_text(encoding="utf-8")
    marker = "\n\ndef get_feature_label(code: str) -> str:"
    assert s.count(marker) == 1, "feature_labels.py 구조가 예상과 다르다"
    block = [
        "",
        "# ── [2026-09-03] 거시 변환 변수·상호작용항 라벨 (자동 생성) ──────────────",
        "#   생성기: eda_pipeline/step41_macro_labels.py",
        "#   원천: api_data_processing/config/indicator_names.csv 의 series_name->name_kr",
        "#   ★ 수동 하드코딩하지 않는다. 원천에 없는 지표는 라벨을 만들지 않고",
        "#     원본 코드명을 그대로 노출한다 (JEMU 한 칸 밀림 사고의 교훈).",
        "MACRO_FEATURE_LABELS: dict[str, str] = {",
    ]
    for k in sorted(gen):
        block.append(f'    "{k}": "{gen[k]}",')
    block += ["}", "", "FEATURE_LABELS.update(MACRO_FEATURE_LABELS)"]
    s = s.replace(marker, "\n" + "\n".join(block) + marker)
    LABELS_PY.write_text(s, encoding="utf-8")
    print(f"추가 완료: {LABELS_PY.relative_to(_PROJECT_ROOT)} (+{len(gen)}건)")


if __name__ == "__main__":
    main()
