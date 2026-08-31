"""차주별 통합 시트만 단독 실행하는 스크립트."""
import sys, logging
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-5s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

from eda_pipeline.step1_load import RawLoader
from eda_pipeline.step4_borrower_sheet import BorrowerSheetBuilder

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--kr", action="store_true",
                    help="한글 헤더 병행본(nh_borrower_sheet_kr.csv)도 함께 생성")
    args = ap.parse_args()

    frames = RawLoader(data_dir="input").load_all()
    sheet  = BorrowerSheetBuilder(frames, output_dir="eda_pipeline/output",
                                  write_kr=args.kr).build()
    print(f"\n=== 완료 ===")
    print(f"Shape : {sheet.shape}")
    print(f"부도율: {sheet['IS_DEFAULT'].mean()*100:.4f}%")
    print(f"컬럼수: {len(sheet.columns)}")
    print(f"파일  : eda_pipeline/output/nh_borrower_sheet.csv")
