"""
======================================================================
EDA Pipeline — 공통 설정
======================================================================
경로와 스파인 모드를 한 곳에서 관리합니다.
하드코딩된 절대경로를 쓰지 않고 프로젝트 루트를 __file__ 기준으로 해석합니다.

사용법:
    from eda_pipeline.config import OUTPUT_DIR, SPINE_MODE, panel_path
    df = pd.read_csv(panel_path())            # 현재 SPINE_MODE의 패널
    df = pd.read_csv(panel_path("legacy"))    # S0 베이스라인 패널
"""

from __future__ import annotations

import os
from pathlib import Path

# ── 경로 ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "eda_pipeline" / "output"
INPUT_DIR = PROJECT_ROOT / "input"
#: 이전 세대 산출물 보관 폴더 (누수 모델·구세대 패널 등). 인용 금지. `_archive/README.md` 참조.
ARCHIVE_DIR = PROJECT_ROOT / "_archive"

# ── 스파인 모드 ──────────────────────────────────────────────────────
#   obv    : VH_OBV_DTL 레코드가 있는 (기업, 월)만 = 당행 여신 보유 차주 (신규 기본)
#   full   : UPCHE 전체 × 캘린더 크로스조인 (기존 동작, 비교용)
#   legacy : 리팩터링 이전에 생성된 원본 패널. 읽기 전용이며 쓰기 금지.
SPINE_MODE = os.getenv("SPINE_MODE", "obv")

# ── 공시지연(개월) ──────────────────────────────────────────────────
#   JEMU : 재무제표. 법인세 신고기한(3월 말) 직후 유통되며 NICE CRI 등급적용시작일이
#          3년 연속 4월 최다 집중 (2023년 36.5% / 2024년 34.6% / 2025년 43.1%).
PUB_LAG_MONTHS = int(os.getenv("PUB_LAG_MONTHS", "4"))
#   AA17 : 생산·판매 분기실적. 분기 마지막 날 실적이 그 달 안에 은행 시스템에
#          들어와 있을 수 없으므로 최소 1개월을 둔다 (2021Q1 -> 202104).
#          STAGE 6에서 LAG=1 / LAG=3 두 버전의 AUC 차이를 측정한다.
AA17_PUB_LAG = int(os.getenv("AA17_PUB_LAG", "1"))

# ── 저장 포맷 ────────────────────────────────────────────────────────
# 패널 산출물은 Parquet 으로 저장한다.
#   1) 타입이 파일에 저장되므로 sentinel / NaN / 0 구분이 CSV 재파싱으로 뭉개지지 않는다.
#      STAGE 4에서 구분한 값들을 지키는 것이 용량보다 중요한 이유다.
#   2) 2.4GB CSV 가 수백 MB 로 줄어 STAGE 6 의 여러 시나리오를 감당할 수 있다.
#   3) DuckDB 가 Parquet 을 직접 쿼리할 수 있어 portal.duckdb 재빌드에도 유리하다.
# 사람이 확인할 용도로는 SAMPLE_ROWS 행짜리 CSV 를 함께 남긴다.
PANEL_FORMAT = os.getenv("PANEL_FORMAT", "parquet")   # parquet | csv
SAMPLE_ROWS = 10_000


def _swap_ext(path: Path, fmt: str | None = None) -> Path:
    return path.with_suffix(".parquet" if (fmt or PANEL_FORMAT) == "parquet" else ".csv")


def _sql_lit(p: Path) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def save_panel(df, path, sample: bool = True) -> Path:
    """패널을 PANEL_FORMAT 으로 저장하고 실제 경로를 반환한다.

    Parquet 엔진은 DuckDB 를 쓴다. pyarrow / fastparquet 의존성을 추가하지 않기 위해서다
    (DuckDB 는 이미 backend 가 쓰고 있다). 엔진이 없으면 CSV 로 자동 폴백한다.
    """
    out = _swap_ext(Path(path))
    if out.suffix == ".parquet":
        try:
            import duckdb
            con = duckdb.connect()
            con.register("_panel_out", df)
            con.execute(f"COPY _panel_out TO {_sql_lit(out)} (FORMAT PARQUET)")
            con.close()
        except Exception:
            out = _swap_ext(Path(path), "csv")
            df.to_csv(out, index=False, encoding="utf-8-sig")
            return out
        if sample and len(df) > SAMPLE_ROWS:
            df.head(SAMPLE_ROWS).to_csv(
                out.with_name(out.stem + f"_sample{SAMPLE_ROWS}.csv"),
                index=False, encoding="utf-8-sig")
    else:
        df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def read_panel(path, **kw):
    """PANEL_FORMAT 우선으로 읽되, 없으면 다른 포맷으로 폴백한다."""
    import pandas as pd
    p = Path(path)
    for cand in (_swap_ext(p), _swap_ext(p, "parquet"), _swap_ext(p, "csv")):
        if not cand.exists():
            continue
        if cand.suffix == ".parquet":
            import duckdb
            cols = kw.get("usecols")
            sel = ", ".join(f'"{c}"' for c in cols) if cols else "*"
            con = duckdb.connect()
            df = con.execute(f"SELECT {sel} FROM read_parquet({_sql_lit(cand)})").df()
            con.close()
            return restore_categories(df)
        return restore_categories(pd.read_csv(cand, **kw))
    raise FileNotFoundError(f"{p} (.parquet/.csv 모두 없음)")


