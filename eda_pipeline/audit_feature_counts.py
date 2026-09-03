"""저장된 A/B/C축 결과의 피처 수를 시나리오 명세와 대조한다.

--seed-probe 가 되넣기 컬럼을 조인하지 않아 "A0 + 누수 N개" 시나리오가
A0 와 같은 피처로 돌아간 결함(2026-09-02 발견)의 영향 범위를 잰다.

★ 세대가 다른 파일을 오늘의 피처 수와 비교하면 안 된다. 패널 컬럼이 달라
  A0 자체가 다르다. 그래서 **각 파일 안의 A0 를 그 파일의 기준선으로 삼아**
  기대 피처 수를 계산한다. 자기정합적 검사다.

  기대(A_x) = n_features(A0) + |add| - |drop|
  단 __SENTINEL__ 드롭은 개수가 가변이므로 판정에서 제외하고 표시만 한다.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

from eda_pipeline.step30_stage6_ablation import SCENARIOS  # noqa: E402

DIR = PROJ / "eda_pipeline" / "output" / "validation" / "stage6_ablation"


def expected(sc: str, n_a0: int) -> tuple[int | None, str]:
    """A0 대비 기대 피처 수. 가변 드롭이 있으면 (None, 사유)."""
    spec = SCENARIOS.get(sc)
    if spec is None:
        return None, "시나리오 미정의"
    if "__SENTINEL__" in spec["drop"]:
        return None, "센티넬 가변 드롭"
    return n_a0 + len(spec["add"]) - len(spec["drop"]), ""


def main() -> None:
    rows = []
    for f in sorted(glob.glob(str(DIR / "*.json"))):
        name = os.path.basename(f)
        try:
            rs = json.load(open(f, encoding="utf-8"))
        except Exception as exc:                                  # noqa: BLE001
            print(f"  {name}: 읽기 실패 {exc}")
            continue
        if not isinstance(rs, list) or not rs:
            continue
        # 이 파일의 A0 기준선
        a0s = {r["n_features"] for r in rs
               if (r.get("scenario") or r.get("variant")) == "A0"}
        n_a0 = sorted(a0s)[0] if a0s else None
        for r in rs:
            sc = r.get("scenario") or r.get("variant")
            nf = r.get("n_features")
            exp, why = (None, "A0 기준선 없음") if n_a0 is None else expected(sc, n_a0)
            # ★ 저장된 desc 와 현재 정의를 대조한다. 다르면 피처 수 불일치의 원인이
            #   조인 누락이 아니라 **시나리오 정의 변경**일 수 있다. 둘을 섞으면
            #   구세대 기록을 조인 결함으로 오진한다 (2026-09-02 실제로 겪었다).
            now_desc = SCENARIOS.get(sc, {}).get("desc")
            then_desc = r.get("desc")
            rows.append(dict(file=name, scenario=sc, seed=r.get("seed"),
                             n_features=nf, n_a0=n_a0, expected=exp, why=why,
                             add=len(SCENARIOS.get(sc, {}).get("add", [])),
                             drop=len(SCENARIOS.get(sc, {}).get("drop", [])),
                             auc=r.get("valid", {}).get("auc"),
                             desc_changed=(then_desc is not None
                                           and now_desc is not None
                                           and then_desc != now_desc),
                             then_desc=then_desc, now_desc=now_desc))

    print("=" * 108)
    print("저장된 결과의 피처 수 대조 — 기대 = 그 파일의 A0 피처수 + add − drop")
    print("=" * 108)
    print(f"{'파일':40s} {'시나': <6s} {'시드':>5s} {'실제':>5s} {'A0':>4s} "
          f"{'add':>4s} {'drop':>5s} {'기대':>5s}  판정")
    print("-" * 108)
    bad, unknown = [], []
    for r in rows:
        seed = "" if r["seed"] is None else str(r["seed"])
        if r["expected"] is None:
            verdict = f"판정보류 ({r['why']})"
            unknown.append(r)
            exp_s = "—"
        elif r["n_features"] == r["expected"]:
            verdict = "일치"
            exp_s = str(r["expected"])
        else:
            gap = r["n_features"] - r["expected"]
            if r["desc_changed"]:
                verdict = f"불일치 {gap:+d} — **정의 변경분**"
            else:
                verdict = f"*** 불일치 {gap:+d} ***"
                bad.append(r)
            exp_s = str(r["expected"])
        print(f"{r['file']:40s} {str(r['scenario']):<6s} {seed:>5s} "
              f"{str(r['n_features']):>5s} {str(r['n_a0']):>4s} "
              f"{r['add']:>4d} {r['drop']:>5d} {exp_s:>5s}  {verdict}")

    print("-" * 108)
    drift = [r for r in rows if r["desc_changed"]]
    print(f"총 {len(rows)}건 / **조인 누락 의심 {len(bad)}건** / "
          f"정의 변경분 {len(drift)}건 / 판정보류 {len(unknown)}건")
    if drift:
        print()
        print("── 시나리오 정의가 바뀐 기록 — 저장값을 현재 설명으로 읽으면 오독한다 ──")
        seen = set()
        for r in drift:
            k = (r["scenario"], r["then_desc"])
            if k in seen:
                continue
            seen.add(k)
            print(f"  {r['scenario']:4s} [{r['file']}]")
            print(f"       당시: {r['then_desc']}")
            print(f"       현재: {r['now_desc']}")
    if bad:
        print()
        print("★ 불일치 상세 — 되넣기가 반영되지 않았을 가능성")
        print(f"  {'파일':40s} {'시나':<6s} {'실제':>5s} {'기대':>5s} {'AUC':>8s}")
        for r in bad:
            auc = "—" if r["auc"] is None else f"{r['auc']:.4f}"
            print(f"  {r['file']:40s} {str(r['scenario']):<6s} "
                  f"{r['n_features']:>5d} {r['expected']:>5d} {auc:>8s}")
        print()
        print("  ※ 실제 == A0 피처수 이고 add > 0 이면 조인 누락의 전형이다.")
        for r in bad:
            if r["n_features"] == r["n_a0"] and r["add"] > 0:
                print(f"    - {r['file']} {r['scenario']}: 실제 {r['n_features']} "
                      f"== A0 {r['n_a0']} 인데 add {r['add']}개 → **조인 누락 의심**")


if __name__ == "__main__":
    main()
