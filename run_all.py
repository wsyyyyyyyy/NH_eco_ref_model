"""
run_all.py — 전처리부터 D8 학습까지 한 번에 실행한다.

    python run_all.py           # 없는 산출물만 만든다 (있으면 건너뜀)
    python run_all.py --force   # 전부 다시 만든다

출력 위치는 환경변수 NH_OUTPUT_DIR 로 바꿀 수 있다 (미설정 시 eda_pipeline/output).
거시 지표 CSV(api_data_processing/output/model_input/model_input_monthly_cleaned.csv)가
이미 있으면 거시 수집 단계(ECOS·KOSIS API 키 필요)는 자동으로 건너뛴다.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Windows 콘솔이 cp949 여도 한글·기호 출력이 깨지지 않게 UTF-8 로 고정한다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
PY = sys.executable
# 상대 경로가 들어와도 절대경로로 고정한다 (하위 단계의 Path.relative_to 가 깨지지 않게).
OUT = Path(os.environ.get("NH_OUTPUT_DIR", str(ROOT / "eda_pipeline" / "output"))).resolve()
MACRO_CSV = ROOT / "api_data_processing" / "output" / "model_input" / "model_input_monthly_cleaned.csv"

#: (표시명, 산출물(OUT 기준 상대경로), 최소 바이트, 실행 커맨드)
STEPS = [
    ("1-3  원천 적재 → 통합 패널 → EDA",
     "nh_panel_full_obv.parquet", 1_000_000,
     [PY, "-m", "eda_pipeline.run", "--output-dir", str(OUT)]),
    ("5    패널 전처리 (sentinel·결측·파생)",
     "nh_panel_prep_obv_none.parquet", 1_000_000,
     [PY, "-m", "eda_pipeline.step5_panel_prep", "--spine", "obv", "--segment", "none"]),
    ("6    거시경제 결합 (상호작용 14 + 축소 178→89)",
     "nh_panel_macro_12m_obv_none_real.parquet", 1_000_000,
     [PY, "-m", "eda_pipeline.step6_macro_integration",
      "--spine", "obv", "--segment", "none", "--tag", "real"]),
    ("37   거시 상호작용 명세 생성 (4구간 부호 검사 → 14항)",
     "validation/macro_interaction_candidates.json", 1_000,
     [PY, "-m", "eda_pipeline.step37_macro_interactions"]),
    ("38   D8 프로덕션 재학습 (시드 3회)",
     "lgbm_v2_full.txt", 100_000,
     [PY, "-m", "eda_pipeline.step38_production_retrain"]),
]


def _ok(path: Path, min_bytes: int) -> bool:
    """산출물이 존재하고 최소 크기를 넘으면 True. 0바이트·손상은 False."""
    try:
        return path.is_file() and path.stat().st_size >= min_bytes
    except OSError:
        return False


def _run(cmd: list[str]) -> int:
    env = dict(os.environ)
    env["NH_OUTPUT_DIR"] = str(OUT)
    env.setdefault("PYTHONPATH", str(ROOT))
    env["PYTHONUTF8"] = "1"                 # 하위 단계 로그(한글·—)도 UTF-8 로
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, cwd=str(ROOT), env=env).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="산출물이 있어도 다시 만든다")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[run_all] 출력 위치 : {OUT}")
    print(f"[run_all] 거시 CSV  : {'있음 (거시 수집 건너뜀)' if MACRO_CSV.is_file() else '없음'}")
    if not MACRO_CSV.is_file():
        print("[run_all] ★ 거시 지표 CSV 가 없습니다. 아래 중 하나가 필요합니다:")
        print("          - 저장소에 포함된 model_input_monthly_cleaned.csv 를 확인하십시오, 또는")
        print("          - ECOS_API_KEY / KOSIS_API_KEY 를 .env 에 넣고 먼저 실행:")
        print("            python -m api_data_processing.main --target-freq M")
        print("            python -m api_data_processing.impute_data")
        return 2

    t_all = time.time()
    for name, out_rel, min_bytes, cmd in STEPS:
        target = OUT / out_rel
        if not a.force and _ok(target, min_bytes):
            print(f"[건너뜀]  step {name}  ({out_rel} 존재, {target.stat().st_size:,} bytes)")
            continue
        print(f"\n[시작]    step {name}")
        t0 = time.time()
        rc = _run(cmd)
        dt = time.time() - t0
        if rc != 0:
            print(f"[실패]    step {name}  — 종료코드 {rc}, {dt:.0f}초 경과. 여기서 중단합니다.")
            return rc
        if not _ok(target, min_bytes):
            print(f"[실패]    step {name}  — 명령은 끝났으나 산출물이 없거나 너무 작습니다: {target}")
            return 1
        print(f"[완료]    step {name}  — {dt:.0f}초 / {target.stat().st_size:,} bytes")

    print(f"\n[run_all] 전체 완료 — {time.time() - t_all:.0f}초")
    print(f"[run_all] 재현 검증:  python verify_reproduction.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