CATEGORY_MAP_FILE = "categorical_levels_v2.json"


def restore_categories(df):
    """저장된 카테고리 매핑을 다시 적용한다.

    DuckDB 의 Parquet 왕복은 category dtype 을 VARCHAR 로 되돌린다.
    카테고리 순서가 Train / Valid 에서 달라지면 조용히 잘못 학습되므로
    step6 이 남긴 categorical_levels_v2.json 의 순서를 그대로 복원한다.
    """
    import json
    import pandas as pd
    f = OUTPUT_DIR / CATEGORY_MAP_FILE
    if not f.exists():
        return df
    try:
        levels = json.loads(f.read_text(encoding="utf-8")).get("levels", {})
    except Exception:
        return df
    for c, cats in levels.items():
        if c in df.columns and str(df[c].dtype) != "category":
            df[c] = pd.Categorical(df[c], categories=cats)
    return df


# ── 단위 보정 ────────────────────────────────────────────────────────
# AA17(생산판매)은 천원 단위, JEMU(재무) / AC12(외화부채)는 원 단위다.
# 두 테이블을 함께 쓰는 파생변수를 만들 때 AA17 값에 이 값을 곱해 원 단위로 맞춘다.
#   실측 근거: AA17 Q4 / JEMU 매출액 비율 중앙값 = 0.0010
AA17_UNIT_SCALE = 1000

# jemu_sentinel 이 Train 구간에서 상수로 판정해 제거한 컬럼 목록
JEMU_CONSTANT_COLS_FILE = "jemu_constant_cols.json"

PANEL_FILE = {
    "obv":    "nh_panel_full_obv.csv",
    "full":   "nh_panel_full_spineFULL.csv",
    "legacy": "nh_panel_full.csv",      # 읽기 전용. STAGE 6 S0 베이스라인. _archive/legacy_panels/ 로 이동됨.
}

#: legacy 패널은 정리(Group E)에서 `_archive/legacy_panels/` 로 이동했다.
#: obv/full 은 `OUTPUT_DIR` 에 그대로 있다.
_PANEL_DIR = {"legacy": ARCHIVE_DIR / "legacy_panels"}

# legacy 패널은 절대 덮어쓰지 않는다.
READ_ONLY_MODES = frozenset({"legacy"})


# 부도 이벤트 원천 테이블.
# 스파인과 무관하게 전체 부도 이벤트를 담는다. STAGE 3의 12개월 라벨 생성에
# 이 파일을 쓴다. 스파인은 '관측시점 후보'만 정의하고 부도 이벤트를 제한하지 않는다.
BUDO_EVENTS_FILE = "budo_events.csv"


BUDO_EVENTS_META_FILE = "budo_events_meta.json"
# 부도 원천 파일명 키워드 (step1_load.FILE_KEYS 의 BUDO_CUST 와 동일)
BUDO_SOURCE_KEYWORD = "BUDO_CUST"


# 거시경제 지표 월별 데이터. .gitignore(*.csv)로 제외되어 체크아웃에 없을 수 있다.
MACRO_INPUT_FILE = "model_input_monthly_cleaned.csv"


def macro_input_path() -> Path:
    return PROJECT_ROOT / "api_data_processing" / "output" / "model_input" / MACRO_INPUT_FILE


def budo_events_path() -> Path:
    return OUTPUT_DIR / BUDO_EVENTS_FILE


def budo_events_meta_path() -> Path:
    return OUTPUT_DIR / BUDO_EVENTS_META_FILE


def jemu_constant_cols_path() -> Path:
    return OUTPUT_DIR / JEMU_CONSTANT_COLS_FILE


def budo_source_path() -> Path | None:
    """input/ 의 부도 원천 TXT 경로. 없으면 None."""
    hits = sorted(INPUT_DIR.glob(f"*{BUDO_SOURCE_KEYWORD}*.txt"))
    return hits[0] if hits else None


