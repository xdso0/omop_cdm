"""이미 적재된 DB 스키마의 모든 CDM 테이블에서 중복(자연키 기준)을 제거.

파이프라인은 적재 시 자동으로 중복을 제거하지만, 기존에 쌓인 스키마를 한 번에
정리하고 싶을 때 사용한다.

사용 예:
    python scripts/dedupe_cdm.py --config config/pipeline.local.yaml          # output_db/스키마 사용
    python scripts/dedupe_cdm.py --url postgresql+psycopg2://u:p@host/db --schema cdm_gen
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import inspect  # noqa: E402
from omop_etl.config import load_config  # noqa: E402
from omop_etl.io import get_engine  # noqa: E402
from omop_etl.cdm_schema import CDM_COLUMNS  # noqa: E402
from omop_etl.dedupe import dedupe_db_table  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="DB CDM 스키마 중복 제거")
    ap.add_argument("--config", default=None)
    ap.add_argument("--url", default=None, help="SQLAlchemy URL (없으면 config.output_db)")
    ap.add_argument("--schema", default=None, help="대상 스키마 (없으면 config.output_schema)")
    args = ap.parse_args()

    cfg = load_config(args.config) if args.config else None
    url = args.url or (cfg.output_db if cfg else None)
    schema = args.schema or (cfg.output_schema if cfg else None)
    if not url:
        raise SystemExit("DB URL 필요: --url 또는 --config(output_db)")

    engine = get_engine(url)
    existing = set(inspect(engine).get_table_names(schema=schema))
    print(f"대상 스키마: {schema or '(default)'}\n")
    total = 0
    for table in CDM_COLUMNS:
        if table not in existing:
            continue
        d = dedupe_db_table(engine, table, schema=schema)
        total += d
        print(f"  {table}: 중복 {d:,} 행 삭제")
    print(f"\n완료: 총 {total:,} 행 제거")


if __name__ == "__main__":
    main()
