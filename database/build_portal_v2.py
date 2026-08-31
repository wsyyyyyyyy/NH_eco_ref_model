"""
database/build_portal_v2.py
===========================
STAGE 6 선행작업 1 — 신 스키마 DuckDB(`portal_v2.duckdb`) 빌드.

지켜야 할 것 (사용자 지시):
  - `portal.duckdb`(구) 가 존재한다면 절대 덮어쓰거나 수정하지 않는다.
    config.assert_db_writable('legacy') 가 예외를 던져 물리적으로 막는다.
  - `portal_v2.duckdb` 는 새로 생성한다. 기존 파일이 있으면 삭제하지 않고
    타임스탬프 접미사를 붙여 옆으로 치운 뒤 보고한다.
  - 빌드 후 아래를 출력한다.
      행수 / 컬럼 수 / 신규 컬럼 목록
      IS_BUDO_12M 양성 수 및 부도율
      (V_BZNO, BASE_YM) 중복 = 0 확인

원천은 STAGE 5 산출 패널(Parquet)이다. DuckDB 가 Parquet 을 직접 읽으므로
2.5GB CSV 를 pandas 로 올리지 않는다.

Usage
-----
    python -m database.build_portal_v2
    python -m database.build_portal_v2 --source eda_pipeline/output/<panel>.parquet
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb

from eda_pipeline import config

# 신 스키마 패널 기본값. STAGE 5(step6_macro_integration) 최종 산출물.
DEFAULT_SOURCE = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none.parquet"

KEY_COLS = ("V_BZNO", "BASE_YM")
TARGET = "IS_BUDO_12M"


def _lit(p: Path) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def _legacy_panel_columns() -> list[str]:
    """구 스키마 컬럼 목록. '신규 컬럼' 판정 기준선이다.

    구 DB(portal.duckdb) 가 있으면 그 테이블 스키마를, 없으면 legacy 패널 CSV
    헤더를 쓴다. 둘 다 없으면 빈 목록을 반환하고 신규 판정을 생략한다.
    """
    if config.DB_PATH_LEGACY.exists():
        con = duckdb.connect(str(config.DB_PATH_LEGACY), read_only=True)
        try:
            return con.execute(
                f"SELECT * FROM {config.PANEL_TABLE} LIMIT 0").df().columns.tolist()
        finally:
            con.close()
    lp = config.panel_path("legacy")
    if lp.exists():
        with open(lp, encoding="utf-8-sig", newline="") as f:
            return next(csv.reader(f))
    return []


def _rotate_existing(target: Path) -> Path | None:
    """기존 portal_v2.duckdb 를 삭제하지 않고 타임스탬프 접미사로 치운다."""
    if not target.exists():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = target.with_name(f"{target.stem}_{stamp}{target.suffix}")
    shutil.move(str(target), str(moved))
    return moved


def build(source: Path, with_branch: bool = True) -> Path:
    # 구 DB 쓰기 시도를 물리적으로 차단. 이 스크립트는 v2 만 쓴다.
    target = config.assert_db_writable("v2")
    target.parent.mkdir(parents=True, exist_ok=True)

    if not source.exists():
        raise FileNotFoundError(
            f"{source} 없음. STAGE 5(step6_macro_integration) 를 먼저 실행할 것.")

    print("=" * 78)
    print("portal_v2.duckdb 재빌드")
    print("=" * 78)
    print(f"  원천 : {source.name}  ({source.stat().st_size / 1e6:,.0f} MB)")
    print(f"  대상 : {target}")
    print(f"  구 DB: {config.DB_PATH_LEGACY.name} "
          f"exists={config.DB_PATH_LEGACY.exists()} — 건드리지 않음")

    moved = _rotate_existing(target)
    if moved:
        print(f"  ! 기존 {target.name} 이 있었다. 삭제하지 않고 옮김 -> {moved.name}")

    con = duckdb.connect(str(target))
    try:
        con.execute(
            f"CREATE TABLE {config.PANEL_TABLE} AS "
            f"SELECT * FROM read_parquet({_lit(source)})")

        if with_branch:
            # 포털 데모용 가상 지점. 구 init_duckdb.py 와 동일한 결정적 해시 규칙.
            con.execute(f"ALTER TABLE {config.PANEL_TABLE} ADD COLUMN V_BRANCH_CODE VARCHAR")
            con.execute(
                f"UPDATE {config.PANEL_TABLE} "
                f"SET V_BRANCH_CODE = 'VB00' || ((hash(V_BZNO::VARCHAR) % 5) + 1)::VARCHAR")

        for col, idx in (("V_BZNO", "idx_v2_bzno"), ("BASE_YM", "idx_v2_baseym"),
                         (TARGET, "idx_v2_budo")):
            con.execute(f"CREATE INDEX {idx} ON {config.PANEL_TABLE}({col})")

        report(con, source)
    finally:
        con.close()
    return target


def report(con, source: Path) -> None:
    t = config.PANEL_TABLE
    cols = con.execute(f"SELECT * FROM {t} LIMIT 0").df().columns.tolist()
    rows = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    print("\n" + "-" * 78)
    print("[재빌드 결과]")
    print("-" * 78)
    print(f"  행수      : {rows:,}")
    print(f"  컬럼 수   : {len(cols):,}")

    legacy = _legacy_panel_columns()
    if legacy:
        base = set(legacy)
        new = [c for c in cols if c not in base]
        print(f"\n  신규 컬럼 : {len(new):,}개 (기준선: 구 스키마 {len(legacy)}개 컬럼)")
        # 지시서가 명시적으로 확인을 요구한 컬럼
        for probe in ("JEMU_191506_val", "JEMU_191502_val", "JEMU_191505_val",
                      "JEMU_191204_val", "JEMU_191207_val", "JEMU_191208_val",
                      "JEMU_debt_ratio", "JEMU_current_ratio",
                      "CG01_MISSING_YN", "C302_MISSING_YN", "JEMU_MISSING_YN"):
            print(f"    {probe:24s} {'있음' if probe in cols else '없음'}")
        print("\n    신규 컬럼 전체 목록:")
        for i in range(0, len(new), 4):
            print("      " + "  ".join(f"{c:32s}" for c in new[i:i + 4]).rstrip())
    else:
        print("\n  신규 컬럼 : 판정 생략 (구 스키마 기준선 없음)")

    pos, tot = con.execute(
        f"SELECT SUM(CAST({TARGET} AS BIGINT)), COUNT({TARGET}) FROM {t}").fetchone()
    print(f"\n  {TARGET} 양성 : {int(pos):,} / {int(tot):,}  = {pos / tot:.4%}")
    firms = con.execute(
        f"SELECT COUNT(DISTINCT V_BZNO) FROM {t} WHERE {TARGET} = 1").fetchone()[0]
    print(f"  {TARGET} 기여기업 : {firms:,}")

    dup = con.execute(
        f"SELECT COUNT(*) FROM (SELECT {', '.join(KEY_COLS)}, COUNT(*) c "
        f"FROM {t} GROUP BY ALL HAVING c > 1)").fetchone()[0]
    verdict = "OK" if dup == 0 else "실패"
    print(f"\n  ({', '.join(KEY_COLS)}) 중복 그룹 : {dup:,}  -> {verdict}")
    if dup:
        raise AssertionError(f"키 중복 {dup}건. 패널 생성 단계로 돌아갈 것.")

    ym = con.execute(f"SELECT MIN(BASE_YM), MAX(BASE_YM), COUNT(DISTINCT BASE_YM) FROM {t}").fetchone()
    print(f"  BASE_YM 범위 : {ym[0]} ~ {ym[1]}  ({ym[2]}개월)")
    split = con.execute(f"SELECT SPLIT, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1").fetchall()
    print(f"  SPLIT 분포   : {dict(split)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--no-branch", action="store_true")
    a = ap.parse_args()
    out = build(Path(a.source), with_branch=not a.no_branch)
    print(f"\n완료: {out}")