def panel_path(mode: str | None = None) -> Path:
    """모드에 대응하는 패널 파일 경로를 반환합니다.

    legacy(STAGE 6 S0 베이스라인)는 Group E 정리에서 `_archive/legacy_panels/` 로
    옮겼습니다. 그 파일이 없으면 `SPINE_MODE=legacy` 로 도는 A~D축 ablation 재현이
    불가능하므로, 여기서 존재 여부를 확인해 명확한 예외를 던집니다.
    """
    m = mode or SPINE_MODE
    if m not in PANEL_FILE:
        raise ValueError(f"알 수 없는 SPINE_MODE: {m!r} (가능: {sorted(PANEL_FILE)})")
    base = _PANEL_DIR.get(m, OUTPUT_DIR)
    p = base / PANEL_FILE[m]
    if m == "legacy" and not p.exists() and not _swap_ext(p).exists():
        raise FileNotFoundError(
            f"legacy 베이스라인 패널이 없습니다: {p}\n"
            f"  이 파일은 _archive/legacy_panels/ 에 보관되며 git 추적 대상이 아닙니다"
            f"(.gitignore: *.csv).\n"
            f"  재생성: `python -m eda_pipeline.run` (step1~2) 후 산출물을 위 경로로 이동.\n"
            f"  legacy 스파인이 필요 없는 경우 SPINE_MODE=obv 를 쓰십시오."
        )
    return p


def split_paths(mode: str | None = None) -> tuple[Path, Path]:
    """TRAIN / VALID 분리 저장 경로를 반환합니다."""
    m = mode or SPINE_MODE
    stem = Path(PANEL_FILE[m]).stem.replace("nh_panel_full", "nh_panel")
    return OUTPUT_DIR / f"{stem}_train.csv", OUTPUT_DIR / f"{stem}_valid.csv"


def assert_writable(mode: str | None = None) -> str:
    """쓰기 금지 모드면 예외를 발생시킵니다."""
    m = mode or SPINE_MODE
    if m not in PANEL_FILE:
        raise ValueError(f"알 수 없는 SPINE_MODE: {m!r} (가능: {sorted(PANEL_FILE)})")
    if m in READ_ONLY_MODES:
        raise PermissionError(
            f"SPINE_MODE={m!r} 은 읽기 전용입니다. "
            f"{PANEL_FILE[m]} 는 STAGE 6 S0 베이스라인이므로 덮어쓸 수 없습니다."
        )
    return m


# ══════════════════════════════════════════════════════════════════════
# DuckDB — 구/신 스키마 병존
# ══════════════════════════════════════════════════════════════════════
# portal.duckdb 와 portal_v2.duckdb 는 "교체" 관계가 아니라 "병존" 관계다.
#   S0 (기존 파이프라인 재현) 은 구 스키마 데이터로 평가해야 하고,
#   S1~S9 는 신 스키마다. 시나리오가 DB 를 고른다.
# 연결은 예외 없이 read_only=True 다. 두 파일 모두 재빌드 스크립트 밖에서는
# 절대 쓰지 않는다.
DB_DIR = PROJECT_ROOT / "database"

DB_FILE = {
    "legacy": "portal.duckdb",     # 구 스키마. 읽기 전용. S0 전용.
    "v2":     "portal_v2.duckdb",  # 신 스키마. STAGE 6 기본.
}

DB_PATH_LEGACY = DB_DIR / DB_FILE["legacy"]
DB_PATH_V2 = DB_DIR / DB_FILE["v2"]
DB_PATH = DB_PATH_V2               # 기본값

# 패널 테이블명 (두 DB 공통)
PANEL_TABLE = "corporate_panel"

# 검증/실험 산출물
VALIDATION_DIR = OUTPUT_DIR / "validation"
ABLATION_DIR = VALIDATION_DIR / "stage6_ablation"


def db_path(which: str = "v2") -> Path:
    """'legacy' | 'v2' 에 대응하는 DuckDB 경로를 반환한다 (존재 여부는 보지 않음)."""
    if which not in DB_FILE:
        raise ValueError(f"알 수 없는 DB 스키마: {which!r} (가능: {sorted(DB_FILE)})")
    return DB_DIR / DB_FILE[which]


def require_db(which: str = "v2") -> Path:
    """DB 파일이 실제로 있을 때만 경로를 반환한다. 없으면 예외.

    조용한 폴백을 하지 않는다. 구 DB 가 없을 때 신 DB 로 대신 붙으면
    S0(구 스키마 재현) 이 S1 과 같은 데이터를 보게 되어 Ablation 전체가 무의미해진다.
    """
    p = db_path(which)
    if p.exists():
        return p
    if which == "legacy":
        raise FileNotFoundError(
            f"{p} 없음.\n"
            f"  이 파일은 S0(기존 파이프라인 재현) 평가에만 필요하다.\n"
            f"  없으면 S0 을 건너뛰고 S1 을 상대 기준선으로 삼는다.\n"
            f"  대체 경로: {panel_path('legacy')} (legacy 베이스라인 패널) 가 있으면\n"
            f"  그 파일로 S0 을 평가할 수 있다.\n"
            f"  ※ 신 DB({DB_PATH_V2.name}) 로 폴백하지 않는다."
        )
    raise FileNotFoundError(
        f"{p} 없음. STAGE 6 선행작업 1번(portal_v2.duckdb 재빌드)을 먼저 실행할 것."
    )


