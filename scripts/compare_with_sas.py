"""생성 산출물 ↔ 기존 산출물 대조(검증용).

비교 기준이 될 기존 CDM 테이블(`*.sas7bdat`/csv)이 있으면, 본 패키지가 생성한
결과와 행 수·키·분포를 대조해 차이를 점검한다.

비교 항목
  - 행 수, 컬럼 집합
  - 키(예: person_id, occurrence_id) 고유개수 및 교집합/차집합
  - concept_id 분포 차이(상위)
  - 날짜 범위(min/max)

사용법::
    python scripts/compare_with_sas.py \
        --python output/condition_occurrence.parquet \
        --sas    D:/g/mappingTable/condition/condition_occurrence.sas7bdat \
        --keys person_id condition_occurrence_id \
        --concept condition_concept_id --date condition_start_date

대용량(.sas7bdat 수 GB)은 시간이 걸릴 수 있다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from omop_etl.io import read_sas, read_table  # noqa: E402


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.lower() for c in df.columns]
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="생성 산출물 ↔ 기존 산출물 대조")
    ap.add_argument("--python", required=True, help="Python 산출 파일(.parquet/.csv)")
    ap.add_argument("--sas", required=True, help="비교 기준이 될 기존 산출물(.sas7bdat)")
    ap.add_argument("--keys", nargs="*", default=["person_id"], help="비교할 키 컬럼들")
    ap.add_argument("--concept", default=None, help="분포 비교할 concept 컬럼")
    ap.add_argument("--date", default=None, help="범위 비교할 날짜 컬럼")
    ap.add_argument("--encoding", default="euc-kr")
    args = ap.parse_args()

    py = _norm(read_table(args.python))
    sas = _norm(read_sas(args.sas, encoding=args.encoding))
    print(f"Python : {args.python}  ({len(py):,} rows, {py.shape[1]} cols)")
    print(f"SAS    : {args.sas}  ({len(sas):,} rows, {sas.shape[1]} cols)\n")

    # 1) 행 수
    diff = len(py) - len(sas)
    print(f"[행 수] 생성 {len(py):,} / 기존 {len(sas):,}  (차이 {diff:+,}, "
          f"{100*len(py)/len(sas):.2f}%)" if len(sas) else "[행 수] 기존 0")

    # 2) 컬럼 집합
    only_py = set(py.columns) - set(sas.columns)
    only_sas = set(sas.columns) - set(py.columns)
    if only_py: print(f"[컬럼] Python 에만: {sorted(only_py)}")
    if only_sas: print(f"[컬럼] 기존에만: {sorted(only_sas)}")
    if not only_py and not only_sas: print("[컬럼] 동일")

    # 3) 키 비교
    for k in args.keys:
        if k in py.columns and k in sas.columns:
            sp, ss = set(py[k].dropna()), set(sas[k].dropna())
            inter = len(sp & ss)
            print(f"[키:{k}] 고유 생성 {len(sp):,} / 기존 {len(ss):,} / 교집합 {inter:,} "
                  f"/ 생성 only {len(sp-ss):,} / 기존 only {len(ss-sp):,}")

    # 4) concept 분포 (상위 차이)
    if args.concept and args.concept in py.columns and args.concept in sas.columns:
        vp = py[args.concept].value_counts()
        vs = sas[args.concept].value_counts()
        comp = pd.DataFrame({"python": vp, "sas": vs}).fillna(0).astype(int)
        comp["diff"] = comp["python"] - comp["sas"]
        comp = comp.reindex(comp["diff"].abs().sort_values(ascending=False).index)
        print(f"\n[concept:{args.concept}] 분포 차이 상위 10")
        print(comp.head(10).to_string())

    # 5) 날짜 범위
    if args.date and args.date in py.columns and args.date in sas.columns:
        dp = pd.to_datetime(py[args.date], errors="coerce")
        ds = pd.to_datetime(sas[args.date], errors="coerce")
        print(f"\n[날짜:{args.date}] Python [{dp.min()} ~ {dp.max()}] / "
              f"기존 [{ds.min()} ~ {ds.max()}]")


if __name__ == "__main__":
    main()
