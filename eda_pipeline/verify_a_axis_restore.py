"""복원된 A축 원자료를 확정판 md 표와 전수 대조하고, gain 상위 15개를 뽑는다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

JSON = PROJ / "eda_pipeline/output/validation/stage6_ablation/ablation_A_results_R2.json"
OUT = PROJ / "eda_pipeline/output/validation/stage6_ablation/A_axis_gain_top15.json"

# 확정판 md §1 표 (수기 전사). (피처, best_iter, Train, Dev, Valid, KS, PSI)
MD = {
    "A0":  (152, 4813, 0.9982, 0.9700, 0.8434, 0.5307, 0.0167),
    "A7":  (162, 3493, 0.9988, 0.9879, 0.9398, 0.7387, 0.0419),
    "A3":  (154, 3823, 0.9989, 0.9873, 0.9217, 0.7013, 0.0432),
    "A0c": (150, 6454, 0.9987, 0.9522, 0.7826, 0.4169, 0.0252),
    "A4":  (153, 4766, 0.9990, 0.9715, 0.8863, 0.5973, 0.0371),
    "A2":  (156, 4916, 0.9986, 0.9695, 0.8796, 0.6078, 0.0167),
    "A1":  (153, 4215, 0.9980, 0.9682, 0.8580, 0.5520, 0.0307),
    "C1":  (151, 4103, 0.9963, 0.9708, 0.8595, 0.5552, 0.0312),
    "C5":  (114, 5572, 0.9981, 0.9726, 0.8560, 0.5498, 0.0261),
    "A5":  (151, 4926, 0.9981, 0.9669, 0.8336, 0.5090, 0.0228),
    "C4":  (150, 6276, 0.9985, 0.9742, 0.8512, 0.5505, 0.0262),
    "C0":  (150, 6130, 0.9984, 0.9738, 0.8509, 0.5483, 0.0287),
    # 판정 불가 표 (Valid 만 기재돼 있다)
    "A6":  (151, None, None, None, 0.8465, None, None),
    "A8":  (116, None, None, None, 0.8452, None, None),
    "C2":  (151, None, None, None, 0.8431, None, None),
}

rs = {r["scenario"]: r for r in json.loads(JSON.read_text(encoding="utf-8"))}

print("=" * 104)
print("복원값 vs 확정판 md 표 — 전수 대조")
print("=" * 104)
print(f"{'ID':5s} {'피처(md/복원)':>14s} {'best_iter':>16s} {'Valid(md/복원)':>18s} "
      f"{'ΔValid':>9s} {'KS':>16s}  판정")
print("-" * 104)

diffs = []
for sc, (nf, bi, tr, dv, va, ks, psi) in MD.items():
    r = rs.get(sc)
    if r is None:
        print(f"{sc:5s} 복원 결과에 없음")
        continue
    g_nf, g_bi = r["n_features"], r["best_iteration"]
    g_va, g_ks = r["valid"]["auc"], r["valid"]["ks"]
    d_va = g_va - va
    ok_nf = g_nf == nf
    ok_bi = (bi is None) or (g_bi == bi)
    ok_va = abs(d_va) < 5e-5           # md 는 4자리 반올림
    ok_ks = (ks is None) or abs(g_ks - ks) < 5e-5
    verdict = "일치" if (ok_nf and ok_bi and ok_va and ok_ks) else "*** 불일치 ***"
    if verdict != "일치":
        diffs.append((sc, nf, g_nf, bi, g_bi, va, g_va, ks, g_ks))
    print(f"{sc:5s} {nf:6d}/{g_nf:<7d} "
          f"{('—' if bi is None else str(bi)):>7s}/{g_bi:<8d} "
          f"{va:.4f}/{g_va:.4f} {d_va:+9.5f} "
          f"{('—' if ks is None else f'{ks:.4f}'):>7s}/{g_ks:.4f}  {verdict}")

print("-" * 104)
print(f"대조 {len(MD)}건 / 불일치 {len(diffs)}건")
if diffs:
    print()
    print("★ 불일치 상세 — 재현값을 정본으로 하고 차이를 기록한다")
    for sc, nf, g_nf, bi, g_bi, va, g_va, ks, g_ks in diffs:
        print(f"  {sc}: 피처 md {nf} / 복원 {g_nf} | best_iter md {bi} / 복원 {g_bi} | "
              f"Valid md {va:.4f} / 복원 {g_va:.4f} ({g_va - va:+.5f}) | "
              f"KS md {ks} / 복원 {g_ks:.4f}")

# ── gain 상위 15 확보 ────────────────────────────────────────
print()
print("=" * 104)
print("gain 상위 15 — A0~A7 (04_누수_발견과_제거 근거)")
print("=" * 104)
dump = {}
for sc in ("A0", "A0c", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
           "C0", "C1", "C2", "C3", "C4", "C5"):
    r = rs.get(sc)
    if r is None:
        continue
    top = r.get("gain_top15") or r.get("gain_top20") or []
    dump[sc] = [{"rank": i + 1, "feature": e["feature"],
                 "gain_pct": e["gain_pct"]} for i, e in enumerate(top[:15])]
for sc in ("A0", "A2", "A3", "A7"):
    if sc not in dump:
        continue
    print(f"\n[{sc}]  Valid AUC {rs[sc]['valid']['auc']:.4f}")
    for e in dump[sc][:15]:
        print(f"   {e['rank']:3d}위 {e['feature']:34s} {e['gain_pct']:7.3f}%")

OUT.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
print()
print(f"저장: {OUT.relative_to(PROJ)}  ({len(dump)}개 시나리오)")

# ── 제안 58 — 중요도 아티팩트 분리 (확정판 기준) ──────────────────
# 산출식은 구세대 값으로 역산 검증했다:
#   CG01  (A4-A0)/(A3-A0) = 43.7%   (구세대 A0=0.7826)
#   C302  (A6-A0)/(A5-A0) = 85.8%   (당시 A5/A6 는 ADD 시나리오)
# 확정판은 C302 가 A0 에 편입돼 있으므로 "둘 다 없음" 기준선이 A0c 다.
print()
print("=" * 104)
print("제안 58 — 중요도 아티팩트 분리 (확정판 기준)")
print("=" * 104)


def _auc(k: str) -> float:
    return rs[k]["valid"]["auc"]


if all(k in rs for k in ("A0c", "A0", "A3", "A4", "A5", "A6")):
    tot_cg = _auc("A3") - _auc("A0")
    part_cg = _auc("A4") - _auc("A0")
    tot_c = _auc("A0") - _auc("A0c")
    miss = _auc("A5") - _auc("A0c")
    ordv = _auc("A6") - _auc("A0c")
    print(f"  CG01 총효과       A3-A0  = {tot_cg:+.5f}")
    print(f"  CG01 이력유무 단독 A4-A0  = {part_cg:+.5f}  -> {part_cg / tot_cg * 100:.1f}%")
    print(f"  C302 총효과       A0-A0c = {tot_c:+.5f}")
    print(f"  C302 이력유무 단독 A5-A0c = {miss:+.5f}  -> {miss / tot_c * 100:.1f}%")
    print(f"  C302 등급서열 단독 A6-A0c = {ordv:+.5f}  -> {ordv / tot_c * 100:.1f}%")
    print(f"  합 = {(miss + ordv) / tot_c * 100:.1f}%  (100% 초과 = 대체재 관계)")
    print()
    print("  ★ 시드 1회 측정이다. 통합 sigma ~ 0.0014 가 분자·분모에 모두 걸린다.")
    print("    비율을 소수점 한 자리로 단정하지 말 것.")
else:
    print("  기준선(A0c/A0) 또는 A3~A6 가 없어 산출을 건너뜀")