def connect_db(which: str = "v2"):
    """읽기 전용 DuckDB 연결. 예외 없이 read_only=True 다."""
    import duckdb
    return duckdb.connect(str(require_db(which)), read_only=True)


def assert_db_writable(which: str) -> Path:
    """재빌드 스크립트가 쓰기 전에 호출한다. 구 DB 는 어떤 경우에도 쓰지 않는다."""
    p = db_path(which)
    if which == "legacy":
        raise PermissionError(
            f"{p} 는 보호 대상이다. 구 스키마 원본이며 S0 재현의 유일한 근거다. "
            f"덮어쓰기·수정 금지. 재빌드는 {DB_FILE['v2']} 로 한다."
        )
    return p


# ══════════════════════════════════════════════════════════════════════
# 모델 경로
# ══════════════════════════════════════════════════════════════════════
# legacy 2건은 STAGE 6 S0 베이스라인이다. 읽기만 하고 절대 다시 쓰지 않는다.
# 누수 포함 모델(230피처). Group E 정리에서 _archive/legacy_model/ 로 이동.
# docs/04 의 gain 수치가 이 파일의 feature_importance 에서 나왔다. 읽기 전용·덮어쓰기 금지.
MODEL_PATH_LEGACY_FULL = ARCHIVE_DIR / "legacy_model" / "lgbm_12m_model.txt"
MODEL_PATH_LEGACY_LEAN = ARCHIVE_DIR / "legacy_model" / "lgbm_12m_lean_model.txt"
MODEL_PATH_V2_FULL = OUTPUT_DIR / "lgbm_v2_full.txt"
MODEL_PATH_V2_LEAN = OUTPUT_DIR / "lgbm_v2_lean.txt"

PROTECTED_MODELS = frozenset({MODEL_PATH_LEGACY_FULL, MODEL_PATH_LEGACY_LEAN})

MODEL_PATH = {
    ("legacy", "full"): MODEL_PATH_LEGACY_FULL,
    ("legacy", "lean"): MODEL_PATH_LEGACY_LEAN,
    ("v2", "full"): MODEL_PATH_V2_FULL,
    ("v2", "lean"): MODEL_PATH_V2_LEAN,
}


def model_path(version: str = "v2", variant: str = "full") -> Path:
    key = (version, variant)
    if key not in MODEL_PATH:
        raise ValueError(f"알 수 없는 모델 키: {key} (가능: {sorted(MODEL_PATH)})")
    return MODEL_PATH[key]


def assert_model_writable(path) -> Path:
    """모델 저장 직전 가드. legacy 2건에 쓰려 하면 예외를 던진다."""
    p = Path(path).resolve()
    for prot in PROTECTED_MODELS:
        if p == prot.resolve() or Path(path).name == prot.name:
            raise PermissionError(
                f"{prot.name} 은 보호 대상이다. STAGE 6 S0 베이스라인 모델이므로 "
                f"덮어쓸 수 없다. 새 모델은 {MODEL_PATH_V2_FULL.name} / "
                f"{MODEL_PATH_V2_LEAN.name} 또는 시나리오별 파일명으로 저장할 것."
            )
    return Path(path)


# ══════════════════════════════════════════════════════════════════════
# LightGBM 모델 입출력 — 비ASCII 경로 우회
# ══════════════════════════════════════════════════════════════════════
# 프로젝트 경로에 한글이 들어 있다 ("바탕 화면", "NH AI경진대회").
# LightGBM 의 C++ 파일 IO 는 이 경로를 열지 못하고
#   LightGBMError: Could not open ...
# 로 죽는다. 파이썬 쪽에서 문자열로 읽고/쓰면 우회된다.
# 모델 저장은 반드시 save_booster 를 쓴다 — legacy 보호 가드가 여기 걸려 있다.

def load_booster(path):
    """model_file= 대신 model_str= 로 로드한다 (한글 경로 우회)."""
    import lightgbm as lgb
    return lgb.Booster(model_str=Path(path).read_text(encoding="utf-8"))


def save_booster(booster, path) -> Path:
    """부스터를 저장한다. legacy 2건에 쓰려 하면 assert_model_writable 이 막는다."""
    out = assert_model_writable(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    obj = getattr(booster, "booster_", booster)     # LGBMClassifier -> Booster
    out.write_text(obj.model_to_string(), encoding="utf-8")
    return out
